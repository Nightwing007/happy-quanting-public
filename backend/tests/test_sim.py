"""The simulation: past days played through the real engine.

Every test replays the fake provider's deterministic 1-minute bars for Thursday 2026-02-26, a
real NSE working day (09:15 to 15:30 IST, i.e. 03:45 to 10:00 UTC). RELIANCE.NS that day, bar by
bar (a bar's time is its start; the cursor reaches its close at start + 1 minute):

    bar starting 09:19 IST   close 1191.871433   (the last bar finished at a 09:20 cursor)
    bar starting 09:59 IST   close 1192.957370   (the last bar finished at a 10:00 cursor)
    bar starting 11:53 IST   close 1193.534748   (the first close at or above 1193.50)
    bar starting 15:19 IST   close 1194.107151   (the last bar finished at a 15:20 cursor)

The account is in rupees with Rs 10,00,000, so no currency conversion muddies the charges.
Charges are Groww's schedule (see markets.py and brokers.py), each line rounded to paise on its
own, GST charged on the sum of brokerage, exchange fee, SEBI fee and the depository charge.
"""

import inspect
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import main
from app.config import get_settings
from app.market_data.base import DataUnavailable
from app.market_data.fake import FakeProvider
from app.models import (
    Account,
    AccountKind,
    BarCache,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    SimSession,
    SimStatus,
    Trade,
)
from app.sim import driver, runner
from app.trading import engine, tick

D = Decimal
IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 2, 26)
SYMBOL = "RELIANCE.NS"

pytestmark = pytest.mark.real_calendar


@pytest.fixture(autouse=True)
def rupee_world(offline_market_data, monkeypatch: pytest.MonkeyPatch, fixed_clock: datetime) -> None:
    # The fixed clock is Monday 2026-03-02, four days after the replayed day: inside the 29 days
    # of 1-minute history Yahoo serves.
    monkeypatch.setenv("BASE_CURRENCY", "INR")
    monkeypatch.setenv("STARTING_CASH", "1000000")
    get_settings.cache_clear()


def ist(hour: int, minute: int, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST).astimezone(UTC)


def make_sim(
    db: Session,
    provider: FakeProvider,
    symbols: tuple[str, ...] = (SYMBOL,),
    start: date = DAY,
    end: date = DAY,
    interval: str = "1m",
    speed: int = 60,
) -> SimSession:
    return runner.create_session(
        db, provider, symbols=list(symbols), interval=interval, start_date=start, end_date=end, speed=speed
    )


def play_to(db: Session, sim: SimSession, provider: FakeProvider, at: datetime) -> engine.TradingContext:
    runner.advance_until(db, sim, at, provider)
    assert sim.cursor == at
    return runner.build_context(db, sim, provider)


def market_order(ctx, side: str, quantity: str, symbol: str = SYMBOL) -> Order:
    return engine.place_order(ctx, symbol=symbol, side=side, type=OrderType.MARKET, quantity=D(quantity))


def trades_of(db: Session, sim: SimSession) -> list[Trade]:
    return list(db.scalars(select(Trade).where(Trade.account_id == sim.account_id).order_by(Trade.id)))


def orders_of(db: Session, sim: SimSession) -> list[Order]:
    return list(db.scalars(select(Order).where(Order.account_id == sim.account_id).order_by(Order.id)))


# --- the two features that were never tested end to end ---------------------------------


