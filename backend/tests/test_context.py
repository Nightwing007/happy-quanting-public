"""Engine context tests: accounts that trade side by side, each on its own clock, and never see
each other's orders, trades, cash or payouts.

Fake prices: AAPL 230, RELIANCE.NS 1250 INR. These tests are about who owns what, not about
charges, so they trade for free.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import main
from app.api.deps import get_live_context
from app.main import app
from app.market_data.fake import FakeProvider
from app.models import (
    Account,
    AccountKind,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Trade,
    TradeStatus,
    User,
)
from app.trading import engine, watchlist
from app.trading.context import TradingContext
from app.trading.errors import OrderNotFound, TradeNotFound
from tests.helpers import live

D = Decimal
pytestmark = pytest.mark.usefixtures("zero_costs")

CREATED = datetime(2025, 1, 1, tzinfo=UTC)


class Clock:
    """A clock a test can set, standing in for one account's idea of the time."""

    def __init__(self, when: datetime) -> None:
        self.when = when

    def __call__(self) -> datetime:
        return self.when


def make_account(
    db: Session, kind: str = AccountKind.SIM, cash: str = "50000", currency: str = "USD"
) -> Account:
    account = Account(
        currency=currency,
        cash=D(cash),
        starting_cash=D(cash),
        realized_pnl=D(0),
        margin_used=D(0),
        created_at=CREATED,
        kind=kind,
    )
    db.add(account)
    db.commit()
    return account


def context(db: Session, account: Account, provider: FakeProvider, clock: Clock) -> TradingContext:
    return TradingContext(db, account, provider, clock)


def buy(ctx: TradingContext, symbol: str, qty: str, **kw) -> Order:
    return engine.place_order(
        ctx, symbol=symbol, side=OrderSide.BUY, type=kw.pop("type", OrderType.MARKET), quantity=D(qty), **kw
    )


def sell(ctx: TradingContext, symbol: str, qty: str, **kw) -> Order:
    return engine.place_order(
        ctx, symbol=symbol, side=OrderSide.SELL, type=kw.pop("type", OrderType.MARKET), quantity=D(qty), **kw
    )


def trades_of(db: Session, account: Account) -> list[Trade]:
    return list(db.scalars(select(Trade).where(Trade.account_id == account.id).order_by(Trade.id)))


def orders_of(db: Session, account: Account) -> list[Order]:
    return list(db.scalars(select(Order).where(Order.account_id == account.id).order_by(Order.id)))


@pytest.fixture
def two(db: Session, fake_provider: FakeProvider) -> tuple[TradingContext, TradingContext]:
    """The live account (March 2026) and a sim account (June 2025), each on its own clock."""
    live = context(db, engine.get_account(db), fake_provider, Clock(datetime(2026, 3, 2, 10, 0, tzinfo=UTC)))
    live.account.cash = live.account.starting_cash = D("100000")
    db.commit()
    sim = context(
        db, make_account(db, cash="50000"), fake_provider, Clock(datetime(2025, 6, 1, 12, 0, tzinfo=UTC))
    )
    return live, sim


