# ruff: noqa: F811 - fixtures imported from other test modules are requested by name
"""Doing the same thing twice: a double exit, a double cancel, a repeated click on a route.

Fake prices: AAPL 230 USD (US: lots are named, `lot_exits="specific"`), RELIANCE.NS 1250 INR
(India: holdings are pooled, exits are FIFO), BTC-USD 60000. The account is USD with 100,000.
Costs are off (`zero_costs`) because these tests are about quantities and states, not charges.
Every expected figure is worked out beside the assertion.
"""

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.algos import jobs
from app.config import get_settings
from app.db import Base
from app.market_data.fake import FakeProvider
from app.marketplace import subscriptions
from app.models import (
    Account,
    AlgoListing,
    Backtest,
    BacktestStatus,
    CashTransfer,
    ListingPerformance,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    SimStatus,
    Subscription,
    Trade,
    TradeStatus,
)
from app.sim import runner
from app.trading import engine, hours
from app.trading.errors import (
    ExitAlreadyPending,
    OrderNotOpen,
    TradeNotOpen,
)
from app.trading.tick import run_tick
from tests.helpers import live
from tests.test_backtest import BODY as BACKTEST_BODY
from tests.test_listing_versions import new_listing, tagged  # noqa: F401 - autouse fixture
from tests.test_subscriptions import (  # noqa: F401 - fixtures
    library_and_registry,
    live_account,
    subscribe,
    world,
)

D = Decimal

pytestmark = pytest.mark.usefixtures("zero_costs")


