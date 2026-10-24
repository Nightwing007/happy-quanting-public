"""Marketplace subscriptions: funding a paper sub-account, the live runner, stopping, and the
profit share against a high-water mark. The creator is `other`, the subscriber is `tester`."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.algos import hq
from app.algos.library import LIBRARY
from app.algos.runner import _EngineBackend
from app.market_data.fake import FakeProvider
from app.marketplace import live, subscriptions
from app.models import (
    Account,
    AccountKind,
    AlgoListing,
    CashTransfer,
    FeeLedger,
    ListingVersion,
    Order,
    Subscription,
    Trade,
)
from app.trading import engine, hours
from app.trading.context import TradingContext

D = Decimal
SYMBOL = "AAPL"
NOW = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CALLS: list[str] = []


class AlwaysBuy(hq.Strategy):
    """Buys ten shares on the first bar it sees and counts every `on_bar` call."""

    name = "Always buy"
    description = "Test strategy."
    markets = ("international",)
    interval = "1d"
    warmup_bars = 0
    PARAMETERS = {}

    def on_bar(self, ctx):
        CALLS.append("on_bar")
        for symbol in ctx.symbols:
            if ctx.position(symbol).quantity == 0:
                ctx.buy(symbol, quantity=10)


@pytest.fixture(autouse=True)
def library_and_registry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(LIBRARY, "always_buy", AlwaysBuy)
    CALLS.clear()
    yield
    live.drop_all()  # no test leaves a sandbox child behind


class Clock:
    """A clock the test moves, so each loop pass sees a newer quote."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.at = NOW
        monkeypatch.setattr(clock, "now", lambda: self.at)

    def advance(self, minutes: int = 1) -> None:
        self.at += timedelta(minutes=minutes)