def test_two_accounts_trade_side_by_side_on_their_own_clocks(
    db: Session, fake_provider: FakeProvider, two: tuple[TradingContext, TradingContext]
):
    a, b = two
    # A: 10 AAPL at 230 = 2300, cash 100000 - 2300 = 97700. B: 5 x 230 = 1150, cash 50000 - 1150 = 48850.
    order_a = buy(a, "AAPL", "10")
    order_b = buy(b, "AAPL", "5")
    assert (order_a.created_at, order_b.created_at) == (a.now(), b.now())
    assert (a.account.cash, b.account.cash) == (D("97700.00"), D("48850.00"))
    [trade_a] = trades_of(db, a.account)
    [trade_b] = trades_of(db, b.account)
    assert (trade_a.opened_at, trade_b.opened_at) == (a.now(), b.now())
    assert (trade_a.open_quantity, trade_b.open_quantity) == (D("10"), D("5"))

    # Protection is set on each clock: a year after the account's own now.
    engine.set_protection(a, trade_a.id, D("200"), None)
    engine.set_protection(b, trade_b.id, D("100"), None)
    assert trade_a.protection_expires_at == datetime(2027, 3, 2, 10, 0, tzinfo=UTC)
    assert trade_b.protection_expires_at == datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    # A resting limit order in A. At 200 it is reachable, but B's pass must not touch it.
    resting = buy(a, "AAPL", "1", type=OrderType.LIMIT, limit_price=D("200"))
    assert resting.status == OrderStatus.OPEN
    fake_provider.set_price("AAPL", D("200"))
    assert engine.fill_open_orders(b) == 0
    assert resting.status == OrderStatus.OPEN
    # It fills at the market price, 200: cash 97700 - 200 = 97500.
    assert engine.fill_open_orders(a) == 1
    assert (resting.status, resting.filled_at, a.account.cash) == (OrderStatus.FILLED, a.now(), D("97500.00"))

    # At 190 A's stop (200) is hit and B's (100) is not. A's clock has moved on; B's has not.
    fake_provider.set_price("AAPL", D("190"))
    a.now.when += timedelta(hours=1)
    assert engine.trigger_protected_trades(b) == 0
    assert engine.trigger_protected_trades(a) == 1
    assert (trade_a.status, trade_a.closed_how, trade_a.closed_at) == (
        TradeStatus.CLOSED, "stop_loss", datetime(2026, 3, 2, 11, 0, tzinfo=UTC)
    )  # fmt: skip
    assert (trade_b.status, trade_b.stop_price) == (TradeStatus.OPEN, D("100.00000000"))

    # A sold 10 at 190 = 1900: cash 97500 + 1900 = 99400, realized 1900 - 2300 = -400.
    # B is untouched: cash 48850, 5 shares now worth 950, so value 49800 and P&L -200.
    assert (a.account.cash, a.account.realized_pnl) == (D("99400.00"), D("-400.00"))
    assert (b.account.cash, b.account.realized_pnl) == (D("48850.00"), D("0"))
    pf_a, pf_b = engine.get_portfolio(a), engine.get_portfolio(b)
    # A: the 1 share bought at 200 is worth 190: value 99400 + 190 = 99590, P&L -410.
    assert [(h.symbol, h.quantity) for h in pf_a.holdings] == [("AAPL", D("1"))]
    assert (pf_a.total_value, pf_a.total_pnl) == (D("99590.00"), D("-410.00"))
    assert [(h.symbol, h.quantity) for h in pf_b.holdings] == [("AAPL", D("5"))]
    assert (pf_b.total_value, pf_b.total_pnl) == (D("49800.00"), D("-200.00"))
    assert len(orders_of(db, a.account)) == 3 and len(orders_of(db, b.account)) == 1
    # Payouts: A closed one trade; B none.
    assert engine.get_payouts(a).totals.trades_closed == 1
    assert engine.get_payouts(b).totals.trades_closed == 0


@pytest.mark.real_calendar
def test_square_off_follows_each_accounts_own_clock(
    db: Session, fake_provider: FakeProvider, two: tuple[TradingContext, TradingContext]
):
    a, b = two
    for ctx in (a, b):
        ctx.account.currency = "INR"
        ctx.account.cash = ctx.account.starting_cash = D("1000000")
    db.commit()
    # A quote from the NSE's current session (it opened at 03:45 UTC), whatever the real date is.
    fake_provider.set_as_of("RELIANCE.NS", int(datetime(2026, 3, 2, 5, 0, tzinfo=UTC).timestamp()))
    # Monday 2026-03-02 10:30 IST (05:00 UTC): NSE open until 15:30 IST. Both go short 10.
    a.now.when = b.now.when = datetime(2026, 3, 2, 5, 0, tzinfo=UTC)
    sell(a, "RELIANCE.NS", "10")
    sell(b, "RELIANCE.NS", "10")
    assert (a.account.margin_used, b.account.margin_used) == (D("2500.00"), D("2500.00"))  # 20% of 12500

    a.now.when = datetime(2026, 3, 2, 9, 49, tzinfo=UTC)  # 15:19 IST: a minute early
    b.now.when = datetime(2026, 3, 2, 9, 50, tzinfo=UTC)  # 15:20 IST: ten minutes before the close
    assert engine.square_off_due(a) == []
    [order] = engine.square_off_due(b)
    assert (order.account_id, order.origin, order.note) == (
        b.account.id, "square_off", "Squared off at 15:20 IST."
    )  # fmt: skip
    assert (a.account.margin_used, b.account.margin_used) == (D("2500.00"), D("0"))
    assert [t.status for t in trades_of(db, a.account)] == ["open"]
    assert [t.status for t in trades_of(db, b.account)] == ["closed"]
    # B's pass is done; A's own clock reaches 15:20 and then its turn comes.
    assert engine.square_off_due(b) == []
    a.now.when = datetime(2026, 3, 2, 9, 50, tzinfo=UTC)
    [order_a] = engine.square_off_due(a)
    assert (order_a.account_id, order_a.created_at) == (a.account.id, a.now())
    assert a.account.margin_used == D("0")