def test_a_target_fires_at_the_market_price_of_the_bar_that_crossed_it(
    db: Session, fake_provider: FakeProvider
):
    sim = make_sim(db, fake_provider)
    assert sim.cursor == ist(9, 15) and sim.status == SimStatus.READY  # nothing has finished yet

    # 09:20 IST: buy 100 at the close of the 09:19 bar, 1191.871433.
    ctx = play_to(db, sim, fake_provider, ist(9, 20))
    bought = market_order(ctx, OrderSide.BUY, "100")
    assert (bought.status, bought.fill_price, bought.filled_at) == (
        OrderStatus.FILLED, D("1191.871433"), ist(9, 20)
    )
    # Value 100 x 1191.871433 = 119,187.1433 -> 119,187.14. Charges, each to the paisa:
    #   brokerage    0.1% = 119.19, capped at 20.00                    20.00
    #   exchange     0.00307%  x 119,187.1433 = 3.659                    3.66
    #   STT          0.1%      x 119,187.1433 = 119.187                119.19
    #   stamp duty   0.015%    x 119,187.1433 = 17.878                  17.88
    #   SEBI         0.0001%   x 119,187.1433 = 0.119                    0.12
    #   GST          18% x (20.00 + 3.66 + 0.12) = 18% x 23.78 = 4.2804   4.28
    #   total                                                          165.13
    assert bought.charges_total == D("165.13")
    [trade] = trades_of(db, sim)
    # The target is above the price now (1191.87). The bar starting 10:49 reaches 1193.53 at its
    # high but closes lower, and that must not fire it: the price a trader could trade at is the
    # bar's close, so only a close at or above the target counts.
    engine.set_protection(ctx, trade.id, None, D("1193.50"))

    ctx = play_to(db, sim, fake_provider, ist(11, 53))  # the 11:52 bar has just finished
    assert trade.status == "open"

    # One more bar: the 11:53 bar closes at 1193.534748, the first close at or above 1193.50.
    runner.advance(db, sim, 1, fake_provider)
    assert sim.cursor == ist(11, 54)
    assert trade.status == "closed" and trade.closed_how == "target"
    assert trade.closed_at == ist(11, 54)

    sold = next(o for o in orders_of(db, sim) if o.origin == "target")
    assert sold.side == OrderSide.SELL and sold.status == OrderStatus.FILLED
    # The market price of the crossing bar, not the 1193.50 that was set.
    assert sold.fill_price == D("1193.534748") != D("1193.50")
    assert sold.filled_at == ist(11, 54)
    assert "Target" in (sold.note or "") and "market price" in (sold.note or "")
    # Value 100 x 1193.534748 = 119,353.4748 -> 119,353.47. Charges:
    #   brokerage 20.00 (cap); exchange 0.00307% = 3.664 -> 3.66; STT 0.1% = 119.353 -> 119.35
    #   SEBI 0.0001% = 0.119 -> 0.12; depository (DP) charge 20.00
    #   GST 18% x (20.00 + 3.66 + 0.12 + 20.00) = 18% x 43.78 = 7.8804 -> 7.88   (no stamp on a sell)
    #   total 20.00 + 3.66 + 119.35 + 0.12 + 20.00 + 7.88 = 171.01
    assert sold.charges_total == D("171.01")
    # 119,353.47 - 119,187.14 = 166.33 gross; less 165.13 and 171.01 of charges = -169.81.
    assert trade.realized_pnl == D("-169.81")

    payouts = engine.get_payouts(runner.build_context(db, sim, fake_provider))
    [row] = payouts.payouts
    assert (row.closed_how, row.entry_charges_total, row.exit_charges_total, row.realized_pnl) == (
        "target", D("165.13"), D("171.01"), D("-169.81")
    )
    # Cash: 1,000,000 - 119,187.14 - 165.13 + 119,353.47 - 171.01 = 999,830.19.
    assert sim.account_id and db.get(Account, sim.account_id).cash == D("999830.19")


def test_an_intraday_short_is_squared_off_at_1520_ist(db: Session, fake_provider: FakeProvider):
    sim = make_sim(db, fake_provider)

    # 10:00 IST: sell 100 short at the close of the 09:59 bar, 1192.957370.
    ctx = play_to(db, sim, fake_provider, ist(10, 0))
    opened = market_order(ctx, OrderSide.SELL, "100")
    assert opened.fill_price == D("1192.957370") and opened.filled_at == ist(10, 0)
    [trade] = trades_of(db, sim)
    assert (trade.direction, trade.product, trade.status) == ("short", "intraday", "open")
    # Value 119,295.737 -> 119,295.74. Intraday short entry: brokerage 20.00, exchange 3.66,
    # STT 0.025% = 29.82 (sell side only), SEBI 0.12, GST 18% x 23.78 = 4.28, no stamp, no DP.
    # total 20.00 + 3.66 + 29.82 + 0.12 + 4.28 = 57.88
    assert opened.charges_total == D("57.88")

    # 15:19: the cover is not due yet (square-off is 10 minutes before the 15:30 close).
    play_to(db, sim, fake_provider, ist(15, 19))
    assert trade.status == "open"

    # The next bar finishes at 15:20 IST, the square-off moment, at 1194.107151.
    runner.advance(db, sim, 1, fake_provider)
    assert sim.cursor == ist(15, 20)
    assert trade.status == "closed" and trade.closed_how == "square_off"
    assert trade.closed_at == ist(15, 20)

    cover = next(o for o in orders_of(db, sim) if o.origin == "square_off")
    assert cover.side == OrderSide.BUY and cover.fill_price == D("1194.107151")
    assert cover.note == "Squared off at 15:20 IST."
    # Value 119,410.7151 -> 119,410.72. Cover: brokerage 20.00, exchange 0.00307% = 3.666 -> 3.67,
    # stamp 0.003% = 3.58 (buy side only), SEBI 0.12, GST 18% x (20.00 + 3.67 + 0.12) = 4.2822 -> 4.28,
    # no STT on a buy. total 20.00 + 3.67 + 3.58 + 0.12 + 4.28 = 31.65
    assert cover.charges_total == D("31.65")
    # Sold at 119,295.74, bought back at 119,410.72: -114.98 gross; less 57.88 and 31.65 = -204.51.
    assert trade.realized_pnl == D("-204.51")

    [row] = engine.get_payouts(runner.build_context(db, sim, fake_provider)).payouts
    assert (row.closed_how, row.product) == ("square_off", "intraday")

    # Play out the day: the session finishes at the 15:30 close with the trade long gone.
    runner.advance(db, sim, 1000, fake_provider)
    assert sim.status == SimStatus.FINISHED and sim.cursor == ist(15, 30)
    assert len(orders_of(db, sim)) == 2