@pytest.fixture
def ticking(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return Clock(monkeypatch)


def user_id(client: TestClient) -> int:
    return client.get("/api/me").json()["id"]


def make_listing(
    db: Session, owner_id: int, *, status="published", fee="20", markets=None, key="always_buy", source=None
) -> AlgoListing:
    now = clock.now()
    listing = AlgoListing(
        owner_user_id=owner_id, name="Test algo", tagline="", description="",
        markets=markets or ["international"],
        test_symbols=[SYMBOL], interval="1d", fee_percent=D(fee), status=status,
        source=source, strategy_key=None if source else key, params=None if source else {},
        version=1, created_at=now, updated_at=now,
    )  # fmt: skip
    db.add(listing)
    db.flush()
    db.add(
        ListingVersion(
            listing_id=listing.id, version=1, source=listing.source, strategy_key=listing.strategy_key,
            params=listing.params, interval="1d", created_at=now,
        )
    )  # fmt: skip
    db.commit()
    return listing


def subscribe(client: TestClient, listing_id: int, capital="30000", symbols=(SYMBOL,)):
    return client.post(
        f"/api/marketplace/listings/{listing_id}/subscribe",
        json={"symbols": list(symbols), "capital": capital},
    )


def live_account(db: Session, uid: int) -> Account:
    return engine.account_for_user(db, uid)


@pytest.fixture
def world(client: TestClient, second_client: TestClient, db: Session):
    """(subscriber id, creator id, published listing)."""
    subscriber, creator = user_id(client), user_id(second_client)
    return subscriber, creator, make_listing(db, creator)


# --- subscribing ---------------------------------------------------------------------------------


def test_subscribe_moves_the_capital_to_its_own_algo_account(client: TestClient, db: Session, world):
    subscriber, _, listing = world
    r = subscribe(client, listing.id)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "active" and out["symbols"] == [SYMBOL] and out["fee_percent"] == "20"
    assert D(out["capital"]) == D(out["equity"]) == D(30000)
    assert out["high_water_mark"] == "0" and out["fees_paid"] == "0"

    sub = db.get(Subscription, out["id"])
    account = db.get(Account, sub.account_id)
    assert account.kind == AccountKind.ALGO and account.user_id == subscriber
    assert account.cash == account.starting_cash == D(30000)
    mine = live_account(db, subscriber)
    assert mine.id != account.id and mine.cash == D(70000)  # 100000 - 30000
    assert (account.broker_india, account.broker_international) == (
        mine.broker_india,
        mine.broker_international,
    )
    (transfer,) = db.scalars(select(CashTransfer)).all()
    assert (transfer.kind, transfer.amount) == ("fund", D(30000))


def test_subscribe_refusals(client: TestClient, second_client: TestClient, db: Session, world):
    subscriber, creator, listing = world
    # More than the available cash (100000 at the start).
    r = subscribe(client, listing.id, capital="100000.01")
    assert r.status_code == 400 and r.json()["code"] == "insufficient_cash"
    assert subscribe(client, listing.id, capital="0").json()["code"] == "invalid_capital"
    # Cash already allocated is no longer available.
    assert subscribe(client, listing.id, capital="60000").status_code == 200
    assert subscribe(client, listing.id, capital="40000.01").json()["code"] == "insufficient_cash"
    # Margin blocked by shorts is not available either.
    live_account(db, subscriber).margin_used = D(39000)
    db.commit()
    assert subscribe(client, listing.id, capital="1000.01").json()["code"] == "insufficient_cash"
    # Your own listing.
    r = subscribe(second_client, listing.id)
    assert r.status_code == 400 and r.json()["code"] == "own_listing"
    # A draft or retired listing of someone else's does not exist for you.
    for status in ("draft", "retired"):
        hidden = make_listing(db, creator, status=status)
        r = subscribe(client, hidden.id, capital="10")
        assert r.status_code == 404 and r.json()["code"] == "listing_not_found"
    # Symbols: outside the listing's markets, unknown, or none.
    r = subscribe(client, listing.id, capital="10", symbols=["RELIANCE.NS"])
    assert r.status_code == 400 and r.json()["code"] == "symbol_market"
    assert (
        subscribe(client, listing.id, capital="10", symbols=["NOPE-XYZ"]).json()["code"] == "symbol_unknown"
    )
    assert subscribe(client, listing.id, capital="10", symbols=[]).status_code == 422
    # Only the 60,000 subscription exists and the cash is as it was.
    assert len(db.scalars(select(Subscription)).all()) == 1
    assert live_account(db, subscriber).cash == D(40000)


def test_a_segment_listing_accepts_its_markets_symbols(client: TestClient, db: Session, world):
    _, creator, _ = world
    india = make_listing(db, creator, markets=["india"])
    assert subscribe(client, india.id, symbols=["RELIANCE.NS"], capital="1000").status_code == 200
    assert subscribe(client, india.id, symbols=[SYMBOL], capital="1000").json()["code"] == "symbol_market"


# --- the profit share ----------------------------------------------------------------------------


def settle_at(db: Session, sub: Subscription, realized: str) -> FeeLedger | None:
    db.get(Account, sub.account_id).realized_pnl = D(realized)
    db.commit()
    return subscriptions.settle_fees(db, sub)


def test_fee_is_charged_only_on_realized_profit_above_the_high_water_mark(
    client: TestClient, db: Session, world
):
    subscriber, creator, listing = world
    sub = db.get(Subscription, subscribe(client, listing.id, capital="50000").json()["id"])
    account, creator_account = db.get(Account, sub.account_id), live_account(db, creator)
    assert (creator_account.cash, account.cash) == (D(100000), D(50000))

    # Profit 1,000: fee = (1000 - 0) x 20% = 200; the mark moves to 1,000.
    row = settle_at(db, sub, "1000")
    assert row.amount == D(200) and (row.hwm_before, row.hwm_after) == (D(0), D(1000))
    assert (row.profit_after, row.fee_percent, row.shortfall) == (D(1000), D(20), D(0))
    assert (creator_account.cash, account.cash) == (D(100200), D(49800))
    assert (sub.high_water_mark, sub.fees_paid) == (D(1000), D(200))

    # A loss to 500: nothing is owed and the mark stays at 1,000.
    assert settle_at(db, sub, "500") is None
    # Recovery to 800 is still under the mark: no fee, so the first 1,000 isn't charged twice.
    assert settle_at(db, sub, "800") is None
    assert (creator_account.cash, account.cash, sub.high_water_mark) == (D(100200), D(49800), D(1000))

    # A rise to 1,300: fee = (1300 - 1000) x 20% = 60; the mark moves to 1,300.
    row = settle_at(db, sub, "1300")
    assert row.amount == D(60) and (row.hwm_before, row.hwm_after) == (D(1000), D(1300))
    assert (creator_account.cash, account.cash) == (D(100260), D(49740))
    assert (sub.high_water_mark, sub.fees_paid) == (D(1300), D(260))
    # Settling again with nothing new owes nothing.
    assert settle_at(db, sub, "1300") is None
    rows = db.scalars(select(FeeLedger).order_by(FeeLedger.id)).all()
    assert [r.amount for r in rows] == [D(200), D(60)]
    assert all((r.creator_user_id, r.subscriber_user_id) == (creator, subscriber) for r in rows)


def test_a_later_listing_fee_change_does_not_change_what_the_subscriber_agreed_to(
    client: TestClient, db: Session, world
):
    _, _, listing = world
    sub = db.get(Subscription, subscribe(client, listing.id, capital="50000").json()["id"])
    listing.fee_percent = D(50)
    db.commit()
    assert settle_at(db, sub, "1000").amount == D(200)  # still 20%


def test_when_cash_is_short_the_creator_gets_what_is_available_and_the_shortfall_is_recorded(
    client: TestClient, db: Session, world
):
    _, creator, listing = world
    sub = db.get(Subscription, subscribe(client, listing.id, capital="1000").json()["id"])
    account = db.get(Account, sub.account_id)
    account.cash = D(50)  # the rest is tied up in positions
    # Profit 1,000: 200 owed, 50 payable.
    row = settle_at(db, sub, "1000")
    assert (row.amount, row.shortfall) == (D(50), D(150))
    assert (account.cash, live_account(db, creator).cash) == (D(0), D(100050))
    # The mark still moves to 1,000, so the shortfall is not charged again later.
    assert (sub.high_water_mark, sub.fees_paid) == (D(1000), D(50))
    assert settle_at(db, sub, "1000") is None


def test_unrealized_profit_is_not_charged(client: TestClient, db: Session, world, fake_provider, ticking):
    _, creator, listing = world
    sub_id = subscribe(client, listing.id).json()["id"]
    sub = db.get(Subscription, sub_id)
    for _ in range(3):
        live.run_subscriptions_once(db, fake_provider)
        ticking.advance()
    assert db.scalars(select(Trade).where(Trade.account_id == sub.account_id)).all()  # a trade is open
    fake_provider.set_price(SYMBOL, D(400))  # bought near 230: 10 shares gain about 1,700
    live.run_subscriptions_once(db, fake_provider)
    out = client.get("/api/marketplace/subscriptions").json()[0]
    assert D(out["unrealized_pnl"]) > 1000 and D(out["realized_pnl"]) == 0  # nothing has been sold
    assert (sub.fees_paid, sub.high_water_mark) == (D(0), D(0))
    assert live_account(db, creator).cash == D(100000)


# --- the live runner -----------------------------------------------------------------------------


def test_the_runner_trades_the_sub_account_and_not_the_live_account(
    client: TestClient, db: Session, world, fake_provider: FakeProvider, ticking: Clock
):
    subscriber, _, listing = world
    sub = db.get(Subscription, subscribe(client, listing.id).json()["id"])
    live.run_subscriptions_once(db, fake_provider)  # on_bar: the strategy decides to buy
    assert CALLS == ["on_bar"]
    ticking.advance()
    live.run_subscriptions_once(db, fake_provider)  # the order meets a newer quote and fills
    assert CALLS == ["on_bar"]  # no new closed bar, so no new decision
    orders = db.scalars(select(Order).where(Order.account_id == sub.account_id)).all()
    assert [(o.symbol, o.side, o.quantity, o.status) for o in orders] == [(SYMBOL, "buy", D(10), "filled")]
    mine = live_account(db, subscriber)
    assert db.scalars(select(Order).where(Order.account_id == mine.id)).all() == []
    assert db.scalars(select(Trade).where(Trade.account_id == mine.id)).all() == []
    assert mine.cash == D(70000)
    assert len(db.scalars(select(Trade).where(Trade.account_id == sub.account_id)).all()) == 1
    assert sub.listing_version == 1


def test_one_failing_subscription_does_not_stop_the_others(
    client: TestClient, second_client: TestClient, db: Session, world, fake_provider, ticking, monkeypatch
):
    _, _, listing = world
    first = subscribe(client, listing.id, capital="1000").json()["id"]
    second = subscribe(client, listing.id, capital="2000").json()["id"]
    real = live._step_active

    def flaky(db_, provider, sub):
        if sub.id == first:
            raise RuntimeError("boom")
        real(db_, provider, sub)

    monkeypatch.setattr(live, "_step_active", flaky)
    live.run_subscriptions_once(db, fake_provider)
    assert second in live._runs and first not in live._runs
    assert CALLS == ["on_bar"]


def test_a_closed_bar_guard_hides_the_bar_still_forming(db: Session, fake_provider: FakeProvider):
    """The fake's last daily bar is 2025-01-01. At noon UTC that day the New York session is on, so
    the day's bar is still being drawn; the day after, it is closed."""
    account = engine.account_for_user(db, 1)
    moment = {"at": datetime(2025, 1, 1, 17, tzinfo=UTC)}
    ctx = TradingContext(db, account, fake_provider, lambda: moment["at"])
    strategy = AlwaysBuy()
    live_view = _EngineBackend(ctx, strategy, (SYMBOL,), closed_only=True)
    replay_view = _EngineBackend(ctx, strategy, (SYMBOL,))
    assert live_view.bars(SYMBOL, 3)[-1].time == "2024-12-31"
    assert len(live_view.bars(SYMBOL, 3)) == 3
    assert replay_view.bars(SYMBOL, 3)[-1].time == "2025-01-01"  # sims and backtests are unchanged
    moment["at"] = datetime(2025, 1, 2, 17, tzinfo=UTC)
    assert live_view.bars(SYMBOL, 3)[-1].time == "2025-01-01"


# --- stopping ------------------------------------------------------------------------------------


def force_market(monkeypatch: pytest.MonkeyPatch, is_open: bool) -> dict:
    state = {"open": is_open}

    def status(market, at=None):
        if state["open"]:
            return hours.MarketStatus("open", True, datetime(1970, 1, 1, tzinfo=UTC), None, None, "UTC")
        return hours.MarketStatus("closed", False, None, None, None, "UTC", "weekend")

    monkeypatch.setattr(hours, "market_status", status)
    return state


def test_stop_with_the_market_closed_waits_then_finishes_when_flat(
    client: TestClient, db: Session, world, fake_provider, ticking, monkeypatch
):
    subscriber, _, listing = world
    market = force_market(monkeypatch, True)
    sub_id = subscribe(client, listing.id).json()["id"]
    for _ in range(3):
        live.run_subscriptions_once(db, fake_provider)
        ticking.advance()
    sub = db.get(Subscription, sub_id)
    account = db.get(Account, sub.account_id)
    (trade,) = db.scalars(select(Trade).where(Trade.account_id == account.id)).all()
    assert trade.status == "open"

    market["open"] = False
    out = client.post(f"/api/marketplace/subscriptions/{sub_id}/stop").json()
    assert out["status"] == "stopping"
    assert sub_id not in live._runs  # the strategy no longer decides anything
    waiting = db.scalars(select(Order).where(Order.account_id == account.id, Order.status == "open")).all()
    assert len(waiting) == 1 and waiting[0].trade_id == trade.id and waiting[0].side == "sell"
    live.run_subscriptions_once(db, fake_provider)  # still closed: nothing changes
    assert db.get(Subscription, sub_id).status == "stopping" and live_account(db, subscriber).cash == D(70000)

    market["open"] = True
    ticking.advance()
    live.run_subscriptions_once(db, fake_provider)  # the exit fills, the account is flat, cash goes home
    db.refresh(sub)
    db.refresh(account)
    assert sub.status == "stopped" and sub.stopped_at is not None
    assert account.cash == 0 and account.margin_used == 0
    # Prices never moved, so the only loss is the round trip's charges (realized_pnl < 0, no fee).
    assert account.realized_pnl < 0 and sub.fees_paid == 0
    returned = D(30000) + account.realized_pnl
    assert live_account(db, subscriber).cash == D(70000) + returned
    kinds = [(t.kind, t.amount) for t in db.scalars(select(CashTransfer).order_by(CashTransfer.id))]
    assert kinds == [("fund", D(30000)), ("return", returned)]
    final = client.get("/api/marketplace/subscriptions").json()[0]
    assert final["status"] == "stopped" and D(final["equity"]) == returned
    assert D(final["unrealized_pnl"]) == 0 and D(final["realized_pnl"]) == account.realized_pnl


def test_stop_when_the_market_is_open_finishes_at_once_and_cancels_waiting_entries(
    client: TestClient, db: Session, world, fake_provider, ticking
):
    subscriber, _, listing = world
    sub_id = subscribe(client, listing.id).json()["id"]
    live.run_subscriptions_once(db, fake_provider)
    ticking.advance()
    live.run_subscriptions_once(db, fake_provider)
    out = client.post(f"/api/marketplace/subscriptions/{sub_id}/stop").json()
    assert out["status"] == "stopped"
    assert db.scalars(select(Trade).where(Trade.status == "open")).all() == []
    assert (
        client.post(f"/api/marketplace/subscriptions/{sub_id}/stop").json()["status"] == "stopped"
    )  # repeat
    assert live_account(db, subscriber).cash > D(99900)


def test_stopping_pays_the_creator_the_final_fee_before_cash_returns(client: TestClient, db: Session, world):
    subscriber, creator, listing = world
    sub = db.get(Subscription, subscribe(client, listing.id, capital="50000").json()["id"])
    db.get(Account, sub.account_id).realized_pnl = D(1000)  # an earlier profit nobody has settled yet
    db.commit()
    client.post(f"/api/marketplace/subscriptions/{sub.id}/stop")
    db.refresh(sub)
    assert sub.status == "stopped" and sub.fees_paid == D(200)
    assert live_account(db, creator).cash == D(100200)
    assert live_account(db, subscriber).cash == D(50000) + D(49800)


def test_stopping_closes_the_sandbox_child_of_uploaded_code(
    client: TestClient, db: Session, world, fake_provider, ticking
):
    _, creator, _ = world
    from pathlib import Path

    source = (Path(__file__).parents[1] / "app" / "algos" / "library" / "sma_crossover.py").read_text(
        encoding="utf-8"
    )
    listing = make_listing(db, creator, source=source)
    sub_id = subscribe(client, listing.id).json()["id"]
    live.run_subscriptions_once(db, fake_provider)
    sandbox = live._runs[sub_id].sandbox
    assert sandbox is not None and sandbox.process is not None and sandbox.process.is_alive()

    client.post(f"/api/marketplace/subscriptions/{sub_id}/stop")
    assert sub_id not in live._runs
    sandbox.process.join(5)
    assert not sandbox.process.is_alive()


# --- who sees what -------------------------------------------------------------------------------


def test_subscriptions_are_private_to_the_subscriber(
    client: TestClient, second_client: TestClient, db: Session, world
):
    _, _, listing = world
    sub_id = subscribe(client, listing.id).json()["id"]
    assert second_client.get("/api/marketplace/subscriptions").json() == []
    r = second_client.post(f"/api/marketplace/subscriptions/{sub_id}/stop")
    assert r.status_code == 404 and r.json()["code"] == "subscription_not_found"
    assert db.get(Subscription, sub_id).status == "active"


def test_earnings_show_counts_and_totals_but_never_who(
    client: TestClient, second_client: TestClient, db: Session, world
):
    _, creator, listing = world
    sub = db.get(Subscription, subscribe(client, listing.id, capital="50000").json()["id"])
    other = make_listing(db, creator, fee="10")
    settle_at(db, sub, "1000")  # 200
    out = second_client.get("/api/marketplace/earnings").json()
    assert D(out["total"]) == 200 and out["currency"] == "USD"
    by_id = {x["listing_id"]: x for x in out["listings"]}
    assert (by_id[listing.id]["subscribers"], D(by_id[listing.id]["fees_received"])) == (1, 200)
    assert (by_id[other.id]["subscribers"], D(by_id[other.id]["fees_received"])) == (0, 0)
    assert "tester" not in second_client.get("/api/marketplace/earnings").text  # the subscriber's name
    assert client.get("/api/marketplace/earnings").json()["listings"] == []  # the subscriber owns none


SOURCE_SENTINEL = "SENTINEL_SUB_5c1d0e7a"
PARAM_SENTINEL = "61.2718281"


def test_a_subscriber_cannot_get_the_code_or_settings_by_any_route(
    client: TestClient, second_client: TestClient, db: Session, world, fake_provider, ticking
):
    from pathlib import Path

    from app.main import app

    _, creator, _ = world
    code = (Path(__file__).parents[1] / "app" / "algos" / "library" / "sma_crossover.py").read_text(
        encoding="utf-8"
    )
    by_code = make_listing(db, creator, source=code + f"\n# {SOURCE_SENTINEL}\n")
    by_key = make_listing(db, creator)
    by_key.params = {"marker": PARAM_SENTINEL}
    db.commit()
    texts = []
    for listing in (by_code, by_key):
        r = subscribe(client, listing.id, capital="1000")
        texts.append(r.text)
        texts.append(client.post(f"/api/marketplace/subscriptions/{r.json()['id']}/upgrade").text)
        texts.append(client.post(f"/api/marketplace/subscriptions/{r.json()['id']}/stop").text)
    texts.append(client.get("/api/marketplace/subscriptions").text)
    texts.append(client.get("/api/marketplace/earnings").text)
    for listing in (by_code, by_key):
        texts.append(client.get(f"/api/marketplace/listings/{listing.id}").text)
    joined = "".join(texts)
    assert SOURCE_SENTINEL not in joined and PARAM_SENTINEL not in joined
    assert '"source"' not in joined and '"params"' not in joined and '"strategy_key"' not in joined
    # And the owner's view does hold them, so the check above can fail.
    mine = second_client.get("/api/marketplace/mine").text
    assert SOURCE_SENTINEL in mine and PARAM_SENTINEL in mine
    paths = [p for p in app.openapi()["paths"] if "subscri" in p or p.endswith("/earnings")]
    assert len(paths) == 5  # subscribe, list, stop, upgrade, earnings