class Hours:
    """Opens and closes every market under the test, whatever the calendar says."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.is_open = True
        self.next_close: datetime | None = None
        monkeypatch.setattr(hours, "market_status", self._status)

    def _status(self, market, at=None):
        if self.is_open:
            began = datetime(1970, 1, 1, tzinfo=UTC)
            return hours.MarketStatus("open", True, began, None, self.next_close, "UTC")
        return hours.MarketStatus("closed", False, None, None, None, "UTC", "weekend")


@pytest.fixture
def market(monkeypatch: pytest.MonkeyPatch) -> Hours:
    return Hours(monkeypatch)


def buy(db: Session, provider: FakeProvider, symbol: str, qty: str, **kw) -> Order:
    return engine.place_order(
        live(db, provider), symbol=symbol, side=OrderSide.BUY, type=kw.pop("type", OrderType.MARKET),
        quantity=D(qty), **kw,
    )  # fmt: skip


def sell(db: Session, provider: FakeProvider, symbol: str, qty: str, **kw) -> Order:
    return engine.place_order(
        live(db, provider), symbol=symbol, side=OrderSide.SELL, type=kw.pop("type", OrderType.MARKET),
        quantity=D(qty), **kw,
    )  # fmt: skip


def exit_(db: Session, provider: FakeProvider, trade: Trade, qty: str | None = None) -> Order:
    return engine.exit_trade(live(db, provider), trade.id, D(qty) if qty else None)


def trades(db: Session, symbol: str) -> list[Trade]:
    return list(db.scalars(select(Trade).where(Trade.symbol == symbol).order_by(Trade.id)))


def open_orders(db: Session) -> list[Order]:
    return list(db.scalars(select(Order).where(Order.status == OrderStatus.OPEN).order_by(Order.id)))


@pytest.fixture
def aapl(db: Session, fake_provider: FakeProvider, fixed_clock) -> Trade:
    """10 AAPL bought at 230: 2,300 spent, cash 97,700."""
    buy(db, fake_provider, "AAPL", "10")
    [trade] = trades(db, "AAPL")
    return trade


# --- exit twice --------------------------------------------------------------------------


def test_a_waiting_exit_blocks_a_second_full_exit(
    db: Session, fake_provider: FakeProvider, aapl: Trade, market: Hours
):
    market.is_open = False
    first = exit_(db, fake_provider, aapl)  # all 10, waits for the open
    assert first.status == OrderStatus.OPEN
    assert aapl.open_quantity == D("10")  # still open: nothing has filled

    # 10 held - 10 already being exited = 0 left, so another exit of 10 (or of 1) is refused.
    for qty in (None, "10", "1"):
        with pytest.raises(ExitAlreadyPending) as caught:
            exit_(db, fake_provider, aapl, qty)
    assert caught.value.code == "exit_already_pending"
    assert "10" in caught.value.message and "already" in caught.value.message
    assert len(open_orders(db)) == 1


def test_waiting_exits_that_fit_are_allowed_and_the_rest_refused(
    db: Session, fake_provider: FakeProvider, aapl: Trade, market: Hours
):
    market.is_open = False
    exit_(db, fake_provider, aapl, "4")
    exit_(db, fake_provider, aapl, "6")  # 4 + 6 = 10: exactly everything, fine
    with pytest.raises(ExitAlreadyPending):
        exit_(db, fake_provider, aapl, "1")  # 10 held - 10 promised = 0 free

    market.is_open = True
    assert engine.fill_open_orders(live(db, fake_provider)) == 2
    # Both fill in order: 10 - 4 - 6 = 0, closed, never short.
    assert aapl.status == TradeStatus.CLOSED
    assert aapl.open_quantity == D("0")
    assert trades(db, "AAPL") == [aapl]  # no short trade was opened by an over-sell


def test_refusal_says_how_much_is_already_being_exited(
    db: Session, fake_provider: FakeProvider, aapl: Trade, market: Hours
):
    market.is_open = False
    exit_(db, fake_provider, aapl, "7")
    # 10 held - 7 promised = 3 free; asking for 5 names both figures.
    with pytest.raises(ExitAlreadyPending) as caught:
        exit_(db, fake_provider, aapl, "5")
    assert "7" in caught.value.message and "3" in caught.value.message
    exit_(db, fake_provider, aapl, "3")  # exactly the rest is fine


def test_a_waiting_limit_sell_counts_against_an_exit(
    db: Session, fake_provider: FakeProvider, aapl: Trade
):
    # A limit sell at 300 rests (price is 230): its 8 shares are promised.
    resting = sell(db, fake_provider, "AAPL", "8", type=OrderType.LIMIT, limit_price=D("300"))
    assert resting.status == OrderStatus.OPEN
    # 10 held - 8 promised = 2 free, so an exit of 5 is refused and of 2 is accepted.
    with pytest.raises(ExitAlreadyPending):
        exit_(db, fake_provider, aapl, "5")
    exit_(db, fake_provider, aapl, "2")
    assert aapl.status == TradeStatus.OPEN and aapl.open_quantity == D("8")  # 2 filled at once


def test_pooled_market_waiting_exit_blocks_a_second_one(
    db: Session, fake_provider: FakeProvider, fixed_clock, market: Hours
):
    # India pools holdings: two trades of 5, exits are FIFO over the pool of 10.
    acct = engine.get_account(db)
    acct.currency, acct.cash = "INR", D("1000000")
    db.commit()
    buy(db, fake_provider, "RELIANCE.NS", "5")
    buy(db, fake_provider, "RELIANCE.NS", "5")
    first, second = trades(db, "RELIANCE.NS")
    market.is_open = False
    exit_(db, fake_provider, first, "5")  # promises 5 of the pool of 10
    exit_(db, fake_provider, second, "5")  # the other 5
    with pytest.raises(ExitAlreadyPending):
        exit_(db, fake_provider, first, "1")  # pool 10 - 10 promised = 0


def test_the_api_answers_a_second_exit_with_a_code(
    client: TestClient, db: Session, fake_provider: FakeProvider, aapl: Trade, market: Hours
):
    market.is_open = False
    assert client.post(f"/api/trades/{aapl.id}/exit").status_code == 200
    again = client.post(f"/api/trades/{aapl.id}/exit")
    assert again.status_code == 400
    assert again.json()["code"] == "exit_already_pending"
    assert "10" in again.json()["detail"]


def test_a_cancelled_exit_frees_its_shares(
    db: Session, fake_provider: FakeProvider, aapl: Trade, market: Hours
):
    market.is_open = False
    first = exit_(db, fake_provider, aapl)
    engine.cancel_order(live(db, fake_provider), first.id)
    again = exit_(db, fake_provider, aapl)  # 10 held - 0 promised: allowed again
    assert again.status == OrderStatus.OPEN


# --- cancel twice, cancel a filled order -----------------------------------------------------


def test_cancel_twice_and_cancel_a_filled_order_are_refused_with_a_code(
    client: TestClient, db: Session, fake_provider: FakeProvider, fixed_clock
):
    filled = buy(db, fake_provider, "AAPL", "1")
    resting = buy(db, fake_provider, "AAPL", "1", type=OrderType.LIMIT, limit_price=D("100"))

    r = client.delete(f"/api/orders/{filled.id}")
    assert r.status_code == 400 and r.json()["code"] == "order_not_open"
    assert "filled" in r.json()["detail"]

    assert client.delete(f"/api/orders/{resting.id}").status_code == 200
    again = client.delete(f"/api/orders/{resting.id}")
    assert again.status_code == 400 and again.json()["code"] == "order_not_open"
    assert "cancelled" in again.json()["detail"]
    # Nothing was changed by the refusals: 1 AAPL bought at 230, cash 100,000 - 230.
    assert engine.get_account(db).cash == D("99770")


def test_a_cancelled_order_never_fills_later(db: Session, fake_provider: FakeProvider, fixed_clock):
    resting = buy(db, fake_provider, "AAPL", "1", type=OrderType.LIMIT, limit_price=D("200"))
    engine.cancel_order(live(db, fake_provider), resting.id)
    with pytest.raises(OrderNotOpen):
        engine.cancel_order(live(db, fake_provider), resting.id)
    fake_provider.set_price("AAPL", D("150"))
    assert engine.fill_open_orders(live(db, fake_provider)) == 0
    assert resting.status == OrderStatus.CANCELLED


# --- exit after the trade was already closed -------------------------------------------------


def test_exit_after_a_stop_fired_is_refused_and_pays_nothing(
    client: TestClient, db: Session, fake_provider: FakeProvider, aapl: Trade
):
    ctx = live(db, fake_provider)
    engine.set_protection(ctx, aapl.id, D("200"), None)
    fake_provider.set_price("AAPL", D("190"))
    assert engine.trigger_protected_trades(ctx) == 1
    # Sold 10 at 190: 2,300 spent, 1,900 back, cash 100,000 - 2,300 + 1,900 = 99,600.
    assert aapl.status == TradeStatus.CLOSED and aapl.closed_how == "stop_loss"
    assert engine.get_account(db).cash == D("99600")

    r = client.post(f"/api/trades/{aapl.id}/exit")
    assert r.status_code == 400 and r.json()["code"] == "trade_not_open"
    assert engine.get_account(db).cash == D("99600")
    assert len(trades(db, "AAPL")) == 1  # no short was opened by the second sell


def test_a_waiting_exit_is_rejected_when_a_stop_closes_the_trade_first(
    db: Session, fake_provider: FakeProvider, aapl: Trade, market: Hours
):
    ctx = live(db, fake_provider)
    market.is_open = False
    waiting = exit_(db, fake_provider, aapl)
    # Protection on a trade with a waiting exit is allowed: whichever fires first closes it, the
    # other finds it closed. The stop is set at 200, below 230.
    engine.set_protection(ctx, aapl.id, D("200"), None)

    market.is_open = True
    fake_provider.set_price("AAPL", D("190"))
    assert engine.trigger_protected_trades(ctx) == 1  # the stop wins here
    assert engine.fill_open_orders(ctx) == 0
    # Closed once, at 190: cash 100,000 - 2,300 + 1,900 = 99,600. The waiting exit is rejected.
    assert waiting.status == OrderStatus.REJECTED
    assert "already closed" in waiting.reject_reason
    assert engine.get_account(db).cash == D("99600")
    assert len(trades(db, "AAPL")) == 1


def test_in_a_normal_tick_the_waiting_exit_fills_first_and_clears_the_stop(
    db: Session, fake_provider: FakeProvider, aapl: Trade, market: Hours
):
    ctx = live(db, fake_provider)
    market.is_open = False
    exit_(db, fake_provider, aapl)
    engine.set_protection(ctx, aapl.id, D("200"), None)
    market.is_open = True
    fake_provider.set_price("AAPL", D("190"))
    run_tick(ctx)
    assert aapl.status == TradeStatus.CLOSED and aapl.closed_how == "exit"
    assert aapl.stop_price is None
    assert engine.get_account(db).cash == D("99600")  # 100,000 - 2,300 + 1,900, once


# --- square-off racing a user exit -----------------------------------------------------------


@pytest.fixture
def short_reliance(db: Session, fake_provider: FakeProvider, fixed_clock, market: Hours) -> Trade:
    """An intraday short of 10 RELIANCE.NS at 1250 (the market is open). Rupee account."""
    acct = engine.get_account(db)
    acct.currency, acct.cash = "INR", D("1000000")
    db.commit()
    sell(db, fake_provider, "RELIANCE.NS", "10")
    [trade] = trades(db, "RELIANCE.NS")
    assert trade.direction == "short" and trade.product == "intraday"
    return trade


def near_the_close(market: Hours, now: datetime) -> None:
    market.is_open = True
    market.next_close = now + timedelta(minutes=1)  # inside the 10-minute square-off window


def test_square_off_closes_the_trade_and_the_waiting_user_cover_is_rejected(
    db: Session, fake_provider: FakeProvider, short_reliance: Trade, market: Hours, fixed_clock
):
    ctx = live(db, fake_provider)
    market.is_open = False
    waiting = exit_(db, fake_provider, short_reliance)  # buy back 10, waits for the open
    assert waiting.status == OrderStatus.OPEN
    near_the_close(market, fixed_clock)

    assert len(engine.square_off_due(ctx)) == 1  # 10 bought back by the square-off
    assert engine.fill_open_orders(ctx) == 0  # then the user's cover finds the trade closed
    assert waiting.status == OrderStatus.REJECTED
    assert short_reliance.status == TradeStatus.CLOSED and short_reliance.closed_how == "square_off"
    # Bought back once: only the original short exists, no long was opened by a second buy.
    assert len(trades(db, "RELIANCE.NS")) == 1


def test_square_off_after_a_partial_user_cover_buys_back_only_the_rest(
    db: Session, fake_provider: FakeProvider, short_reliance: Trade, market: Hours, fixed_clock
):
    ctx = live(db, fake_provider)
    exit_(db, fake_provider, short_reliance, "4")  # open market: fills at once, 10 - 4 = 6 left
    assert short_reliance.open_quantity == D("6")
    near_the_close(market, fixed_clock)
    [order] = engine.square_off_due(ctx)
    assert order.quantity == D("6")  # 10 - 4 = 6, not another 10
    assert short_reliance.status == TradeStatus.CLOSED
    assert len(trades(db, "RELIANCE.NS")) == 1


def test_a_user_cover_after_square_off_is_trade_not_open(
    db: Session, fake_provider: FakeProvider, short_reliance: Trade, market: Hours, fixed_clock
):
    near_the_close(market, fixed_clock)
    engine.square_off_due(live(db, fake_provider))
    with pytest.raises(TradeNotOpen):
        exit_(db, fake_provider, short_reliance)


# --- the same request twice at once -----------------------------------------------------------


@pytest.mark.parametrize("market_is_open", [True, False])
def test_two_threads_exiting_one_trade_close_it_once(
    tmp_path, fake_provider: FakeProvider, fixed_clock, market: Hours, market_is_open: bool
):
    """Two requests, each with its own session on a real file database. Both plan before either
    writes (a barrier inside the planner forces that), which is exactly the read-then-write gap:
    without the per-account lock both would credit the sale."""
    file_engine = create_engine(
        f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False, "timeout": 20}
    )
    Base.metadata.create_all(file_engine)
    maker = sessionmaker(bind=file_engine, autoflush=False, expire_on_commit=False)
    with maker() as setup:
        buy(setup, fake_provider, "AAPL", "10")
        [trade_id] = [t.id for t in trades(setup, "AAPL")]
    market.is_open = market_is_open

    barrier = threading.Barrier(2)
    real_plan = engine._plan

    def meeting_plan(ctx, request, quote):
        plan = real_plan(ctx, request, quote)
        try:
            barrier.wait(timeout=0.7)  # the other thread arrives here only if nothing serialises them
        except threading.BrokenBarrierError:
            pass
        return plan

    outcomes: list[str] = []

    def request_exit() -> None:
        with maker() as session:
            try:
                order = engine.exit_trade(live(session, fake_provider), trade_id)
                outcomes.append(order.status)
            except Exception as exc:  # noqa: BLE001 - the test reads which refusal it was
                outcomes.append(getattr(exc, "code", type(exc).__name__))

    engine._plan = meeting_plan
    try:
        threads = [threading.Thread(target=request_exit) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    finally:
        engine._plan = real_plan

    with maker() as check:
        cash = engine.get_account(check).cash
        all_trades = trades(check, "AAPL")
        sells = list(check.scalars(select(Order).where(Order.side == OrderSide.SELL)))
        status = all_trades[0].status
    file_engine.dispose()

    assert len(all_trades) == 1  # never a short
    assert len(sells) == 1
    if market_is_open:
        # One sale: 100,000 - 2,300 + 2,300 = 100,000, not 102,300.
        assert sorted(outcomes) == ["filled", "trade_not_open"]
        assert cash == D("100000") and status == TradeStatus.CLOSED
    else:
        assert sorted(outcomes) == ["exit_already_pending", "open"]
        assert cash == D("97700") and status == TradeStatus.OPEN


# --- sims: delete, control and orders once a session has finished ----------------------------

SIM_SYMBOL = "RELIANCE.NS"
SIM_BODY = {"symbols": [SIM_SYMBOL], "start_date": "2026-02-26", "end_date": "2026-02-26", "speed": 10}


@pytest.fixture
def rupee_world(offline_market_data, monkeypatch: pytest.MonkeyPatch, fixed_clock: datetime) -> None:
    # Replays Thursday 2026-02-26, a real NSE day, from the fixed clock of Monday 2026-03-02.
    monkeypatch.setenv("BASE_CURRENCY", "INR")
    monkeypatch.setenv("STARTING_CASH", "1000000")
    get_settings.cache_clear()


def finished_sim(client: TestClient, db: Session, provider: FakeProvider) -> str:
    sim_id = client.post("/api/sim/sessions", json=SIM_BODY).json()["id"]
    session = runner.get_session(db, sim_id, engine.get_account(db).user_id)
    runner.advance(db, session, 10_000, provider)
    assert session.status == SimStatus.FINISHED
    return f"/api/sim/sessions/{sim_id}"


@pytest.mark.real_calendar
@pytest.mark.usefixtures("rupee_world")
def test_a_finished_sim_refuses_new_orders_exits_and_protection_but_not_reads_or_reset(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    sim_id = client.post("/api/sim/sessions", json=SIM_BODY).json()["id"]
    base = f"/api/sim/sessions/{sim_id}"
    order = {"symbol": SIM_SYMBOL, "side": "buy", "type": "market", "quantity": "1"}
    runner.advance(db, runner.get_session(db, sim_id, engine.get_account(db).user_id), 5, fake_provider)
    assert client.post(f"{base}/orders", json=order).status_code == 200  # still playing: fine
    [trade] = client.get(f"{base}/trades").json()

    session = runner.get_session(db, sim_id, engine.get_account(db).user_id)
    runner.advance(db, session, 10_000, fake_provider)
    assert session.status == SimStatus.FINISHED

    # Nothing can ever fill after the last bar, so these would wait forever.
    for r in (
        client.post(f"{base}/orders", json=order),
        client.post(f"{base}/trades/{trade['id']}/exit"),
        client.put(f"{base}/trades/{trade['id']}/protection", json={"stop_price": "1000"}),
    ):
        assert r.status_code == 409 and r.json()["code"] == "sim_finished", r.text
        assert "finished" in r.json()["detail"]
    assert len(client.get(f"{base}/orders").json()) == 1  # no second order appeared
    assert client.get(f"{base}/portfolio").status_code == 200

    # Control on a finished session: start and step say it has finished, pause is harmless.
    for action in ("start", "step"):
        r = client.post(f"{base}/control", json={"action": action})
        assert r.status_code == 409 and "finished" in r.json()["detail"]
    assert client.post(f"{base}/control", json={"action": "pause"}).json()["status"] == "finished"
    assert client.post(f"{base}/control", json={"action": "reset"}).json()["status"] == "ready"
    # Playable again: no longer refused as finished (at the first bar there is no price yet).
    assert client.post(f"{base}/orders", json=order).json().get("code") != "sim_finished"


@pytest.mark.real_calendar
@pytest.mark.usefixtures("rupee_world")
def test_deleting_a_running_sim_twice_and_advancing_it_afterwards_are_harmless(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    sim_id = client.post("/api/sim/sessions", json=SIM_BODY).json()["id"]
    base = f"/api/sim/sessions/{sim_id}"
    assert client.post(f"{base}/control", json={"action": "start"}).json()["status"] == "running"
    session = runner.get_session(db, sim_id, engine.get_account(db).user_id)
    account_id = session.account_id

    assert client.delete(base).status_code == 204
    assert client.delete(base).status_code == 404  # a second click
    assert db.get(Account, account_id) is None

    # The driver may still hold the row it read a moment before the delete: its turn does nothing.
    assert runner.advance(db, session, 5, fake_provider) == 0
    assert runner.advance_until(db, session, datetime(2030, 1, 1, tzinfo=UTC), fake_provider) == 0
    with pytest.raises(runner.SimNotFound):
        runner.set_status(db, session, SimStatus.PAUSED)
    runner.delete_session(db, session)  # and so is deleting what is already gone


# --- backtests: delete twice, delete while it starts ------------------------------------------


def test_backtest_delete_twice_and_when_the_worker_starts_it_in_the_gap(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
):
    first = client.post("/api/backtests", json=BACKTEST_BODY).json()["id"]
    assert client.delete(f"/api/backtests/{first}").status_code == 204
    assert client.delete(f"/api/backtests/{first}").status_code == 404

    second = client.post("/api/backtests", json=BACKTEST_BODY).json()["id"]
    real_get = jobs.get_backtest

    def worker_starts_it(session, backtest_id, owner_id):
        row = real_get(session, backtest_id, owner_id)  # the delete has seen "queued"...
        session.execute(  # ...then the worker marks it running, behind this object's back
            update(Backtest).where(Backtest.id == backtest_id).values(status=BacktestStatus.RUNNING),
            execution_options={"synchronize_session": False},
        )
        session.commit()
        return row

    monkeypatch.setattr(jobs, "get_backtest", worker_starts_it)
    busy = client.delete(f"/api/backtests/{second}")
    assert busy.status_code == 409 and "is running" in busy.json()["detail"]
    assert db.scalar(select(Backtest.id).where(Backtest.id == second)) == second  # still there


# --- the marketplace: publish, stop, subscribe twice -------------------------------------------


def test_publishing_twice_keeps_the_measured_performance(client: TestClient, db: Session):
    listing = new_listing(client, db)
    rows = list(db.scalars(select(ListingPerformance)))
    assert len(rows) == 3
    rows[0].status = "done"  # a window the worker already measured
    db.commit()

    again = client.post(f"/api/marketplace/listings/{listing['id']}/publish")
    assert again.status_code == 200 and again.json()["status"] == "published"
    after = list(db.scalars(select(ListingPerformance).order_by(ListingPerformance.id)))
    # Not re-queued: same three rows, and the measured one is still measured.
    assert [r.id for r in after] == [r.id for r in rows]
    assert after[0].status == "done"


def test_retiring_twice_changes_nothing_the_second_time(client: TestClient, db: Session):
    listing = new_listing(client, db)
    url = f"/api/marketplace/listings/{listing['id']}/retire"
    assert client.post(url).json()["status"] == "retired"
    stamp = db.get(AlgoListing, listing["id"]).updated_at
    db.expire_all()
    second = client.post(url)
    assert second.status_code == 200 and second.json()["status"] == "retired"
    assert db.get(AlgoListing, listing["id"]).updated_at == stamp


def test_subscribing_twice_makes_two_independent_funded_subscriptions(
    client: TestClient, db: Session, world
):
    """Intended: each subscription is its own sub-account (different symbols or capital). A
    repeated click funds a second one, visibly, and each stops on its own."""
    subscriber, _, listing = world
    one = subscribe(client, listing.id, capital="30000").json()
    two = subscribe(client, listing.id, capital="30000").json()
    assert one["id"] != two["id"]
    assert live_account(db, subscriber).cash == D(40000)  # 100,000 - 30,000 - 30,000
    assert db.get(Subscription, one["id"]).account_id != db.get(Subscription, two["id"]).account_id

    assert client.post(f"/api/marketplace/subscriptions/{one['id']}/stop").json()["status"] == "stopped"
    assert client.get("/api/marketplace/subscriptions").json()[0]["status"] == "active"  # two still runs
    assert live_account(db, subscriber).cash == D(70000)


def test_stopping_twice_returns_the_cash_once(client: TestClient, db: Session, world):
    subscriber, _, listing = world
    sub_id = subscribe(client, listing.id, capital="30000").json()["id"]
    url = f"/api/marketplace/subscriptions/{sub_id}/stop"
    assert client.post(url).json()["status"] == "stopped"
    assert client.post(url).json()["status"] == "stopped"  # a second click is a no-op
    # 100,000 - 30,000 + 30,000 back, once.
    assert live_account(db, subscriber).cash == D(100000)
    transfers = [t.kind for t in db.scalars(select(CashTransfer).order_by(CashTransfer.id))]
    assert transfers == ["fund", "return"]


def test_advance_stop_on_an_already_stopped_subscription_returns_nothing_again(
    client: TestClient, db: Session, world, fake_provider
):
    subscriber, _, listing = world
    sub = db.get(Subscription, subscribe(client, listing.id, capital="30000").json()["id"])
    assert subscriptions.advance_stop(db, fake_provider, sub) is True
    # A second caller (the background loop) that read the row as "stopping" before the first
    # finished still holds an old object; it must see the stop and add no second transfer.
    sub.status = "stopping"
    assert subscriptions.advance_stop(db, fake_provider, sub) is True
    assert live_account(db, subscriber).cash == D(100000)
    assert [t.kind for t in db.scalars(select(CashTransfer))] == ["fund", "return"]


# --- every mutation route, sent twice -----------------------------------------------------------


def test_other_mutation_routes_sent_twice(client: TestClient, db: Session, fake_provider: FakeProvider):
    # Watchlist: adding what is there is a no-op, removing what is gone is a 404 with a sentence.
    assert client.post("/api/watchlist", json={"symbol": "MSFT"}).status_code == 200
    before = len(client.get("/api/watchlist").json())
    assert client.post("/api/watchlist", json={"symbol": "MSFT"}).status_code == 200
    assert len(client.get("/api/watchlist").json()) == before
    assert client.delete("/api/watchlist", params={"symbol": "MSFT"}).status_code == 204
    gone = client.delete("/api/watchlist", params={"symbol": "MSFT"})
    assert gone.status_code == 404 and "not on your watchlist" in gone.json()["detail"]

    # Resetting the account twice leaves the same clean account.
    for _ in range(2):
        r = client.post("/api/portfolio/reset")
        assert r.status_code == 200 and D(r.json()["cash"]) == D("100000")

    # A saved algorithm: the second delete is a 404.
    algo = client.post("/api/algos/mine", json={"name": "A", "strategy": "rsi_reversion", "params": {}})
    url = f"/api/algos/mine/{algo.json()['id']}"
    assert client.delete(url).status_code == 204
    assert client.delete(url).status_code == 404

    # Settings are a set, not a toggle: the same body twice gives the same answer.
    body = {"broker_india": "groww"}
    first = client.put("/api/settings", json=body)
    assert first.status_code == 200 and client.put("/api/settings", json=body).json() == first.json()

    # Logging out twice: both fine (the second has no session left to end).
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/logout").status_code == 204