# --- isolation and honesty --------------------------------------------------------------


def test_the_sim_and_the_live_account_never_see_each_others_trades(
    client, db: Session, fake_provider: FakeProvider
):
    sim = make_sim(db, fake_provider)
    play_to(db, sim, fake_provider, ist(9, 20))
    base = f"/api/sim/sessions/{sim.id}"
    bought = client.post(
        f"{base}/orders", json={"symbol": SYMBOL, "side": "buy", "type": "market", "quantity": "5"}
    )
    assert bought.status_code == 200, bought.text
    # Bitcoin trades round the clock, so the live account (on the real calendar) can buy it.
    live_buy = client.post(
        "/api/orders", json={"symbol": "BTC-USD", "side": "buy", "type": "market", "quantity": "0.001"}
    )
    assert live_buy.status_code == 200, live_buy.text

    live_symbols = {t["symbol"] for t in client.get("/api/trades").json()}
    sim_symbols = {t["symbol"] for t in client.get(f"{base}/trades").json()}
    assert live_symbols == {"BTC-USD"} and sim_symbols == {SYMBOL}
    assert {o["symbol"] for o in client.get("/api/orders").json()} == {"BTC-USD"}
    assert {o["symbol"] for o in client.get(f"{base}/orders").json()} == {SYMBOL}

    # Cash moved only in the account that traded.
    live_cash = D(client.get("/api/portfolio").json()["cash"])
    sim_cash = D(client.get(f"{base}/portfolio").json()["cash"])
    assert live_cash < D("1000000") and sim_cash < D("1000000") and live_cash != sim_cash
    assert D(client.get(f"{base}/portfolio").json()["starting_cash"]) == D("1000000")

    # The sim's account is not a live one, so the background loop never touches it.
    sim_account = db.get(Account, sim.account_id)
    assert sim_account.kind == AccountKind.SIM
    assert [a.id for a in engine.live_accounts(db)] == [engine.get_account(db).id]
    # Exiting through the sim route closes the sim's trade, not a live one.
    [sim_trade] = trades_of(db, sim)
    exit_order = client.post(f"{base}/trades/{sim_trade.id}/exit")
    assert exit_order.status_code == 200 and exit_order.json()["origin"] == "exit"
    assert {t["symbol"]: t["status"] for t in client.get("/api/trades").json()} == {"BTC-USD": "open"}
    assert client.get(f"{base}/payouts").json()["totals"]["trades_closed"] == 1
    assert client.get("/api/payouts").json()["totals"]["trades_closed"] == 0


