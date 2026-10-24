"""trades and short selling

Positions become trades: each existing position turns into one open long delivery trade that
carries its cost exactly. Orders gain a trade pointer, an origin, the cash they moved and the
legs they were made of; accounts gain the margin their shorts block.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24 08:47:57.958186
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


D0 = Decimal(0)


def _market_code(symbol: str) -> str:
    """The market a Yahoo symbol trades on, by the same rule as `markets.market_for`: no suffix
    is US, a '-USD' pair is crypto, otherwise the suffix names the market."""
    from app.trading.markets import _BY_SUFFIX  # the suffix table only; read at migration time

    if "." not in symbol:
        return "CRYPTO" if symbol.endswith("-USD") else "US"
    found = _BY_SUFFIX.get("." + symbol.rsplit(".", 1)[1].upper())
    return found.code if found else "US"


def _create_trades() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("market_code", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("product", sa.String(), nullable=False),
        sa.Column("quantity", app.db.DecimalString(), nullable=False),
        sa.Column("open_quantity", app.db.DecimalString(), nullable=False),
        sa.Column("entry_price", app.db.DecimalString(), nullable=False),
        sa.Column("entry_fx_rate", app.db.DecimalString(), nullable=False),
        sa.Column("entry_value", app.db.DecimalString(), nullable=False),
        sa.Column("entry_charges", app.db.DecimalString(), nullable=False),
        sa.Column("cost_basis", app.db.DecimalString(), nullable=False),
        sa.Column("margin_blocked", app.db.DecimalString(), nullable=False),
        sa.Column("financing_paid", app.db.DecimalString(), nullable=False),
        sa.Column("financing_accrued_until", app.db.UTCDateTime(), nullable=False),
        sa.Column("exit_value", app.db.DecimalString(), nullable=False),
        sa.Column("exit_charges", app.db.DecimalString(), nullable=False),
        sa.Column("realized_pnl", app.db.DecimalString(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("closed_how", sa.String(), nullable=True),
        sa.Column("opened_at", app.db.UTCDateTime(), nullable=False),
        sa.Column("closed_at", app.db.UTCDateTime(), nullable=True),
        sa.Column("opened_by_order_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_trades_account_id_accounts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trades")),
    )
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.create_index("ix_trades_account_id_status", ["account_id", "status"], unique=False)
        batch_op.create_index("ix_trades_symbol", ["symbol"], unique=False)


def _positions_to_trades(bind: sa.Connection) -> None:
    """One open long delivery trade per position, with its cost carried over exactly.

    `entry_charges` is set to 0: a position stored only the total it cost (charges included),
    and the exchange rate at buy time was not stored, so the charges inside it cannot be
    separated out. `entry_value` is therefore the whole `cost_basis`, which keeps
    cost_basis = entry_value + entry_charges and every total unchanged.
    """
    positions = bind.execute(
        sa.text("SELECT account_id, symbol, name, currency, quantity, avg_price, cost_basis FROM positions")
    ).all()
    for account_id, symbol, name, currency, quantity, avg_price, cost_basis in positions:
        # The buys that built the position are still in the order history. Its opening time is the
        # first of them; the rate is the latest one's (the best guess at the rate behind the cost).
        buys = bind.execute(
            sa.text(
                "SELECT id, fx_rate, filled_at FROM orders WHERE account_id = :a AND symbol = :s "
                "AND side = 'buy' AND status = 'filled' ORDER BY filled_at, id"
            ),
            {"a": account_id, "s": symbol},
        ).all()
        if buys:
            order_id, opened_at = buys[0][0], buys[0][2]
            fx_rate = buys[-1][1] or "1"
        else:
            order_id, fx_rate = None, "1"
            opened_at = bind.execute(
                sa.text("SELECT created_at FROM accounts WHERE id = :a"), {"a": account_id}
            ).scalar_one()
        bind.execute(
            sa.text(
                "INSERT INTO trades (account_id, symbol, name, currency, market_code, direction, product, "
                "quantity, open_quantity, entry_price, entry_fx_rate, entry_value, entry_charges, "
                "cost_basis, margin_blocked, financing_paid, financing_accrued_until, exit_value, "
                "exit_charges, realized_pnl, status, closed_how, opened_at, closed_at, opened_by_order_id) "
                "VALUES (:account_id, :symbol, :name, :currency, :market, 'long', 'delivery', "
                ":quantity, :quantity, :avg_price, :fx, :cost_basis, '0', :cost_basis, '0', '0', "
                ":opened_at, '0', '0', '0', 'open', NULL, :opened_at, NULL, :order_id)"
            ),
            {
                "account_id": account_id, "symbol": symbol, "name": name, "currency": currency,
                "market": _market_code(symbol), "quantity": quantity, "avg_price": avg_price,
                "fx": fx_rate, "cost_basis": cost_basis, "opened_at": opened_at, "order_id": order_id,
            },
        )  # fmt: skip


def _backfill_cash_change(bind: sa.Connection) -> None:
    """What each filled order did to cash, from the amounts it already stores."""
    rows = bind.execute(
        sa.text("SELECT id, side, amount, charges_total FROM orders WHERE status = 'filled'")
    ).all()
    for order_id, side, amount, charges_total in rows:
        amount, charges = Decimal(amount or "0"), Decimal(charges_total or "0")
        change = -(amount + charges) if side == "buy" else amount - charges
        bind.execute(
            sa.text("UPDATE orders SET cash_change = :c WHERE id = :i"), {"c": f"{change:f}", "i": order_id}
        )


def upgrade() -> None:
    bind = op.get_bind()
    _create_trades()

    # NOT NULL columns need a default while existing rows get filled; the defaults are dropped
    # again below so the schema matches the models (which default in Python).
    # No account had a short, so no margin was in use; every order was user-placed and had no legs.
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("margin_used", app.db.DecimalString(), nullable=False, server_default="0")
        )
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trade_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("origin", sa.String(), nullable=False, server_default="user"))
        batch_op.add_column(
            sa.Column("cash_change", app.db.DecimalString(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("legs", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("note", sa.String(), nullable=True))
        batch_op.create_foreign_key("fk_orders_trade_id", "trades", ["trade_id"], ["id"])

    _backfill_cash_change(bind)
    _positions_to_trades(bind)
    op.drop_table("positions")

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.alter_column("margin_used", existing_type=app.db.DecimalString(), server_default=None)
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.alter_column("origin", existing_type=sa.String(), server_default=None)
        batch_op.alter_column("cash_change", existing_type=app.db.DecimalString(), server_default=None)
        batch_op.alter_column("legs", existing_type=sa.JSON(), server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    shorts = bind.execute(
        sa.text("SELECT COUNT(*) FROM trades WHERE status = 'open' AND direction = 'short'")
    ).scalar_one()
    if shorts:
        # The old schema cannot hold a short, and dropping one would silently lose the margin
        # and the obligation to buy it back.
        raise RuntimeError(f"Close your {shorts} open short trade(s) before downgrading to 0002.")

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("quantity", app.db.DecimalString(), nullable=False),
        sa.Column("avg_price", app.db.DecimalString(), nullable=False),
        sa.Column("cost_basis", app.db.DecimalString(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_positions_account_id_accounts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_positions")),
        sa.UniqueConstraint("account_id", "symbol", name="uq_positions_account_id_symbol"),
    )
    # Open long trades pool back into one position per symbol (average cost, as before).
    rows = bind.execute(
        sa.text(
            "SELECT account_id, symbol, name, currency, open_quantity, entry_price, cost_basis "
            "FROM trades WHERE status = 'open' AND direction = 'long' ORDER BY opened_at, id"
        )
    ).all()
    pooled: dict[tuple[int, str], dict] = {}
    for account_id, symbol, name, currency, quantity, price, cost_basis in rows:
        p = pooled.setdefault(
            (account_id, symbol),
            {"name": name, "currency": currency, "quantity": D0, "paid": D0, "cost": D0},
        )
        q = Decimal(quantity)
        p["quantity"] += q
        p["paid"] += q * Decimal(price)
        p["cost"] += Decimal(cost_basis)
    for (account_id, symbol), p in pooled.items():
        average = (p["paid"] / p["quantity"]).quantize(Decimal("1E-8"))
        bind.execute(
            sa.text(
                "INSERT INTO positions (account_id, symbol, name, currency, quantity, avg_price, cost_basis) "
                "VALUES (:a, :s, :n, :c, :q, :p, :b)"
            ),
            {
                "a": account_id, "s": symbol, "n": p["name"], "c": p["currency"],
                "q": f"{p['quantity']:f}", "p": f"{average:f}", "b": f"{p['cost']:f}",
            },
        )  # fmt: skip

    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_constraint("fk_orders_trade_id", type_="foreignkey")
        batch_op.drop_column("note")
        batch_op.drop_column("legs")
        batch_op.drop_column("cash_change")
        batch_op.drop_column("origin")
        batch_op.drop_column("trade_id")
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_column("margin_used")
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.drop_index("ix_trades_symbol")
        batch_op.drop_index("ix_trades_account_id_status")
    op.drop_table("trades")
