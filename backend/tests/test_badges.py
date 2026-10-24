"""Gym badges (step 31a): every badge is earned from real engine, sim, backtest and marketplace
calls on the fake provider, and the near misses the spec names do not earn it.

The tester's live account is made a rupee account with 10,00,000, so one set of round trips
(win +20% of a notional, lose 20% of a sized one) serves all four market groups: a loss of 20% on a
position worth 5x a limit's share of starting cash is a drawdown just past (or just under) that
limit. Prices are moved with `set_price`; every trade goes through the engine.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app import clock
from app.algos import jobs
from app.algos.library import LIBRARY
from app.badges import award, evaluate
from app.badges.catalog import BADGES, CHAMPION, ELITE_FOUR, REGIONS, region_badges
from app.market_data import fake
from app.market_data.fake import FakeProvider
from app.marketplace import live, performance
from app.marketplace.seed import SEED_CREATORS, seed_marketplace
from app.migrate import upgrade_database
from app.models import (
    Account,
    AccountKind,
    AlgoListing,
    ListingPerformance,
    ListingVersion,
    Order,
    SimStatus,
    Subscription,
    Trade,
    User,
    UserBadge,
)
from app.sim import runner
from app.trading import engine
from tests.test_listing_versions import SYMBOL as LV_SYMBOL
from tests.test_listing_versions import Tagged, edit, new_listing, subscribe
from tests.test_marketplace import SHORT_WINDOWS
from tests.test_migrations import _upgrade_to

D = Decimal
real_calendar = pytest.mark.real_calendar
START = datetime(2026, 3, 2, 5, 0, tzinfo=UTC)  # Monday 10:30 IST

EXTRA_SYMBOLS = [
    ("INFY.NS", "Infosys Limited", "NSE", "equity", "INR", "1500"),
    ("WIPRO.NS", "Wipro Limited", "NSE", "equity", "INR", "250"),
    ("NVDA", "NVIDIA Corporation", "NASDAQ", "equity", "USD", "120"),
    ("TSLA", "Tesla, Inc.", "NASDAQ", "equity", "USD", "250"),
    ("AMZN", "Amazon.com, Inc.", "NASDAQ", "equity", "USD", "190"),
    ("SOL-USD", "Solana USD", "CCC", "crypto", "USD", "150"),
]
INDIA5 = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "WIPRO.NS"]
US5 = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN"]
COINS = ["BTC-USD", "ETH-USD", "SOL-USD"]
COUNTRIES = ["SAP.DE", "VOD.L", "0700.HK"]  # Germany, UK, Hong Kong

# group -> (first-trade badge, protection badge, streak badge, a symbol, a small quantity)
GROUPS = {
    "india": ("boulder", "cascade", "soul", "RELIANCE.NS", "10"),
    "us": ("zephyr", "hive", "mineral", "AAPL", "2"),
    "crypto": ("stone", "knuckle", "feather", "BTC-USD", "0.01"),
    "global": ("coal", "forest", "mine", "SAP.DE", "5"),
}
# group -> (badge, symbol, win quantity, loss quantity that breaks the limit, one that stays under)
CAPSTONES = {
    "india": ("earth", "RELIANCE.NS", "100", "400", "380"),
    "us": ("rising", "AAPL", "10", "27", "24"),
    "crypto": ("rain", "BTC-USD", "0.02", "0.14", "0.13"),
    "global": ("beacon", "SAP.DE", "10", "29", "25"),
}


# --- the desk: one user's live account, driven through the engine -----------------------------


class Clock:
    def __init__(self) -> None:
        self.t = START

    def set(self, *args: int) -> None:
        self.t = datetime(*args, tzinfo=UTC)

    def add(self, **kw: float) -> None:
        self.t += timedelta(**kw)


class Desk:
    def __init__(self, db: Session, provider: FakeProvider, user_id: int, clk: Clock) -> None:
        self.db, self.fp, self.uid, self.clk = db, provider, user_id, clk

    def ctx(self):
        return engine.live_context(self.db, self.fp, self.uid)

    def order(self, side: str, symbol: str, qty: str) -> Order:
        return engine.place_order(self.ctx(), symbol=symbol, side=side, type="market", quantity=D(qty))

    def buy(self, symbol: str, qty: str) -> Order:
        return self.order("buy", symbol, qty)

    def sell(self, symbol: str, qty: str) -> Order:
        return self.order("sell", symbol, qty)

    def trades(self) -> list[Trade]:
        return list(self.db.scalars(select(Trade).order_by(Trade.id)))

    def last(self) -> Trade:
        return self.trades()[-1]

    def price(self, symbol: str) -> Decimal:
        return self.fp.get_quote(symbol).price

    def exit(self, trade: Trade) -> Order:
        return engine.exit_trade(self.ctx(), trade.id)

    def protect(self, trade: Trade, stop: Decimal | None = None, target: Decimal | None = None) -> None:
        engine.set_protection(self.ctx(), trade.id, stop, target)

    def trip(self, symbol: str, qty: str, move: str = "0.05", protect: bool = False) -> Trade:
        """Buy, move the price by `move`, exit (a closed-by-you trade), put the price back."""
        base = self.price(symbol)
        self.buy(symbol, qty)
        trade = self.last()
        if protect:
            self.protect(trade, stop=(base * D("0.9")).quantize(D("0.01")))
        self.fp.set_price(symbol, base * (1 + D(move)))
        self.clk.add(minutes=1)
        self.exit(trade)
        self.fp.set_price(symbol, base)
        self.clk.add(minutes=1)
        self.db.refresh(trade)
        return trade

    def earned(self) -> set[str]:
        return evaluate.evaluate_user(self.db, self.uid, self.clk.t)


@pytest.fixture(autouse=True)
def world(monkeypatch: pytest.MonkeyPatch) -> Clock:
    monkeypatch.setattr(fake, "_SEED", fake._SEED + EXTRA_SYMBOLS)
    clk = Clock()
    monkeypatch.setattr(clock, "now", lambda: clk.t)
    monkeypatch.setitem(LIBRARY, "tagged", Tagged)
    monkeypatch.setattr(performance, "WINDOWS", SHORT_WINDOWS)
    award.reset_sweep_state()
    yield clk
    live.drop_all()


@pytest.fixture
def desk(client: TestClient, db: Session, fake_provider: FakeProvider, world: Clock) -> Desk:
    uid = client.get("/api/me").json()["id"]
    account = engine.account_for_user(db, uid)
    account.currency = "INR"
    account.cash = account.starting_cash = D(1_000_000)
    db.commit()
    return Desk(db, fake_provider, uid, world)


def sim_day(desk: Desk, symbol: str, bars: int):
    session = runner.create_session(
        desk.db, desk.fp, symbols=[symbol], interval="1m", start_date=date(2026, 2, 26),
        end_date=date(2026, 2, 26), speed=60, owner_user_id=desk.uid,
    )  # fmt: skip
    runner.advance(desk.db, session, bars, desk.fp)
    return session


# --- catalog ------------------------------------------------------------------------------------


def test_the_catalog_is_complete_and_every_badge_has_a_condition():
    assert len(BADGES) == 37  # 4 regions x 8, the Elite Four, the Champion
    assert {r: len(region_badges(r)) for r in REGIONS} == {
        "kanto": 8, "johto": 8, "hoenn": 8, "sinnoh": 8, "elite": 4,
    }  # fmt: skip
    assert set(evaluate.CHECKS) == set(BADGES) - {CHAMPION}
    assert all(b.hint and b.name for b in BADGES.values())
    assert BADGES["thunder"].hint == "An intraday short closed by you before the broker's square-off"
    assert [REGIONS[r].group for r in REGIONS] == ["india", "us", "crypto", "global", None]


def test_the_catalog_route_lists_regions_with_hints(client: TestClient):
    body = client.get("/api/badges/catalog").json()
    assert [r["id"] for r in body["regions"]] == list(REGIONS)
    kanto = body["regions"][0]
    assert (kanto["name"], kanto["group"]) == ("Kanto", "india")
    assert [b["id"] for b in kanto["badges"]][:3] == ["boulder", "cascade", "thunder"]
    assert kanto["badges"][0]["hint"] == "First filled trade on NSE or BSE"
    assert body["regions"][4]["badges"][-1]["id"] == CHAMPION


# --- first trade, first protection, streak, distinct symbols -------------------------------------


@pytest.mark.parametrize("group", GROUPS)
def test_the_first_trade_in_a_group_earns_only_that_groups_badge(desk: Desk, group: str):
    badge, _, _, symbol, qty = GROUPS[group]
    assert desk.earned() == set()
    desk.buy(symbol, qty)
    assert desk.earned() == {badge}  # no other region's first-trade badge comes with it


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("how", ["stop", "target"])
def test_setting_a_stop_or_target_earns_the_groups_protection_badge(desk: Desk, group: str, how: str):
    _, badge, _, symbol, qty = GROUPS[group]
    desk.buy(symbol, qty)
    trade = desk.last()
    assert badge not in desk.earned()
    price = desk.price(symbol)
    if how == "stop":
        desk.protect(trade, stop=(price * D("0.9")).quantize(D("0.01")))
        assert desk.last().had_stop is True
    else:
        desk.protect(trade, target=(price * D("1.1")).quantize(D("0.01")))
        assert desk.last().had_stop is False  # only a stop is recorded for "protected"
    assert badge in desk.earned()


def test_clearing_a_stop_keeps_had_stop(desk: Desk):
    desk.buy("AAPL", "2")
    trade = desk.last()
    desk.protect(trade, stop=D("200"))
    desk.protect(trade, stop=None, target=None)
    assert (desk.last().stop_price, desk.last().had_stop) == (None, True)


@pytest.mark.parametrize("group", GROUPS)
def test_ten_protected_closed_trades_earn_the_streak_badge_and_nine_do_not(desk: Desk, group: str):
    _, _, badge, symbol, qty = GROUPS[group]
    for _ in range(9):
        desk.trip(symbol, qty, protect=True)
    assert badge not in desk.earned()  # 9 protected trades
    desk.trip(symbol, qty, protect=True)
    assert badge in desk.earned()


def test_an_unprotected_trade_in_the_ten_breaks_the_run(desk: Desk):
    for _ in range(5):
        desk.trip("RELIANCE.NS", "10", protect=True)
    desk.trip("RELIANCE.NS", "10", protect=False)
    for _ in range(5):
        desk.trip("RELIANCE.NS", "10", protect=True)
    assert "soul" not in desk.earned()  # 11 closed trades, but never 10 protected in a row
    for _ in range(5):
        desk.trip("RELIANCE.NS", "10", protect=True)
    assert "soul" in desk.earned()


def test_open_trades_do_not_count_toward_the_streak(desk: Desk):
    for _ in range(9):
        desk.trip("RELIANCE.NS", "10", protect=True)
    desk.buy("RELIANCE.NS", "10")
    desk.protect(desk.last(), stop=D("1000"))
    assert "soul" not in desk.earned()


@pytest.mark.parametrize(
    ("badge", "symbols", "qty", "needed"),
    [
        ("rainbow", INDIA5, "10", 5),
        ("storm", US5, "2", 5),
        ("balance", COINS, "0.01", 3),
        ("cobble", COUNTRIES, "5", 3),
    ],
)
def test_distinct_symbols_or_countries(desk: Desk, badge: str, symbols: list[str], qty: str, needed: int):
    for symbol in symbols[: needed - 1]:
        desk.buy(symbol, qty)
        desk.buy(symbol, qty)  # trading one thing twice is still one thing
    assert badge not in desk.earned()
    desk.buy(symbols[needed - 1], qty)
    assert badge in desk.earned()


def test_cobble_counts_countries_not_exchanges(desk: Desk):
    desk.buy("SAP.DE", "5")  # Xetra, Germany
    desk.buy("VOD.L", "100")
    assert "cobble" not in desk.earned()


# --- the other trade-shape badges ----------------------------------------------------------------


def test_thunder_an_intraday_short_closed_by_you(desk: Desk):
    desk.sell("RELIANCE.NS", "10")
    short = desk.last()
    assert (short.direction, short.product) == ("short", "intraday")
    assert "thunder" not in desk.earned()  # still open
    desk.clk.add(minutes=30)
    desk.buy("RELIANCE.NS", "10")  # buying back what you are short is the cover
    assert desk.last().closed_how == "cover"
    assert "thunder" in desk.earned()


@real_calendar
def test_thunder_is_not_earned_when_the_broker_squares_you_off(desk: Desk):
    desk.sell("RELIANCE.NS", "10")
    desk.clk.set(2026, 3, 2, 9, 50)  # 15:20 IST, ten minutes before the close
    [order] = engine.square_off_due(desk.ctx())
    assert order.origin == "square_off" and desk.last().closed_how == "square_off"
    assert "thunder" not in desk.earned()
    assert "boulder" in desk.earned()


def test_marsh_and_relic_need_thirty_days(desk: Desk):
    desk.buy("RELIANCE.NS", "10")
    desk.buy("SAP.DE", "5")
    desk.clk.add(days=29, hours=23)
    assert desk.earned() == {"boulder", "coal"}  # open for 29 days 23 hours
    desk.clk.add(hours=1)
    assert desk.earned() == {"boulder", "coal", "marsh", "relic"}  # open trades count while held


def test_a_trade_closed_before_thirty_days_never_earns_the_hold(desk: Desk):
    desk.buy("RELIANCE.NS", "10")
    trade = desk.last()
    desk.clk.add(days=29)
    desk.exit(trade)
    desk.clk.add(days=60)  # time passing after the close changes nothing
    assert "marsh" not in desk.earned()


def test_marsh_needs_a_delivery_trade(desk: Desk):
    # An Indian short is intraday: it can't be held, but even if a row said so it isn't delivery.
    desk.sell("RELIANCE.NS", "10")
    trade = desk.last()
    trade.opened_at = desk.clk.t - timedelta(days=40)
    desk.db.commit()
    assert "marsh" not in desk.earned()


def test_plain_is_a_fractional_us_buy(desk: Desk):
    desk.buy("AAPL", "2")
    desk.buy("ETH-USD", "0.5")  # a fractional coin is not a fractional share
    assert "plain" not in desk.earned()
    desk.buy("AAPL", "0.5")
    assert "plain" in desk.earned()


def test_fog_a_us_short_held_overnight_and_closed_by_you(desk: Desk):
    desk.sell("AAPL", "5")
    short = desk.last()
    assert (short.direction, short.product) == ("short", "margin")
    desk.clk.add(days=2)
    assert engine.accrue_financing(desk.ctx()) == 1
    assert desk.last().financing_paid > 0
    assert "fog" not in desk.earned()  # borrow paid, but not closed yet
    desk.buy("AAPL", "5")
    assert "fog" in desk.earned()


def test_fog_is_not_earned_by_a_same_day_cover(desk: Desk):
    desk.sell("AAPL", "5")
    desk.clk.add(hours=3)
    assert engine.accrue_financing(desk.ctx()) == 0
    desk.buy("AAPL", "5")
    assert desk.last().financing_paid == 0
    assert "fog" not in desk.earned()


def test_heat_a_crypto_short_closed_by_you_after_funding(desk: Desk):
    desk.sell("BTC-USD", "0.01")
    desk.clk.add(days=2)
    assert engine.accrue_financing(desk.ctx()) == 1
    assert "heat" not in desk.earned()
    desk.exit(desk.last())
    assert desk.last().closed_how == "exit" and desk.last().financing_paid > 0
    assert "heat" in desk.earned()


def test_heat_needs_funding_to_have_been_paid(desk: Desk):
    desk.sell("BTC-USD", "0.01")
    desk.exit(desk.last())
    assert "heat" not in desk.earned()


@real_calendar
def test_dynamo_a_crypto_order_while_nse_nyse_and_lse_are_all_closed(desk: Desk):
    desk.clk.set(2026, 3, 7, 12, 0)  # Saturday noon UTC: all three are shut for the weekend
    desk.buy("BTC-USD", "0.01")
    assert "dynamo" in desk.earned()


@real_calendar
@pytest.mark.parametrize(
    ("when", "symbol", "qty"),
    [
        ((2026, 3, 2, 14, 30), "BTC-USD", "0.01"),  # Monday: New York has just opened
        ((2026, 3, 2, 11, 0), "BTC-USD", "0.01"),  # Monday: Mumbai shut, London still trading
        ((2026, 3, 7, 12, 0), "AAPL", "2"),  # all shut, but not a crypto order
    ],
)
def test_dynamo_near_misses(desk: Desk, when: tuple, symbol: str, qty: str):
    desk.clk.set(*when)
    desk.buy(symbol, qty)
    assert "dynamo" not in desk.earned()


@real_calendar
def test_icicle_a_hong_kong_lunch_break_order_that_waited_for_the_reopen(desk: Desk):
    desk.clk.set(2026, 3, 2, 4, 30)  # 12:30 HKT
    order = desk.buy("0700.HK", "10")
    assert order.status == "open"
    assert "icicle" not in desk.earned()  # still waiting
    desk.clk.set(2026, 3, 2, 5, 0)  # 13:00 HKT, the reopen
    assert engine.fill_open_orders(desk.ctx()) == 1
    assert "icicle" in desk.earned()


@real_calendar
def test_icicle_near_misses(desk: Desk):
    desk.clk.set(2026, 3, 2, 2, 0)  # 10:00 HKT: open, fills at once
    assert desk.buy("0700.HK", "10").status == "filled"
    assert "icicle" not in desk.earned()
    desk.clk.set(2026, 3, 2, 4, 30)  # lunch break, but a different exchange's stock
    desk.buy("SAP.DE", "5")  # Xetra is shut at this hour: it waits, nothing to do with Hong Kong
    assert "icicle" not in desk.earned()


def test_fen_a_trade_that_paid_a_transaction_tax(desk: Desk):
    order = desk.buy("VOD.L", "100")
    assert any(c["category"] == "tax" for c in order.charges)  # UK stamp duty reserve tax
    assert "fen" in desk.earned()


def test_fen_near_misses(desk: Desk):
    order = desk.buy("SAP.DE", "5")  # Germany: no transaction tax is modelled
    assert not any(c["category"] == "tax" for c in order.charges)
    order = desk.buy("RELIANCE.NS", "10")  # India's STT is a tax, but not a global one
    assert any(c["category"] == "tax" for c in order.charges)
    assert "fen" not in desk.earned()


# --- capstones -----------------------------------------------------------------------------------


def wins(desk: Desk, symbol: str, qty: str, count: int) -> None:
    for _ in range(count):
        desk.trip(symbol, qty, move="0.2")


def closed(desk: Desk) -> list[Trade]:
    rows = [t for t in desk.trades() if t.closed_at]
    return sorted(rows, key=lambda t: (t.closed_at, t.id))


def loss(desk: Desk, symbol: str, qty: str) -> Trade:
    return desk.trip(symbol, qty, move="-0.2")


@pytest.mark.parametrize("group", CAPSTONES)
def test_a_capstone_needs_twenty_trades_net_profit_and_a_drawdown_under_the_limit(desk: Desk, group: str):
    badge, symbol, win_qty, _, under_qty = CAPSTONES[group]
    wins(desk, symbol, win_qty, 19)
    assert badge not in desk.earned()  # 19 closed trades
    loss(desk, symbol, under_qty)
    limit = D(15) if group == "crypto" else D(10)
    drawdown = evaluate.max_drawdown_pct(closed(desk), D(1_000_000))
    assert limit - 2 < drawdown < limit  # just under
    assert badge in desk.earned()


@pytest.mark.parametrize("group", CAPSTONES)
def test_a_drawdown_just_over_the_limit_withholds_the_capstone(desk: Desk, group: str):
    badge, symbol, win_qty, over_qty, _ = CAPSTONES[group]
    wins(desk, symbol, win_qty, 19)
    loss(desk, symbol, over_qty)
    limit = D(15) if group == "crypto" else D(10)
    drawdown = evaluate.max_drawdown_pct(closed(desk), D(1_000_000))
    assert limit < drawdown < limit + 2
    assert sum(t.realized_pnl for t in closed(desk)) > 0  # profitable, so only the drawdown fails
    assert badge not in desk.earned()


def test_a_capstone_needs_a_net_profit(desk: Desk):
    for _ in range(20):
        desk.trip("RELIANCE.NS", "10", move="0")  # round trips at one price lose the charges
    assert sum(t.realized_pnl for t in closed(desk)) < 0
    assert "earth" not in desk.earned()


def test_a_capstone_counts_one_group_only(desk: Desk):
    wins(desk, "RELIANCE.NS", "100", 10)
    wins(desk, "TCS.NS", "10", 9)  # also Indian: 19 in all
    wins(desk, "AAPL", "10", 5)  # another group's trades don't fill the count
    assert "earth" not in desk.earned()
    wins(desk, "TCS.NS", "10", 1)
    assert "earth" in desk.earned()


def test_trades_outside_a_live_account_never_count(desk: Desk):
    wins(desk, "RELIANCE.NS", "100", 20)
    assert {"boulder", "earth"} <= desk.earned()
    account = engine.account_for_user(desk.db, desk.uid)
    account.kind = AccountKind.ALGO  # the same trades, made by a subscription's algorithm
    desk.db.commit()
    assert desk.earned() == set()


@real_calendar
def test_a_sim_trade_earns_nothing(desk: Desk):
    session = sim_day(desk, "RELIANCE.NS", 5)
    engine.place_order(
        runner.build_context(desk.db, session, desk.fp), symbol="RELIANCE.NS", side="buy",
        type="market", quantity=D(1),
    )  # fmt: skip
    assert desk.db.scalars(select(Trade)).all()  # the sim account holds a trade
    assert desk.earned() == set()


# --- sims -----------------------------------------------------------------------------------------


@real_calendar
@pytest.mark.parametrize(("badge", "symbol"), [("volcano", "RELIANCE.NS"), ("glacier", "AAPL")])
def test_replaying_a_full_day_through_to_the_close(desk: Desk, badge: str, symbol: str):
    session = sim_day(desk, symbol, 10_000)
    assert session.status == SimStatus.FINISHED
    assert desk.earned() == {badge}


@real_calendar
@pytest.mark.parametrize("symbol", ["RELIANCE.NS", "AAPL"])
def test_a_sim_stopped_before_the_close_earns_nothing(desk: Desk, symbol: str):
    session = sim_day(desk, symbol, 100)
    assert session.status != SimStatus.FINISHED
    assert desk.earned() == set()


@real_calendar
def test_someone_elses_finished_sim_does_not_count(desk: Desk, second_client: TestClient):
    other = second_client.get("/api/me").json()["id"]
    runner.create_session(
        desk.db, desk.fp, symbols=["RELIANCE.NS"], interval="1m", start_date=date(2026, 2, 26),
        end_date=date(2026, 2, 26), speed=60, owner_user_id=other,
    )  # fmt: skip
    session = desk.db.scalars(select(runner.SimSession)).one()
    runner.advance(desk.db, session, 10_000, desk.fp)
    assert evaluate.evaluate_user(desk.db, other, desk.clk.t) == {"volcano"}
    assert desk.earned() == set()


# --- backtests ------------------------------------------------------------------------------------


def backtest(client: TestClient, db: Session, provider: FakeProvider, symbol: str) -> dict:
    body = {
        "strategy": "sma_crossover",
        "params": {"fast_period": 3, "slow_period": 6, "percent_of_cash": "50"},
        "symbols": [symbol], "interval": "1d", "start_date": "2026-01-05", "end_date": "2026-02-27",
    }  # fmt: skip
    created = client.post("/api/backtests", json=body)
    assert created.status_code == 200, created.text
    jobs.run_backtest_job(db, created.json()["id"], provider, today=date(2026, 3, 2))
    detail = client.get(f"/api/backtests/{created.json()['id']}").json()
    assert detail["status"] == "done", detail
    return detail["results"]


def test_mind_a_crypto_backtest_that_beat_buy_and_hold(client: TestClient, desk: Desk):
    # The fake ETH falls over these weeks: the strategy loses less than holding does.
    results = backtest(client, desk.db, desk.fp, "ETH-USD")
    assert D(results["metrics"]["total_return_pct"]) > D(results["buy_and_hold"]["total_return_pct"])
    assert desk.earned() == {"mind"}


def test_mind_is_not_earned_by_a_backtest_that_lost_to_buy_and_hold(client: TestClient, desk: Desk):
    results = backtest(client, desk.db, desk.fp, "BTC-USD")  # the fake BTC rises
    assert D(results["metrics"]["total_return_pct"]) < D(results["buy_and_hold"]["total_return_pct"])
    assert desk.earned() == set()


# --- the Elite Four ---------------------------------------------------------------------------------


def results_json(pct: str) -> dict:
    """The stored shape of a measured window (PerformanceResultsOut), with one return in it."""
    return {
        "account_currency": "USD",
        "metrics": {
            "starting_cash": "100000", "final_equity": "100000", "total_return_pct": pct, "cagr_pct": None,
            "cagr_note": None, "max_drawdown_pct": "1.00", "sharpe": None, "sharpe_note": None,
            "win_rate_pct": None, "profit_factor": None, "trade_count": 0, "total_charges": "0",
            "exposure_pct": "0",
        },
        "equity_curve": [],
        "drawdown": [],
        "buy_and_hold": {
            "final_equity": "100000", "total_return_pct": "1.00", "cagr_pct": None,
            "max_drawdown_pct": "1.00", "total_charges": "0",
        },
    }  # fmt: skip


def finish_windows(db: Session, listing_id: int, returns: list[str], when: datetime) -> None:
    rows = db.scalars(
        select(ListingPerformance)
        .where(ListingPerformance.listing_id == listing_id)
        .order_by(ListingPerformance.id)
    ).all()
    for row, pct in zip(rows, returns, strict=False):
        row.status, row.computed_at = "done", when
        row.results = results_json(pct)
    db.commit()


def uid_of(client: TestClient) -> int:
    return client.get("/api/me").json()["id"]


def test_debut_needs_a_published_listing_with_a_measured_window(
    client: TestClient, db: Session, fake_provider: FakeProvider, world: Clock
):
    me = uid_of(client)
    draft = client.post(
        "/api/marketplace/listings",
        json=dict(
            name="Draft", markets=["international"], test_symbols=[LV_SYMBOL], fee_percent="10", tagline="t",
            description="d", source=None, user_algo_id=_saved_tagged(db, me, world),
        ),
    ).json()  # fmt: skip
    assert draft["status"] == "draft"
    assert evaluate.evaluate_user(db, me, world.t) == set()
    listing = new_listing(client, db)
    assert evaluate.evaluate_user(db, me, world.t) == set()  # published, nothing measured yet
    performance.compute_performance(db, fake_provider, db.get(AlgoListing, listing["id"]))  # a real run
    assert evaluate.evaluate_user(db, me, world.t) == {"debut"}


def _saved_tagged(db: Session, user_id: int, clk: Clock) -> int:
    from app.models import UserAlgo

    algo = UserAlgo(
        owner_user_id=user_id, name="s", strategy_key="tagged", params={"text": "alpha"}, created_at=clk.t
    )
    db.add(algo)
    db.commit()
    return algo.id


def test_consistent_needs_two_measured_windows_all_positive(client: TestClient, db: Session, world: Clock):
    me = uid_of(client)
    listing = new_listing(client, db)
    finish_windows(db, listing["id"], ["4.50"], world.t)
    assert evaluate.evaluate_user(db, me, world.t) == {"debut"}  # one window is not enough
    finish_windows(db, listing["id"], ["4.50", "-0.10"], world.t)
    assert evaluate.evaluate_user(db, me, world.t) == {"debut"}  # one window lost money
    finish_windows(db, listing["id"], ["4.50", "0.10", "7.00"], world.t)
    assert evaluate.evaluate_user(db, me, world.t) == {"debut", "consistent"}


def test_trusted_is_ten_subscriptions_from_other_people(
    client: TestClient, second_client: TestClient, db: Session, world: Clock
):
    me = uid_of(client)
    listing = new_listing(client, db)
    assert subscribe(client, listing["id"]).json()["code"] == "own_listing"
    for _ in range(9):
        assert subscribe(second_client, listing["id"]).status_code == 200
    assert "trusted" not in evaluate.evaluate_user(db, me, world.t)  # 9 from others
    assert subscribe(second_client, listing["id"]).status_code == 200
    assert "trusted" in evaluate.evaluate_user(db, me, world.t)


def test_craftsman_needs_a_subscriber_to_have_upgraded(
    client: TestClient, second_client: TestClient, db: Session, world: Clock
):
    me = uid_of(client)
    listing = new_listing(client, db)
    sub = subscribe(second_client, listing["id"]).json()
    world.add(hours=1)
    edit(client, listing["id"], params={"text": "beta"})  # version 2
    assert db.get(AlgoListing, listing["id"]).version == 2
    assert "craftsman" not in evaluate.evaluate_user(db, me, world.t)  # shipped, nobody moved
    world.add(hours=1)
    late = subscribe(second_client, listing["id"]).json()  # subscribed straight onto v2
    assert late["listing_version"] == 2
    assert "craftsman" not in evaluate.evaluate_user(db, me, world.t)  # not an upgrade
    assert second_client.post(f"/api/marketplace/subscriptions/{sub['id']}/upgrade").status_code == 200
    assert "craftsman" in evaluate.evaluate_user(db, me, world.t)


def test_champion_needs_a_full_region_and_all_four_elite():
    kanto = set(region_badges("kanto"))
    elite = set(ELITE_FOUR)
    assert evaluate.champion(kanto | elite)
    assert evaluate.champion(set(region_badges("hoenn")) | elite)  # any one region will do
    assert not evaluate.champion(kanto | (elite - {"debut"}))
    assert not evaluate.champion((kanto - {"marsh"}) | elite)
    assert not evaluate.champion(kanto)
    assert not evaluate.champion(elite)
    # eight badges spread over two regions are not a region
    assert not evaluate.champion(set(list(kanto)[:4]) | set(list(region_badges("johto"))[:4]) | elite)


def test_evaluate_user_adds_the_champion(monkeypatch: pytest.MonkeyPatch, db: Session, client: TestClient):
    uid = uid_of(client)
    everything = {b: (lambda f: True) for b in evaluate.CHECKS}
    monkeypatch.setattr(evaluate, "CHECKS", everything)
    assert evaluate.evaluate_user(db, uid, START) == set(BADGES)
    monkeypatch.setattr(evaluate, "CHECKS", {**everything, "craftsman": lambda f: False})
    assert CHAMPION not in evaluate.evaluate_user(db, uid, START)


# --- awarding, seen/unseen, backfill, sweep -------------------------------------------------------


def test_award_new_is_idempotent_and_never_revokes(desk: Desk):
    desk.buy("RELIANCE.NS", "10")
    assert award.award_new(desk.db, desk.uid, desk.clk.t) == ["boulder"]
    assert award.award_new(desk.db, desk.uid, desk.clk.t) == []
    row = desk.db.scalars(select(UserBadge)).one()
    assert (row.badge_id, row.seen, row.backfilled, row.earned_at) == ("boulder", False, False, desk.clk.t)
    account = engine.account_for_user(desk.db, desk.uid)
    account.kind = AccountKind.ALGO  # the data that earned it goes away
    desk.db.commit()
    assert desk.earned() == set()
    assert award.award_new(desk.db, desk.uid, desk.clk.t) == []
    assert award.earned_ids(desk.db, desk.uid) == {"boulder"}


def test_seen_and_unseen_through_the_api(client: TestClient, desk: Desk):
    assert client.get("/api/badges/me").json() == {"earned": [], "new": [], "backfill_summary": None}
    desk.buy("RELIANCE.NS", "10")
    desk.buy("AAPL", "2")
    mine = client.get("/api/badges/me").json()  # checked on read
    assert {b["id"] for b in mine["earned"]} == {"boulder", "zephyr"}
    assert sorted(mine["new"]) == ["boulder", "zephyr"]
    seen = client.post("/api/badges/me/seen", json={"ids": ["boulder"]}).json()
    assert seen["new"] == ["zephyr"]
    assert client.get("/api/badges/me").json()["new"] == ["zephyr"]  # a second read doesn't re-announce
    assert client.post("/api/badges/me/seen", json={"ids": ["zephyr", "nope"]}).json()["new"] == []


def test_backfill_awards_past_activity_silently_with_one_summary(client: TestClient, desk: Desk):
    desk.buy("RELIANCE.NS", "10")
    desk.buy("AAPL", "2")
    assert award.backfill_all(desk.db, desk.clk.t) == 2
    rows = desk.db.scalars(select(UserBadge)).all()
    assert all(r.seen and r.backfilled for r in rows)
    mine = client.get("/api/badges/me").json()
    assert (len(mine["earned"]), mine["new"], mine["backfill_summary"]) == (2, [], 2)
    assert client.get("/api/badges/me").json()["backfill_summary"] == 2  # stays until acknowledged
    assert client.post("/api/badges/me/summary-seen").json()["backfill_summary"] is None
    assert client.get("/api/badges/me").json()["backfill_summary"] is None
    assert award.backfill_all(desk.db, desk.clk.t) == 0  # holders of badges are left alone
    desk.buy("TCS.NS", "1")
    desk.buy("BTC-USD", "0.01")  # new activity after the backfill is a toast, not a summary
    assert client.get("/api/badges/me").json()["new"] == ["stone"]


def test_backfill_gives_the_seeded_creators_their_elite_four(
    client: TestClient, db: Session, fake_provider: FakeProvider, world: Clock
):
    subscriber = uid_of(client)
    seed_marketplace(db, fake_provider)
    creators = {u.username: u for u in db.scalars(select(User).where(User.is_creator.is_(True)))}
    assert len(creators) == len(SEED_CREATORS)
    long_ago = world.t - timedelta(days=30)
    for listing in db.scalars(select(AlgoListing)).all():
        finish_windows(db, listing.id, ["5.00", "3.00", "9.00"], world.t)
        # A second version shipped after the first ten subscribers joined; one of them moved up.
        for i in range(10):
            account = Account(
                currency="USD", cash=D(1000), starting_cash=D(1000), realized_pnl=D(0),
                created_at=long_ago, kind=AccountKind.ALGO, user_id=subscriber,
            )  # fmt: skip
            db.add(account)
            db.flush()
            db.add(
                Subscription(
                    subscriber_user_id=subscriber, listing_id=listing.id, listing_version=2 if i == 0 else 1,
                    symbols=[LV_SYMBOL], capital=D(1000), account_id=account.id, fee_percent=D(10),
                    created_at=long_ago,
                )
            )  # fmt: skip
        db.add(
            ListingVersion(listing_id=listing.id, version=2, interval=listing.interval, created_at=world.t)
        )
        listing.version = 2
    db.commit()

    assert award.backfill_all(db, world.t) >= 4 * len(creators)
    for user in creators.values():
        held = {r.badge_id: r for r in db.scalars(select(UserBadge).where(UserBadge.user_id == user.id))}
        assert set(ELITE_FOUR) <= set(held), user.username
        assert all(r.seen and r.backfilled for r in held.values())
        assert CHAMPION not in held  # no full region
    assert award.creator_badges(db, creators["zangoose"].id) == list(ELITE_FOUR)


def test_the_sweep_checks_only_users_with_recent_activity(
    desk: Desk, second_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    other = uid_of(second_client)
    desk.buy("RELIANCE.NS", "10")
    desk.clk.add(minutes=1)
    checked: list[int] = []
    real = award.evaluate_user
    monkeypatch.setattr(
        award, "evaluate_user", lambda db, uid, now: checked.append(uid) or real(db, uid, now)
    )

    assert award.sweep(desk.db, desk.clk.t) == {desk.uid: ["boulder"]}
    assert desk.uid in checked
    checked.clear()
    desk.clk.add(minutes=1)
    assert award.sweep(desk.db, desk.clk.t) == {}
    assert checked == []  # nobody did anything
    desk.clk.add(minutes=1)
    desk.buy("AAPL", "2")
    assert award.sweep(desk.db, desk.clk.t) == {desk.uid: ["zephyr"]}
    assert checked == [desk.uid] and other not in checked


def test_the_sweep_notices_a_hold_that_crosses_thirty_days_with_nobody_acting(desk: Desk):
    desk.buy("RELIANCE.NS", "10")
    award.sweep(desk.db, desk.clk.t)
    desk.clk.add(days=31)
    assert award.sweep(desk.db, desk.clk.t) == {desk.uid: ["marsh"]}


@real_calendar
def test_the_sweep_notices_a_sim_that_finishes_later(desk: Desk):
    session = sim_day(desk, "RELIANCE.NS", 10)
    session.status = SimStatus.RUNNING  # the driver is playing it
    desk.db.commit()
    desk.clk.add(minutes=1)
    assert award.sweep(desk.db, desk.clk.t) == {}
    runner.advance(desk.db, session, 10_000, desk.fp)
    desk.clk.add(minutes=1)
    assert award.sweep(desk.db, desk.clk.t) == {desk.uid: ["volcano"]}


# --- public lists and the marketplace card -----------------------------------------------------------


def test_a_users_public_badge_list(client: TestClient, second_client: TestClient, desk: Desk):
    desk.buy("RELIANCE.NS", "10")
    award.award_new(desk.db, desk.uid, desk.clk.t)
    body = second_client.get("/api/users/tester/badges").json()
    assert body["username"] == "tester" and [b["id"] for b in body["earned"]] == ["boulder"]
    assert second_client.get("/api/users/other/badges").json()["earned"] == []
    assert client.get("/api/users/nobody/badges").status_code == 404


def test_a_listing_card_shows_only_the_creators_elite_four_and_champion(
    client: TestClient, second_client: TestClient, desk: Desk
):
    listing = new_listing(client, desk.db)
    finish_windows(desk.db, listing["id"], ["4.00", "5.00"], desk.clk.t)
    desk.buy("RELIANCE.NS", "10")  # a trader badge too
    mine = client.get("/api/badges/me").json()
    assert {b["id"] for b in mine["earned"]} == {"boulder", "debut", "consistent"}
    card = second_client.get(f"/api/marketplace/listings/{listing['id']}").json()
    assert card["creator"]["badges"] == ["debut", "consistent"]
    [row] = second_client.get("/api/marketplace/listings").json()
    assert row["creator"]["badges"] == ["debut", "consistent"]


# --- the migration ------------------------------------------------------------------------------------


def test_0019_backfills_had_stop(tmp_path) -> None:
    engine_ = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    _upgrade_to(engine_, "0018")
    cols = (
        "(id, account_id, symbol, name, currency, market_code, direction, product, quantity, open_quantity, "
        "entry_price, entry_fx_rate, entry_value, entry_charges, cost_basis, margin_blocked, financing_paid, "
        "financing_accrued_until, exit_value, exit_charges, realized_pnl, status, opened_at, closed_how, "
        "stop_price, target_price)"
    )
    # (id, status, closed_how, stop, target): a stop still set, closed by stop, closed by target,
    # closed by hand with nothing left to show, and open with a target only (approximated as no).
    rows = [
        (1, "open", None, "90", None),
        (2, "closed", "stop_loss", None, None),
        (3, "closed", "target", None, None),
        (4, "closed", "exit", None, None),
        (5, "open", None, None, "120"),
    ]
    with engine_.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, currency, cash, starting_cash, realized_pnl, created_at, "
                "broker_india, broker_international, broker_crypto, margin_used, kind) VALUES "
                "(1, 'USD', '100000', '100000', '0', '2026-03-02 04:00:00', 'groww', 'ibkr', 'coindcx', "
                "'0', 'live')"
            )
        )
        for i, status, how, stop, target in rows:
            q = lambda v: "NULL" if v is None else f"'{v}'"  # noqa: E731
            conn.execute(
                text(
                    f"INSERT INTO trades {cols} VALUES ({i}, 1, 'AAPL', 'Apple', 'USD', 'US', 'long', "
                    "'delivery', '10', '10', '100', '1', '1000', '1', '1001', '0', '0', "
                    f"'2026-03-02 04:00:00', '0', '0', '0', '{status}', '2026-03-02 04:00:00', "
                    f"{q(how)}, {q(stop)}, {q(target)})"
                )
            )
    upgrade_database(engine_)
    with engine_.connect() as conn:
        got = dict(conn.execute(text("SELECT id, had_stop FROM trades")).all())
        users = conn.execute(text("SELECT COUNT(*) FROM user_badges")).scalar_one()
    assert got == {1: 1, 2: 1, 3: 1, 4: 0, 5: 0}
    assert users == 0
    engine_.dispose()


def test_user_badges_are_unique_per_user_and_badge(db: Session, client: TestClient):
    uid = uid_of(client)
    db.add(UserBadge(user_id=uid, badge_id="boulder", earned_at=START))
    db.commit()
    db.add(UserBadge(user_id=uid, badge_id="boulder", earned_at=START))
    with pytest.raises(Exception, match="UNIQUE"):
        db.commit()
    db.rollback()
    assert db.scalar(select(func.count()).select_from(UserBadge)) == 1