def test_the_state_never_shows_a_bar_after_the_cursor(client, db: Session, fake_provider: FakeProvider):
    sim = make_sim(db, fake_provider)
    base = f"/api/sim/sessions/{sim.id}"
    at_start = client.get(base).json()
    assert at_start["status"] == "ready" and at_start["bars"][SYMBOL] == []

    def check(expected_bars: int) -> dict:
        state = client.get(base).json()
        cursor = int(datetime.fromisoformat(state["cursor"]).timestamp())
        bars = state["bars"][SYMBOL]
        assert len(bars) == expected_bars
        # Bars are stamped in exchange-local time like a live chart (UTC + 19,800 s), and a bar
        # lasts 60 s: its close, start + 60, must not be after the cursor.
        assert all(b["time"] - 19800 + 60 <= cursor for b in bars)
        return state

    play_to(db, sim, fake_provider, ist(9, 20))
    state = check(5)  # 09:15 to 09:19
    assert state["cursor"].startswith("2026-02-26T03:50:00")
    [local] = state["exchange_times"]
    assert local["timezone"] == "Asia/Kolkata" and local["local_time"].startswith("2026-02-26T09:20:00+05:30")

    stepped = client.post(f"{base}/control", json={"action": "step", "steps": 3})
    assert stepped.status_code == 200 and stepped.json()["status"] == "paused"
    check(8)
    assert 0 < client.get(base).json()["progress_percent"] < 5
    # A short tail on request, never more than has been revealed.
    assert len(client.get(f"{base}?bars_limit=2").json()["bars"][SYMBOL]) == 2
    assert client.get(f"{base}?bars_limit=0").json()["bars"][SYMBOL] == []

    runner.advance(db, sim, 10_000, fake_provider)
    state = check(375)
    assert state["status"] == "finished" and state["progress_percent"] == 100


def test_the_live_loop_and_the_runner_share_one_step_function(
    db: Session, fake_provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
):
    assert [(name, fn) for name, fn in tick.TICK_STEPS] == [
        ("Filling open orders", engine.fill_open_orders),
        ("Firing stop-losses and targets", engine.trigger_protected_trades),
        ("Squaring off intraday shorts", engine.square_off_due),
        ("Charging borrow and funding", engine.accrue_financing),
    ]
    # Neither module has a sequence of its own.
    assert main.run_tick is tick.run_tick and runner.run_tick is tick.run_tick
    assert "fill_open_orders" not in inspect.getsource(main._fill_once)
    assert "fill_open_orders" not in inspect.getsource(runner)

    seen: list[tuple[str, int]] = []

    def spy(ctx):
        seen.append((ctx.account.kind, ctx.account.id))

    class Keep:
        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    sim = make_sim(db, fake_provider)
    monkeypatch.setattr(main, "run_tick", spy)
    monkeypatch.setattr(runner, "run_tick", spy)
    monkeypatch.setattr(main, "SessionLocal", Keep)
    monkeypatch.setattr(main, "get_provider", lambda: fake_provider)
    main._fill_once()
    runner.advance(db, sim, 2, fake_provider)
    assert seen == [
        ("live", engine.get_account(db).id),
        ("sim", sim.account_id),
        ("sim", sim.account_id),
    ]


# --- the runner itself ------------------------------------------------------------------


def test_a_quote_from_the_previous_session_cannot_fill_an_order(db: Session, fake_provider: FakeProvider):
    # Half-hour bars over Wed 25 and Thu 26 Feb for Apple and Bitcoin. Bitcoin's bars end on the
    # half hour round the clock, so the cursor lands exactly on 09:30 New York (14:30 UTC), the
    # moment the US market opens, while Apple's newest bar is still Wednesday's 16:00 close.
    sim = make_sim(db, fake_provider, ("AAPL", "BTC-USD"), date(2026, 2, 25), DAY, interval="30m")
    at = datetime(2026, 2, 26, 14, 30, tzinfo=UTC)
    ctx = play_to(db, sim, fake_provider, at)
    assert ctx.provider.get_quote("AAPL").as_of < at.timestamp()
    order = market_order(ctx, OrderSide.BUY, "1", "AAPL")
    assert order.status == OrderStatus.OPEN and order.fill_price is None

    # The first Thursday bar finishes at 15:00 UTC; now the quote is fresh and the order fills.
    runner.advance(db, sim, 1, fake_provider)
    assert sim.cursor == datetime(2026, 2, 26, 15, 0, tzinfo=UTC)
    assert order.status == OrderStatus.FILLED and order.filled_at == sim.cursor


def test_a_symbol_with_no_bar_yet_has_no_price(db: Session, fake_provider: FakeProvider):
    # Only Thursday is loaded, so at 09:30 New York Apple has not had a single bar.
    sim = make_sim(db, fake_provider, ("AAPL", "BTC-USD"), interval="30m")
    ctx = play_to(db, sim, fake_provider, datetime(2026, 2, 26, 14, 30, tzinfo=UTC))
    with pytest.raises(DataUnavailable):
        market_order(ctx, OrderSide.BUY, "1", "AAPL")
    assert orders_of(db, sim) == []


