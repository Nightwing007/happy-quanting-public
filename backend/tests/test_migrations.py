from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session

from app.db import Base
from app.migrate import _alembic_config, upgrade_database
from app.models import Account, Order, OrderStatus, Trade


@pytest.fixture
def file_engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    yield engine
    engine.dispose()


def _upgrade_to(engine: Engine, revision: str) -> None:
    """Migrate part of the way, to build a database as an earlier release left it."""
    cfg = _alembic_config()
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)
        connection.commit()


def _version(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_migrations_match_models(file_engine: Engine) -> None:
    upgrade_database(file_engine)
    with file_engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "render_as_batch": True})
        diffs = compare_metadata(ctx, Base.metadata)
    assert diffs == [], f"models and migrations differ: {diffs}"
    assert _version(file_engine) == "0016"


def test_pre_migration_database_is_stamped_and_upgraded(file_engine: Engine) -> None:
    # A database made before migrations existed has the 0001 tables and no alembic_version.
    # (Base.metadata.create_all would build today's tables, which already have 0002's columns.)
    _upgrade_to(file_engine, "0001")
    with file_engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
    assert "alembic_version" not in inspect(file_engine).get_table_names()

    upgrade_database(file_engine)

    assert _version(file_engine) == "0016"
    # Running again is a no-op, not an error.
    upgrade_database(file_engine)
    assert _version(file_engine) == "0016"


def test_0001_database_with_data_upgrades_to_default_brokers(file_engine: Engine) -> None:
    _upgrade_to(file_engine, "0001")
    with file_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, currency, cash, starting_cash, realized_pnl, created_at) "
                "VALUES (1, 'USD', '97700.00', '100000', '0', '2026-03-02 10:30:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO orders (id, account_id, symbol, name, currency, side, type, quantity, "
                "status, fill_price, fx_rate, amount, created_at, filled_at) VALUES "
                "(1, 1, 'AAPL', 'Apple Inc.', 'USD', 'buy', 'market', '10', 'filled', '230', '1', "
                "'2300.00', '2026-03-02 10:30:00', '2026-03-02 10:30:00')"
            )
        )

    upgrade_database(file_engine)

    assert _version(file_engine) == "0016"
    with Session(file_engine) as session:
        account = session.query(Account).one()
        assert (account.broker_india, account.broker_international, account.broker_crypto) == (
            "groww",
            "ibkr",
            "coindcx",
        )
        assert account.cash == Decimal("97700.00")
        # The order was placed before charges existed, so it truthfully paid none.
        order = session.query(Order).one()
        assert order.charges == []
        assert order.charges_total == Decimal("0")
        assert order.amount == Decimal("2300.00")


def test_decimal_round_trip_is_exact(file_engine: Engine) -> None:
    upgrade_database(file_engine)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(file_engine) as session:
        session.add(
            Account(
                currency="USD",
                cash=Decimal("0.1"),
                starting_cash=Decimal("1234567.89"),
                realized_pnl=Decimal("0"),
                created_at=now,
            )
        )
        session.commit()
    with Session(file_engine) as session:
        account = session.query(Account).one()
        assert account.cash == Decimal("0.1")
        assert account.starting_cash == Decimal("1234567.89")
        assert isinstance(account.cash, Decimal)


def test_utc_datetime_round_trip_is_aware(file_engine: Engine) -> None:
    upgrade_database(file_engine)
    ist = timezone(timedelta(hours=5, minutes=30))
    # 10:00 IST is 04:30 UTC.
    created = datetime(2026, 3, 2, 10, 0, tzinfo=ist)
    with Session(file_engine) as session:
        session.add(
            Account(
                currency="USD",
                cash=Decimal("1"),
                starting_cash=Decimal("1"),
                realized_pnl=Decimal("0"),
                created_at=created,
            )
        )
        session.commit()
    with Session(file_engine) as session:
        got = session.query(Account).one().created_at
    assert got.tzinfo is not None
    assert got.utcoffset() == timedelta(0)
    assert got == created
    assert got == datetime(2026, 3, 2, 4, 30, tzinfo=UTC)