# --- nothing leaks -------------------------------------------------------------------------


@pytest.fixture
def busy_and_empty(
    db: Session, fake_provider: FakeProvider, two: tuple[TradingContext, TradingContext]
) -> tuple[TradingContext, TradingContext]:
    """Account A has done everything an account can: an open trade with protection, a closed
    trade with a payout, a resting order that could fill, a stop that could fire, a watchlist.
    Account B has done nothing."""
    a, b = two
    buy(a, "AAPL", "10")
    buy(a, "AAPL", "4")
    first, second = trades_of(db, a.account)
    engine.exit_trade(a, second.id)  # a closed trade, so there is a payout
    engine.set_protection(a, first.id, D("200"), D("300"))
    buy(a, "AAPL", "1", type=OrderType.LIMIT, limit_price=D("220"))  # resting; 230 is above it
    sell(a, "AAPL", "2", type=OrderType.LIMIT, limit_price=D("250"))  # resting sell promises shares
    fake_provider.set_price("AAPL", D("190"))  # now both the buy limit and the stop are reachable
    return a, b


def test_account_b_reads_nothing_of_account_a(busy_and_empty: tuple[TradingContext, TradingContext]):
    a, b = busy_and_empty
    assert len(trades_of(b.db, a.account)) == 2 and len(orders_of(b.db, a.account)) >= 4  # A really is busy
    assert engine.get_payouts(a).totals.trades_closed == 1
    assert [i for i, _ in watchlist.list_items(a)] != []

    pf = engine.get_portfolio(b)
    assert (pf.holdings, pf.trades) == ([], [])
    assert (pf.cash, pf.starting_cash, pf.invested, pf.market_value, pf.short_value) == (
        D("50000"), D("50000"), D("0"), D("0"), D("0")
    )  # fmt: skip
    assert (pf.realized_pnl, pf.unrealized_pnl, pf.total_pnl, pf.financing_paid) == (D(0), D(0), D(0), D(0))
    assert pf.charges_paid.total == D("0")


EMPTY_READS = {
    "list_trades": lambda ctx: engine.list_trades(ctx),
    "list_trades_closed": lambda ctx: engine.list_trades(ctx, status="closed"),
    "list_trades_open": lambda ctx: engine.list_trades(ctx, status="open"),
    "list_trades_by_symbol": lambda ctx: engine.list_trades(ctx, symbol="AAPL"),
    "payouts": lambda ctx: engine.get_payouts(ctx).payouts,
    "portfolio_trades": lambda ctx: engine.get_portfolio(ctx).trades,
    "portfolio_holdings": lambda ctx: engine.get_portfolio(ctx).holdings,
    "open_trades_of_symbol": lambda ctx: engine._open_trades(ctx, "AAPL"),
    "open_trades_of_account": lambda ctx: engine._open_trades_of_account(ctx),
    "orders": lambda ctx: orders_of(ctx.db, ctx.account),
    "watchlist": lambda ctx: watchlist.list_items(ctx),
    "fill_open_orders": lambda ctx: [] if engine.fill_open_orders(ctx) == 0 else ["filled"],
    "trigger_protected_trades": lambda ctx: [] if engine.trigger_protected_trades(ctx) == 0 else ["fired"],
    "square_off_due": lambda ctx: engine.square_off_due(ctx),
    "accrue_financing": lambda ctx: [] if engine.accrue_financing(ctx) == 0 else ["charged"],
    "promised": lambda ctx: [] if engine._promised(ctx, "AAPL") == 0 else ["promised"],
}


@pytest.mark.parametrize("read", EMPTY_READS.values(), ids=EMPTY_READS.keys())
def test_every_read_path_of_account_b_is_empty(read, busy_and_empty: tuple[TradingContext, TradingContext]):
    a, b = busy_and_empty
    assert read(b) == []
    # ...and the same read on A is not, so the table is not passing by accident (the background
    # steps are the exception: they return a count that the table turns into a list).
    if read not in (EMPTY_READS["accrue_financing"], EMPTY_READS["square_off_due"]):
        assert read(a) != []


