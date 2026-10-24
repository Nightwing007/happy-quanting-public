from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import JSON, BigInteger, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, DecimalString, UTCDateTime

# side/type/status are plain strings in the database, not SQL enums: simpler SQLite
# migrations. These enums are the only legal values.


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class TradeDirection(StrEnum):
    LONG = "long"
    SHORT = "short"


class TradeProduct(StrEnum):
    """How a trade is held, which decides the charges and the margin.

    Indian longs are `delivery`; Indian shorts are `intraday` (shares you never owned cannot
    be delivered, so they must be bought back the same day). US and crypto shorts are
    `margin`: held as long as you like against blocked cash, charged like an ordinary trade.
    """

    DELIVERY = "delivery"
    INTRADAY = "intraday"
    MARGIN = "margin"


class TradeStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class ClosedHow(StrEnum):
    EXIT = "exit"  # the trade's own Exit button
    SELL = "sell"  # an ordinary sell order closed a long
    COVER = "cover"  # an ordinary buy order closed a short
    SQUARE_OFF = "square_off"  # the engine closed an Indian intraday short before the close
    STOP_LOSS = "stop_loss"  # the trade's stop-loss price was reached
    TARGET = "target"  # the trade's target price was reached


class OrderOrigin(StrEnum):
    USER = "user"
    SQUARE_OFF = "square_off"
    EXIT = "exit"  # the Exit button: POST /api/trades/{id}/exit
    STOP_LOSS = "stop_loss"  # placed by the engine when a trade's stop-loss was reached
    TARGET = "target"  # placed by the engine when a trade's target was reached


class LegKind(StrEnum):
    CLOSE_LONG = "close_long"
    OPEN_SHORT = "open_short"
    CLOSE_SHORT = "close_short"
    OPEN_LONG = "open_long"


class AccountKind(StrEnum):
    LIVE = "live"  # the person's own paper account; the only kind the background loop works on
    SIM = "sim"
    BACKTEST = "backtest"
    ALGO = "algo"  # an account an algorithm trades in


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    currency: Mapped[str] = mapped_column(String(3))
    cash: Mapped[Decimal] = mapped_column(DecimalString)
    starting_cash: Mapped[Decimal] = mapped_column(DecimalString)
    realized_pnl: Mapped[Decimal] = mapped_column(DecimalString)
    # Cash blocked by open shorts. Available cash is `cash - margin_used`; it cannot go below zero.
    margin_used: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    kind: Mapped[str] = mapped_column(String, default=AccountKind.LIVE)  # AccountKind
    # The owner, once there are users. No foreign key yet: the users table does not exist.
    user_id: Mapped[int | None] = mapped_column(nullable=True)
    # The broker chosen for each segment; see app/trading/brokers.py for the codes.
    broker_india: Mapped[str] = mapped_column(String, default="groww")
    broker_international: Mapped[str] = mapped_column(String, default="ibkr")
    broker_crypto: Mapped[str] = mapped_column(String, default="coindcx")