def test_naive_datetime_is_rejected(file_engine: Engine) -> None:
    upgrade_database(file_engine)
    with Session(file_engine) as session:
        session.add(
            Order(
                account_id=1,
                symbol="AAPL",
                name="Apple",
                currency="USD",
                side="buy",
                type="market",
                quantity=Decimal("1"),
                status=OrderStatus.OPEN,
                created_at=datetime(2026, 1, 1),  # naive
            )
        )
        with pytest.raises(Exception, match="timezone-aware"):
            session.flush()


def test_0002_position_becomes_one_open_long_trade_with_its_cost_intact(file_engine: Engine) -> None:
    _upgrade_to(file_engine, "0002")
    with file_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, currency, cash, starting_cash, realized_pnl, created_at, "
                "broker_india, broker_international, broker_crypto) VALUES "
                "(1, 'INR', '987470.41', '1000000', '0', '2026-03-02 04:00:00', 'groww', 'ibkr', 'coindcx')"
            )
        )
        # A filled buy of 10 RELIANCE.NS at 1250 (value 12500.00, charges 29.59) and a cancelled
        # order, so the cash-change backfill sees both kinds.
        conn.execute(
            text(
                "INSERT INTO orders (id, account_id, symbol, name, currency, side, type, quantity, status, "
                "fill_price, fx_rate, amount, charges, charges_total, created_at, filled_at) VALUES "
                "(1, 1, 'RELIANCE.NS', 'Reliance', 'INR', 'buy', 'market', '10', 'filled', '1250', '1', "
                "'12500.00', '[]', '29.59', '2026-03-02 04:30:00', '2026-03-02 04:30:00'), "
                "(2, 1, 'RELIANCE.NS', 'Reliance', 'INR', 'buy', 'limit', '5', 'cancelled', NULL, NULL, "
                "NULL, '[]', '0', '2026-03-02 05:00:00', NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO positions (id, account_id, symbol, name, currency, quantity, avg_price, "
                "cost_basis) VALUES (1, 1, 'RELIANCE.NS', 'Reliance', 'INR', '10', '1250', '12529.59')"
            )
        )

    upgrade_database(file_engine)

    assert "positions" not in inspect(file_engine).get_table_names()
    with Session(file_engine) as session:
        trade = session.query(Trade).one()
        # Carried over exactly. The charges inside the cost were not stored separately, so the
        # whole cost sits in entry_value and entry_charges is 0.
        assert (trade.direction, trade.product, trade.status) == ("long", "delivery", "open")
        assert (trade.quantity, trade.open_quantity, trade.entry_price) == (
            Decimal("10"), Decimal("10"), Decimal("1250"),
        )  # fmt: skip
        assert trade.cost_basis == Decimal("12529.59")
        assert (trade.entry_value, trade.entry_charges) == (Decimal("12529.59"), Decimal("0"))
        assert (trade.margin_blocked, trade.financing_paid) == (Decimal("0"), Decimal("0"))
        assert (trade.market_code, trade.currency, trade.entry_fx_rate) == ("NSE", "INR", Decimal("1"))
        assert trade.opened_by_order_id == 1
        assert trade.opened_at == datetime(2026, 3, 2, 4, 30, tzinfo=UTC)
        account = session.query(Account).one()
        assert account.margin_used == Decimal("0")
        buy, cancelled = session.query(Order).order_by(Order.id).all()
        # cash change of the filled buy: -(12500.00 + 29.59); nothing for the cancelled order
        assert buy.cash_change == Decimal("-12529.59")
        assert cancelled.cash_change == Decimal("0")
        assert (buy.origin, buy.legs, buy.trade_id) == ("user", [], None)