def test_a_foreign_symbol_is_converted_at_the_nearest_earlier_daily_close(
    db: Session, fake_provider: FakeProvider
):
    sim = make_sim(db, fake_provider, ("AAPL",))
    ctx = play_to(db, sim, fake_provider, datetime(2026, 2, 26, 14, 35, tzinfo=UTC))
    order = market_order(ctx, OrderSide.BUY, "1", "AAPL")
    # Wednesday's USD/INR daily bar closes at midnight UTC on Thursday, the latest one finished.
    wednesday = FakeProvider().get_history("USDINR=X", "1d", date(2026, 2, 25), date(2026, 2, 25))[0]
    assert order.status == OrderStatus.FILLED and order.fx_rate == wednesday.close.quantize(D("1E-8"))


def test_the_cursor_jumps_over_nights_and_weekends(db: Session, fake_provider: FakeProvider):
    # Friday 27 Feb to Monday 2 Mar: 3 sessions' worth is not 3 x 24 hours of minutes.
    sim = make_sim(db, fake_provider, start=date(2026, 2, 27), end=date(2026, 3, 2))
    assert runner.advance(db, sim, 375, fake_provider) == 375
    assert sim.cursor == ist(15, 30, date(2026, 2, 27))
    assert runner.advance(db, sim, 1, fake_provider) == 1
    assert sim.cursor == ist(9, 16, date(2026, 3, 2))  # one step across the weekend
    assert runner.advance(db, sim, 10_000, fake_provider) == 374
    assert sim.status == SimStatus.FINISHED
    assert runner.advance(db, sim, 5, fake_provider) == 0


def test_a_gap_in_the_bars_does_not_make_the_square_off_late(db: Session, fake_provider: FakeProvider):
    # Yahoo's minutes are not all there. Take out the bars that start 15:16 to 15:27 (as one real
    # day had it): the last bar before the gap finishes at 15:16 and the next at 15:29. The clock
    # still reaches 15:20, so the short is bought back then, at the last price standing.
    sim = make_sim(db, fake_provider)
    first, last = int(ist(15, 16).timestamp()), int(ist(15, 27).timestamp())
    db.execute(delete(BarCache).where(BarCache.symbol == SYMBOL, BarCache.ts.between(first, last)))
    db.commit()

    ctx = play_to(db, sim, fake_provider, ist(10, 0))
    market_order(ctx, OrderSide.SELL, "100")
    runner.advance_until(db, sim, ist(15, 19), fake_provider)
    assert sim.cursor == ist(15, 19)  # stepped through the gap a minute at a time
    [trade] = trades_of(db, sim)
    assert trade.status == "open"
    runner.advance(db, sim, 1, fake_provider)
    assert trade.closed_how == "square_off" and trade.closed_at == ist(15, 20)
    cover = next(o for o in orders_of(db, sim) if o.origin == "square_off")
    # The bar starting 15:15 is the last that finished; its close is read back from the cache.
    last_bar = db.scalar(
        select(BarCache).where(BarCache.symbol == SYMBOL, BarCache.ts == int(ist(15, 15).timestamp()))
    )
    assert cover.fill_price == last_bar.close and cover.note == "Squared off at 15:20 IST."

    # The far side of the gap is reached, and a night is still one jump, not a thousand steps.
    runner.advance(db, sim, 1000, fake_provider)
    assert sim.status == SimStatus.FINISHED and sim.cursor == ist(15, 30)


def test_the_driver_advances_running_sessions_by_their_speed(
    db: Session, fake_provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
):
    class Keep:
        def __enter__(self):
            return db

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(driver, "SessionLocal", Keep)
    monkeypatch.setattr(driver, "get_provider", lambda: fake_provider)
    running = make_sim(db, fake_provider, speed=7)
    paused = make_sim(db, fake_provider, speed=7)
    running.status = SimStatus.RUNNING
    paused.status = SimStatus.PAUSED
    db.commit()

    driver.drive_once()
    assert running.cursor == ist(9, 15 + 7) and paused.cursor == ist(9, 15)


# --- the API ----------------------------------------------------------------------------