def test_account_b_cannot_reach_account_as_trades_or_orders(
    db: Session, busy_and_empty: tuple[TradingContext, TradingContext]
):
    a, b = busy_and_empty
    [open_trade] = [t for t in trades_of(db, a.account) if t.status == TradeStatus.OPEN]
    [closed_trade] = [t for t in trades_of(db, a.account) if t.status == TradeStatus.CLOSED]
    resting = next(o for o in orders_of(db, a.account) if o.status == OrderStatus.OPEN)
    for trade in (open_trade, closed_trade):
        with pytest.raises(TradeNotFound):
            engine.get_trade_view(b, trade.id)
        with pytest.raises(TradeNotFound):
            engine.exit_trade(b, trade.id)
        with pytest.raises(TradeNotFound):
            engine.preview_exit(b, trade.id)
        with pytest.raises(TradeNotFound):
            engine.set_protection(b, trade.id, D("100"), None)
        with pytest.raises(TradeNotFound):
            engine.preview_protection(b, trade.id, D("100"), None)
    with pytest.raises(OrderNotFound):
        engine.cancel_order(b, resting.id)
    assert resting.status == OrderStatus.OPEN
    assert open_trade.stop_price == D("200")


def test_a_sell_in_one_account_never_closes_the_others_longs(
    db: Session, busy_and_empty: tuple[TradingContext, TradingContext]
):
    a, b = busy_and_empty
    [held] = [t for t in trades_of(db, a.account) if t.status == TradeStatus.OPEN]
    before = (held.open_quantity, held.status, a.account.cash)
    # B owns no AAPL, so this sell is a short in B (US shorts are offered): it must not consume A's 10.
    sell(b, "AAPL", "3")
    [short] = trades_of(db, b.account)
    assert (short.direction, short.open_quantity) == ("short", D("3"))
    assert (held.open_quantity, held.status, a.account.cash) == before


def test_resetting_one_account_leaves_the_others_books_alone(
    db: Session, busy_and_empty: tuple[TradingContext, TradingContext]
):
    a, b = busy_and_empty
    trades_before = len(trades_of(db, a.account))
    orders_before = len(orders_of(db, a.account))
    cash_before = a.account.cash
    buy(b, "AAPL", "1")
    engine.reset_account(b)
    assert (trades_of(db, b.account), orders_of(db, b.account), b.account.cash) == ([], [], D("50000"))
    assert (len(trades_of(db, a.account)), len(orders_of(db, a.account)), a.account.cash) == (
        trades_before, orders_before, cash_before
    )  # fmt: skip
    total = db.scalar(select(func.count()).select_from(Trade))
    assert total == trades_before


# --- accounts and the app ------------------------------------------------------------------


def test_new_accounts_are_live_by_default_owned_by_demo(db: Session):
    live = engine.get_account(db)
    assert db.get(User, live.user_id).username == "demo"
    assert live.kind == AccountKind.LIVE
    sim = make_account(db, AccountKind.SIM)
    assert engine.get_account(db).id == live.id  # the live account stays the one the app shows
    assert [a.id for a in engine.live_accounts(db)] == [live.id]
    assert sim.kind == "sim"


def test_the_live_context_follows_a_replaced_clock(
    db: Session, fake_provider: FakeProvider, fixed_clock: datetime
):
    ctx = live(db, fake_provider)
    assert ctx.now() == fixed_clock
    assert ctx.account.id == engine.get_account(db).id


def test_the_background_loop_works_on_live_accounts_only(
    db: Session, fake_provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
):
    live = context(db, engine.get_account(db), fake_provider, Clock(datetime(2026, 3, 2, 10, 0, tzinfo=UTC)))
    sim = context(db, make_account(db), fake_provider, Clock(datetime(2026, 3, 2, 10, 0, tzinfo=UTC)))
    resting = [buy(ctx, "AAPL", "1", type=OrderType.LIMIT, limit_price=D("200")) for ctx in (live, sim)]
    fake_provider.set_price("AAPL", D("200"))

    class Keep:
        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(main, "SessionLocal", Keep)
    monkeypatch.setattr(main, "get_provider", lambda: fake_provider)
    main._fill_once()
    assert [o.status for o in resting] == [OrderStatus.FILLED, OrderStatus.OPEN]


def test_the_api_trades_through_whatever_context_the_dependency_hands_out(
    client, db: Session, fake_provider: FakeProvider
):
    sim = context(db, make_account(db, cash="12345"), fake_provider, Clock(datetime(2026, 1, 5, tzinfo=UTC)))
    assert D(client.get("/api/portfolio").json()["cash"]) == D("100000")
    app.dependency_overrides[get_live_context] = lambda: sim
    try:
        body = client.get("/api/portfolio").json()
        assert D(body["cash"]) == D("12345")
        order = client.post(
            "/api/orders", json={"symbol": "AAPL", "side": "buy", "type": "market", "quantity": "1"}
        )
        assert order.status_code == 200
        assert order.json()["created_at"].startswith("2026-01-05")
    finally:
        app.dependency_overrides.pop(get_live_context, None)
    assert [o.account_id for o in db.scalars(select(Order))] == [sim.account.id]