def test_0003_downgrade_rebuilds_positions_from_open_long_trades(file_engine: Engine) -> None:
    upgrade_database(file_engine)
    with file_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, currency, cash, starting_cash, realized_pnl, created_at, "
                "broker_india, broker_international, broker_crypto, margin_used, kind) VALUES "
                "(1, 'USD', '100000', '100000', '0', '2026-03-02 04:00:00', 'groww', 'ibkr', 'coindcx', "
                "'0', 'live')"
            )
        )
        for i, (qty, price, basis) in enumerate((("10", "100", "1001.00"), ("10", "110", "1102.00")), 1):
            conn.execute(
                text(
                    "INSERT INTO trades (id, account_id, symbol, name, currency, market_code, direction, "
                    "product, quantity, open_quantity, entry_price, entry_fx_rate, entry_value, "
                    "entry_charges, cost_basis, margin_blocked, financing_paid, financing_accrued_until, "
                    "exit_value, exit_charges, realized_pnl, status, opened_at) VALUES "
                    f"({i}, 1, 'AAPL', 'Apple', 'USD', 'US', 'long', 'delivery', '{qty}', '{qty}', "
                    f"'{price}', '1', '{basis}', '0', '{basis}', '0', '0', '2026-03-02 04:00:00', "
                    "'0', '0', '0', 'open', '2026-03-02 04:00:00')"
                )
            )
    cfg = _alembic_config()
    with file_engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0002")
        connection.commit()
    assert _version(file_engine) == "0002"
    with file_engine.connect() as conn:
        row = conn.execute(text("SELECT quantity, avg_price, cost_basis FROM positions")).one()
    # 20 shares; average (10 x 100 + 10 x 110) / 20 = 105; cost 1001.00 + 1102.00 = 2103.00
    quantity, average, basis = (Decimal(v) for v in row)
    assert (quantity, average, basis) == (Decimal("20"), Decimal("105"), Decimal("2103.00"))


def test_0004_adds_empty_protection_columns_and_keeps_existing_trades(file_engine: Engine) -> None:
    _upgrade_to(file_engine, "0003")
    with file_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, currency, cash, starting_cash, realized_pnl, created_at, "
                "broker_india, broker_international, broker_crypto, margin_used) VALUES "
                "(1, 'USD', '100000', '100000', '0', '2026-03-02 04:00:00', 'groww', 'ibkr', 'coindcx', '0')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO trades (id, account_id, symbol, name, currency, market_code, direction, "
                "product, quantity, open_quantity, entry_price, entry_fx_rate, entry_value, "
                "entry_charges, cost_basis, margin_blocked, financing_paid, financing_accrued_until, "
                "exit_value, exit_charges, realized_pnl, status, opened_at) VALUES "
                "(1, 1, 'AAPL', 'Apple', 'USD', 'US', 'long', 'delivery', '10', '10', '100', '1', "
                "'1000.00', '1.00', '1001.00', '0', '0', '2026-03-02 04:00:00', "
                "'0', '0', '0', 'open', '2026-03-02 04:00:00')"
            )
        )

    upgrade_database(file_engine)

    assert _version(file_engine) == "0016"
    with Session(file_engine) as session:
        trade = session.query(Trade).one()
        assert (trade.symbol, trade.open_quantity) == ("AAPL", Decimal("10"))
        assert trade.cost_basis == Decimal("1001.00")
        assert (trade.stop_price, trade.target_price, trade.protection_expires_at) == (None, None, None)


def test_0005_makes_every_existing_account_live(file_engine: Engine) -> None:
    _upgrade_to(file_engine, "0004")
    with file_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, currency, cash, starting_cash, realized_pnl, created_at, "
                "broker_india, broker_international, broker_crypto, margin_used) VALUES "
                "(1, 'USD', '100000', '100000', '0', '2026-03-02 04:00:00', 'groww', 'ibkr', 'coindcx', '0')"
            )
        )

    upgrade_database(file_engine)

    assert _version(file_engine) == "0016"
    with Session(file_engine) as session:
        account = session.query(Account).one()
        # 0010 later hands every ownerless account to the demo user (id 1 here).
        assert (account.kind, account.user_id, account.cash) == ("live", 1, Decimal("100000"))


def test_0010_gives_existing_rows_to_the_demo_user(file_engine: Engine) -> None:
    _upgrade_to(file_engine, "0009")
    with file_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, currency, cash, starting_cash, realized_pnl, created_at, "
                "broker_india, broker_international, broker_crypto, margin_used, kind) VALUES "
                "(1, 'USD', '100000', '100000', '0', '2026-03-02 04:00:00', 'groww', 'ibkr', 'coindcx', '0', "
                "'live')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO user_algos (id, name, description, strategy_key, params, created_at) VALUES "
                "(1, 'a', '', 'sma_cross', '{}', '2026-03-02 04:00:00')"
            )
        )

    upgrade_database(file_engine)

    with file_engine.connect() as conn:
        demo = conn.execute(text("SELECT id, password_hash FROM users WHERE username = 'demo'")).one()
        assert demo.password_hash == "!"
        assert conn.execute(text("SELECT user_id FROM accounts")).scalar_one() == demo.id
        assert conn.execute(text("SELECT owner_user_id FROM user_algos")).scalar_one() == demo.id