def test_create_validates_the_range_and_makes_an_account(client, db: Session, fake_provider: FakeProvider):
    body = {"symbols": [SYMBOL], "interval": "1m", "start_date": "2026-02-26", "end_date": "2026-02-26"}
    created = client.post("/api/sim/sessions", json=body | {"speed": 30})
    assert created.status_code == 200, created.text
    made = created.json()
    assert (made["status"], made["speed"], made["interval"]) == ("ready", 30, "1m")
    assert made["cursor"].startswith("2026-02-26T03:45:00")
    account = db.get(Account, made["account_id"])
    live = engine.get_account(db)
    assert (account.kind, account.cash, account.currency) == ("sim", D("1000000"), "INR")
    assert (account.broker_india, account.broker_international, account.broker_crypto) == (
        live.broker_india, live.broker_international, live.broker_crypto
    )
    assert [s["id"] for s in client.get("/api/sim/sessions").json()] == [made["id"]]

    # Saturday 28 Feb: no bars. 1-minute bars only go back ~30 days. Speed is 1 to 200.
    saturday = {"start_date": "2026-02-28", "end_date": "2026-02-28"}
    weekend = client.post("/api/sim/sessions", json=body | saturday)
    assert weekend.status_code == 400 and "shut" in weekend.json()["detail"]
    old = client.post("/api/sim/sessions", json=body | {"start_date": "2026-01-05", "end_date": "2026-01-06"})
    assert old.status_code == 400 and "30" in old.json()["detail"]
    assert client.post("/api/sim/sessions", json=body | {"speed": 201}).status_code == 422
    index = client.post("/api/sim/sessions", json=body | {"symbols": ["^NSEI"]})
    assert index.status_code == 400
    assert client.get("/api/sim/sessions/999").status_code == 404
    # A refused request leaves nothing behind.
    assert len(client.get("/api/sim/sessions").json()) == 1
    assert db.scalar(select(Account.id).where(Account.kind == AccountKind.SIM).limit(1)) == made["account_id"]


def test_control_and_delete(client, db: Session, fake_provider: FakeProvider):
    body = {"symbols": [SYMBOL], "start_date": "2026-02-26", "end_date": "2026-02-26", "speed": 10}
    sim_id = client.post("/api/sim/sessions", json=body).json()["id"]
    base = f"/api/sim/sessions/{sim_id}"

    started = client.post(f"{base}/control", json={"action": "start", "speed": 100})
    assert started.json()["status"] == "running"
    assert client.get(base).json()["speed"] == 100
    assert client.post(f"{base}/control", json={"action": "step"}).status_code == 409  # pause first
    assert client.post(f"{base}/control", json={"action": "pause"}).json()["status"] == "paused"
    stepped = client.post(f"{base}/control", json={"action": "step", "steps": 6}).json()
    assert stepped["cursor"].startswith("2026-02-26T03:51:00")

    # Trade, then reset: back to the first bar, the starting cash, no orders or trades.
    assert client.post(
        f"{base}/orders", json={"symbol": SYMBOL, "side": "buy", "type": "market", "quantity": "1"}
    ).status_code == 200
    reset = client.post(f"{base}/control", json={"action": "reset"}).json()
    assert reset["status"] == "ready" and reset["cursor"].startswith("2026-02-26T03:45:00")
    assert client.get(f"{base}/orders").json() == [] and client.get(f"{base}/trades").json() == []
    assert D(client.get(f"{base}/portfolio").json()["cash"]) == D("1000000")

    # A finished session can't be started again until it is reset.
    runner.advance(db, runner.get_session(db, sim_id), 10_000, fake_provider)
    assert client.post(f"{base}/control", json={"action": "start"}).status_code == 409

    account_id = client.get(base).json()["account_id"]
    assert client.delete(base).status_code == 204
    assert client.get(base).status_code == 404
    assert db.get(Account, account_id) is None
    assert client.get(f"{base}/orders").status_code == 404


def test_order_errors_in_a_sim_read_like_the_live_ones(client, db: Session, fake_provider: FakeProvider):
    sim = make_sim(db, fake_provider)
    play_to(db, sim, fake_provider, ist(9, 20))
    bad = client.post(
        f"/api/sim/sessions/{sim.id}/orders",
        json={"symbol": SYMBOL, "side": "buy", "type": "market", "quantity": "lots"},
    )
    live_bad = client.post(
        "/api/orders", json={"symbol": SYMBOL, "side": "buy", "type": "market", "quantity": "lots"}
    )
    assert bad.status_code == live_bad.status_code == 422
    assert bad.json() == live_bad.json()