class Trade(Base):
    """One fill that opened something. Holdings are computed from open trades, so this table is
    the only record of what you own or owe (there is no second copy to drift).

    Money columns are account currency unless the name says otherwise. `quantity` is what the
    trade opened with; the other remaining-amount columns (`open_quantity`, `entry_value`,
    `entry_charges`, `cost_basis`, `margin_blocked`) shrink as parts of it are closed, in step.
    What a closed part paid is kept on the order that closed it (`Order.legs`), not here.
    """

    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_account_id_status", "account_id", "status"),
        Index("ix_trades_symbol", "symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", name="fk_trades_account_id_accounts")
    )
    symbol: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String(3))  # the instrument's
    market_code: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)  # TradeDirection
    product: Mapped[str] = mapped_column(String)  # TradeProduct
    quantity: Mapped[Decimal] = mapped_column(DecimalString)
    open_quantity: Mapped[Decimal] = mapped_column(DecimalString)
    entry_price: Mapped[Decimal] = mapped_column(DecimalString)  # instrument currency
    entry_fx_rate: Mapped[Decimal] = mapped_column(DecimalString)  # instrument -> account currency
    # Value of the open part at the entry price and rate: what a long paid for the shares or a
    # short sold them for, before charges. `cost_basis` is always `entry_value + entry_charges`.
    entry_value: Mapped[Decimal] = mapped_column(DecimalString)
    entry_charges: Mapped[Decimal] = mapped_column(DecimalString)  # the part still on the open quantity
    cost_basis: Mapped[Decimal] = mapped_column(DecimalString)
    margin_blocked: Mapped[Decimal] = mapped_column(DecimalString)  # shorts only; remaining
    financing_paid: Mapped[Decimal] = mapped_column(DecimalString)  # borrow or funding, so far
    financing_accrued_until: Mapped[datetime] = mapped_column(UTCDateTime)
    exit_value: Mapped[Decimal] = mapped_column(DecimalString)  # accumulated over partial exits
    exit_charges: Mapped[Decimal] = mapped_column(DecimalString)
    realized_pnl: Mapped[Decimal] = mapped_column(DecimalString)  # exits, less financing
    status: Mapped[str] = mapped_column(String)  # TradeStatus
    closed_how: Mapped[str | None] = mapped_column(String, nullable=True)  # ClosedHow
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # No foreign key: orders.trade_id already points the other way, and a pair of foreign keys
    # between two tables cannot be created or dropped in order. Null for a trade carried over
    # from the old positions table, whose opening order was not recorded per position.
    opened_by_order_id: Mapped[int | None] = mapped_column(nullable=True)
    # Protection, in the instrument's currency. One firing closes the trade, which clears both
    # (one-cancels-other, like a GTT pair). It lapses a year after it was set, also like a GTT.
    stop_price: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    protection_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_account_id_status", "account_id", "status"),
        Index("ix_orders_symbol", "symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", name="fk_orders_account_id_accounts")
    )
    symbol: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String(3))
    side: Mapped[str] = mapped_column(String)  # OrderSide
    type: Mapped[str] = mapped_column(String)  # OrderType
    quantity: Mapped[Decimal] = mapped_column(DecimalString)
    limit_price: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    status: Mapped[str] = mapped_column(String)  # OrderStatus
    fill_price: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    fx_rate: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    # Account-currency value of the shares traded, before charges.
    amount: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    realized_pnl: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    # What the fill cost, line by line: a list of ChargeOut dicts, written through that model.
    charges: Mapped[list] = mapped_column(JSON, default=list)
    charges_total: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal(0))
    reject_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # The trade this order acted on: the one an exit or square-off closes, otherwise the trade the
    # order opened (or, failing that, the first it closed). `legs` has the full story.
    trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("trades.id", name="fk_orders_trade_id"), nullable=True
    )
    origin: Mapped[str] = mapped_column(String, default=OrderOrigin.USER)  # OrderOrigin
    # What the fill did to cash: buy -(value + charges); sell +(value - charges); a short
    # -charges (margin is blocked, not spent); a cover (entry value - exit value) - charges.
    cash_change: Mapped[Decimal] = mapped_column(DecimalString, default=Decimal(0))
    # One entry per trade touched: a list of OrderLegOut dicts, written through that model, with
    # what each leg paid. Immutable, so a closed trade can still report its entry charges.
    legs: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "Squared off at 15:20 IST"
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    filled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uq_watchlist_items_account_id_symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", name="fk_watchlist_items_account_id_accounts")
    )
    symbol: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class BarCache(Base):
    """One fetched historical bar. `ts` is UTC unix seconds for every interval (a daily bar sits
    at its date's UTC midnight), so bars of any market and interval compare the same way."""

    __tablename__ = "bar_cache"
    __table_args__ = (UniqueConstraint("symbol", "interval", "ts", name="uq_bar_cache_symbol_interval_ts"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String)
    interval: Mapped[str] = mapped_column(String)
    ts: Mapped[int] = mapped_column(BigInteger)
    open: Mapped[Decimal] = mapped_column(DecimalString)
    high: Mapped[Decimal] = mapped_column(DecimalString)
    low: Mapped[Decimal] = mapped_column(DecimalString)
    close: Mapped[Decimal] = mapped_column(DecimalString)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)


class HistorySpan(Base):
    """A run of calendar days (both ends inclusive) already asked of the provider for a symbol and
    interval. Days inside it with no bars are weekends and holidays, so they are not asked again."""

    __tablename__ = "history_spans"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "interval", "start_date", name="uq_history_spans_symbol_interval_start_date"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String)
    interval: Mapped[str] = mapped_column(String)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)


class SimStatus(StrEnum):
    READY = "ready"  # made, cursor at the first bar, nothing played yet
    RUNNING = "running"  # the driver is advancing it at `speed` bars a second
    PAUSED = "paused"
    FINISHED = "finished"  # the cursor is at the end of the last bar


class SimSession(Base):
    """A past stretch of days played back through the real engine on an account of its own."""

    __tablename__ = "sim_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # The owner, once there are users (same as Account.user_id: no foreign key yet).
    owner_user_id: Mapped[int | None] = mapped_column(nullable=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", name="fk_sim_sessions_account_id_accounts")
    )
    symbols: Mapped[list] = mapped_column(JSON)
    interval: Mapped[str] = mapped_column(String, default="1m")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    speed: Mapped[int] = mapped_column(default=60)  # bars per second while running, 1-200
    # The replayed "now": the end of the last bar played. It starts at the first bar's start,
    # when no bar has finished yet.
    cursor: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String, default=SimStatus.READY)  # SimStatus
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class BacktestStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Backtest(Base):
    """A strategy run over a past date range, and what came of it.

    The scratch account the run traded in is deleted once `results` are stored, so the table
    holds the findings and nothing else piles up.
    """

    __tablename__ = "backtests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # The owner, once there are users (same as Account.user_id: no foreign key yet).
    owner_user_id: Mapped[int | None] = mapped_column(nullable=True)
    strategy_key: Mapped[str] = mapped_column(String)
    params: Mapped[dict] = mapped_column(JSON)  # as given, decimals as strings
    symbols: Mapped[list] = mapped_column(JSON)
    interval: Mapped[str] = mapped_column(String)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    starting_cash: Mapped[Decimal] = mapped_column(DecimalString)
    account_currency: Mapped[str] = mapped_column(String(3))
    brokers: Mapped[dict] = mapped_column(JSON)  # {"india": "groww", ...}
    status: Mapped[str] = mapped_column(String, default=BacktestStatus.QUEUED)  # BacktestStatus
    progress: Mapped[int] = mapped_column(default=0)  # percent, 0-100
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    results: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # BacktestResultsOut
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
