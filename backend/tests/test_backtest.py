"""The backtester: strategies replayed over a past range through the real engine.

Daily fixtures use real NSE working days in February 2026 (Mon 2 to Fri 13, no holidays), so the
real exchange calendar decides what can fill. A RELIANCE.NS session runs 09:15 to 15:30 IST, i.e.
03:45 to 10:00 UTC; a daily bar quotes its open from 03:45 and its close from 10:00.

The two prices a daily bar has, and why a decision made at a close fills at the next open:
a trader sees day t's close at 10:00 UTC, the market is shut until day t+1's 03:45 UTC, and the
first price after the decision is that morning's open.
"""

import multiprocessing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algos import hq, jobs
from app.algos.api import ParameterError
from app.algos.backtest import (
    BacktestError,
    cagr_pct,
    daily_equity,
    drawdown_series,
    max_drawdown_pct,
    run_backtest,
    sharpe_ratio,
)
from app.algos.library import LIBRARY
from app.algos.runner import run_strategy_on
from app.market_data.base import Bar, DataUnavailable, Instrument
from app.market_data.fake import FakeProvider
from app.market_data.history import HistoryRangeError
from app.market_data.replay import ReplayProvider
from app.models import Account, AccountKind, Backtest, BacktestStatus, Order, Trade
from app.trading import hours
from app.trading.context import TradingContext
from app.trading.markets import MARKETS

D = Decimal
TODAY = date(2026, 3, 2)
SYMBOL = "RELIANCE.NS"
# Mon 2 Feb to Fri 13 Feb 2026: ten NSE sessions.
DAYS = [date(2026, 2, d) for d in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13)]


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def open_of(day: date) -> datetime:
    return at(day, 3, 45)  # 09:15 IST


def close_of(day: date) -> datetime:
    return at(day, 10, 0)  # 15:30 IST


class FixtureProvider(FakeProvider):
    """The offline provider, except that chosen (symbol, interval) pairs serve bars made for the
    test, so the expected figures can be worked out by hand."""

    def __init__(self) -> None:
        super().__init__()
        self.series: dict[tuple[str, str], list[Bar]] = {}

    def set_daily(self, symbol: str, days: list[date], opens: list, closes: list) -> None:
        bars = []
        for day, o, c in zip(days, opens, closes, strict=True):
            o, c = D(str(o)), D(str(c))
            bars.append(Bar(day.isoformat(), o, max(o, c) + 1, min(o, c) - 1, c, 1000))
        self.series[(symbol, "1d")] = bars

    def get_history(self, symbol, interval, start, end):
        if (symbol, interval) in self.series:
            return [
                b for b in self.series[(symbol, interval)] if start <= date.fromisoformat(str(b.time)) <= end
            ]
        return super().get_history(symbol, interval, start, end)


def backtest(db: Session, provider, strategy, params=None, *, symbols=(SYMBOL,), interval="1d", **kw):
    args = dict(
        params=params or {}, symbols=list(symbols), interval=interval, start=DAYS[0], end=DAYS[-1],
        starting_cash=D(100000), account_currency="INR", today=TODAY,
    )  # fmt: skip
    args.update(kw)
    if strategy is None:
        return run_backtest(db, provider, **args)  # uploaded code comes in `source=`
    if isinstance(strategy, str):
        return run_backtest(db, provider, strategy_key=strategy, **args)
    return run_backtest(db, provider, strategy_cls=strategy, **args)


def scratch_accounts(db: Session) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.kind == AccountKind.BACKTEST)))


# --- the daily open/close quote rule ----------------------------------------------------------


def nse_replay(interval: str = "1d", *, with_hours: bool = True) -> ReplayProvider:
    market = MARKETS["NSE"]
    sessions = {SYMBOL: lambda day: hours.session_bounds(market, day)} if with_hours else None
    replay = ReplayProvider(
        at(DAYS[0], 0),
        instruments={SYMBOL: Instrument(SYMBOL, "Reliance", "NSE", "equity", "INR")},
        timezones={SYMBOL: "Asia/Kolkata"},
        sessions=sessions,
    )
    bars = [
        Bar("2026-02-02", D(1000), D(1020), D(990), D(1010), 1),
        Bar("2026-02-03", D(1030), D(1040), D(1000), D(1005), 1),
    ]
    replay.load(SYMBOL, interval, bars)
    return replay


@pytest.mark.real_calendar
def test_a_daily_bar_quotes_its_open_from_the_bell_and_its_close_from_the_close():
    replay = nse_replay()
    market = MARKETS["NSE"]

    replay.cursor = at(DAYS[0], 3, 44)  # a minute before the bell
    with pytest.raises(DataUnavailable):
        replay.get_quote(SYMBOL)

    replay.cursor = open_of(DAYS[0])
    quote = replay.get_quote(SYMBOL)
    assert quote.price == D(1000)  # the open
    assert quote.as_of == int(open_of(DAYS[0]).timestamp())
    assert hours.can_fill(market, quote.as_of, replay.cursor)  # fresh in a session that is open
    assert replay.get_bars(SYMBOL, "1d", "max") == []  # the day's bar has not closed

    replay.cursor = at(DAYS[0], 9, 59)
    assert replay.get_quote(SYMBOL).price == D(1000)  # still the open until the close

    replay.cursor = close_of(DAYS[0])
    quote = replay.get_quote(SYMBOL)
    assert quote.price == D(1010)
    assert quote.as_of == int(close_of(DAYS[0]).timestamp())
    assert [b.time for b in replay.get_bars(SYMBOL, "1d", "max")] == ["2026-02-02"]

    replay.cursor = at(DAYS[0], 20)  # overnight: yesterday's close still stands
    assert replay.get_quote(SYMBOL).price == D(1010)

    replay.cursor = open_of(DAYS[1])
    quote = replay.get_quote(SYMBOL)
    assert quote.price == D(1030)
    assert quote.previous_close == D(1010)
    assert [b.time for b in replay.get_bars(SYMBOL, "1d", "max")] == ["2026-02-02"]

    assert replay.visit_times([SYMBOL], "1d") == [
        int(t.timestamp()) for t in (open_of(DAYS[0]), close_of(DAYS[0]), open_of(DAYS[1]), close_of(DAYS[1]))
    ]
    assert replay.first_cursor([SYMBOL], "1d") == datetime(2026, 2, 2, 3, 44, 59, tzinfo=UTC)


@pytest.mark.real_calendar
def test_without_exchange_hours_a_daily_bar_could_never_fill():
    """The fault this rule fixes: a bar stamped at UTC midnight 'ends' at the next midnight, so its
    price is dated before the session it would be traded in and `can_fill` refuses it."""
    replay = nse_replay(with_hours=False)
    replay.cursor = open_of(DAYS[1])
    quote = replay.get_quote(SYMBOL)  # day 1's close, stamped at midnight UTC
    assert not hours.can_fill(MARKETS["NSE"], quote.as_of, replay.cursor)


@pytest.mark.real_calendar
def test_crypto_days_run_midnight_to_midnight_and_weeks_span_their_sessions():
    crypto = MARKETS["CRYPTO"]
    day = date(2026, 2, 7)  # a Saturday: crypto trades on it
    assert hours.session_bounds(crypto, day) == (at(day, 0), datetime(2026, 2, 7, 23, 59, 59, tzinfo=UTC))
    assert hours.session_bounds(MARKETS["NSE"], day) is None  # shut

    replay = ReplayProvider(
        at(DAYS[0], 0),
        instruments={SYMBOL: Instrument(SYMBOL, "Reliance", "NSE", "equity", "INR")},
        sessions={SYMBOL: lambda d: hours.session_bounds(MARKETS["NSE"], d)},
    )
    week = [Bar("2026-02-02", D(100), D(130), D(90), D(120), 1)]  # labelled with its Monday
    replay.load(SYMBOL, "1wk", week)
    replay.cursor = open_of(DAYS[0])
    assert replay.get_quote(SYMBOL).price == D(100)  # the week opens with Monday's bell
    replay.cursor = at(DAYS[3], 10, 0)  # Thursday's close: the week is not over
    assert replay.get_quote(SYMBOL).price == D(100)
    replay.cursor = close_of(DAYS[4])  # Friday 6 Feb closes the week
    assert replay.get_quote(SYMBOL).price == D(120)


# --- a known SMA crossover, end to end --------------------------------------------------------

# Ten NSE sessions, 2 to 13 Feb 2026. RELIANCE.NS opens and closes:
#   day      0    1    2    3    4    5    6    7    8    9
#   open   100  100  100  100   85   85  112  121  128   95
#   close  100  100  100   90   80  110  120  130  100   70
# SMA crossover with fast=2, slow=3, 100% of cash. Averages of the closes:
#   day      3      4      5       6      7    8        9
#   fast    95     85     95     115    125  115       85
#   slow  96.67     90  93.33  103.33    120  116.67   100
# Day 5 (close 110): fast 85 -> 95 crosses above slow 90 -> 93.33. Buy decided at the day-5 close;
# the next price is day 6's OPEN, 112. Not the day-5 close (110) it was decided at.
# Day 8 (close 100): fast 125 -> 115 crosses below slow 120 -> 116.67. Sell decided at the day-8
# close; fills at day 9's open, 95.
# Zero charges here (see test_buy_and_hold_pays_real_charges for the costed case):
#   buy  floor(100,000 / 112) = 892 shares (892 x 112 = 99,904; 893 x 112 = 100,016 is too much)
#        cash 100,000 - 99,904 = 96
#   sell 892 x 95 = 84,740 -> cash 96 + 84,740 = 84,836; realized 84,836 - 100,000 = -15,164
# Equity at each close (cash + shares x close): days 0-5 100,000 (cash only);
#   day 6: 96 + 892 x 120 = 107,136    day 7: 96 + 892 x 130 = 116,056
#   day 8: 96 + 892 x 100 =  89,296    day 9: 84,836 (sold at that morning's open)
# Buy-and-hold: day 0's open is 100, so 1,000 shares for 100,000; worth 1,000 x close.
SMA_OPENS = [100, 100, 100, 100, 85, 85, 112, 121, 128, 95]
SMA_CLOSES = [100, 100, 100, 90, 80, 110, 120, 130, 100, 70]
SMA_PARAMS = {"fast_period": 2, "slow_period": 3, "percent_of_cash": 100}


@pytest.fixture
def sma_world(db: Session) -> FixtureProvider:
    provider = FixtureProvider()
    provider.set_daily(SYMBOL, DAYS, SMA_OPENS, SMA_CLOSES)
    return provider


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
def test_sma_crossover_fills_at_the_next_days_open(db: Session, sma_world: FixtureProvider):
    results = backtest(db, sma_world, "sma_crossover", SMA_PARAMS)

    (trade,) = results.trades
    assert trade.symbol == SYMBOL and trade.direction == "long" and trade.status == "closed"
    assert trade.quantity == D(892)
    assert trade.entry_at == open_of(DAYS[6])  # bought on day 6's open, not day 5's close
    assert trade.entry_price == D(112)
    assert trade.exit_at == open_of(DAYS[9])
    assert trade.exit_price == D(95)
    assert trade.closed_how == "sell"
    assert trade.realized_pnl == D(-15164)
    assert trade.gross_pnl == D(-15164)  # no charges, so gross equals net
    assert trade.charges_total == 0 and trade.financing == 0

    assert trade.id == 1 and [o.id for o in results.orders] == [1, 2]  # numbered within the run
    assert [o.trade_id for o in results.orders] == [1, 1]
    assert [leg.trade_id for o in results.orders for leg in o.legs] == [1, 1]
    assert [o.side for o in results.orders] == ["buy", "sell"]
    assert [o.fill_price for o in results.orders] == [D(112), D(95)]
    assert [o.filled_at for o in results.orders] == [open_of(DAYS[6]), open_of(DAYS[9])]

    assert [p.at for p in results.equity_curve] == [close_of(d) for d in DAYS]  # one point a day
    assert [p.equity for p in results.equity_curve] == [D(100000)] * 6 + [
        D(107136), D(116056), D(89296), D(84836),
    ]  # fmt: skip
    assert [p.cash for p in results.equity_curve][6] == D(96)
    assert [p.positions for p in results.equity_curve][6] == D(107040)  # 892 x 120

    m = results.metrics
    assert m.final_equity == D(84836)
    assert m.total_return_pct == D("-15.16")  # -15,164 / 100,000 = -15.164%
    # Peak 116,056 on day 7, trough 84,836 on day 9: (84,836 - 116,056) / 116,056 = -26.9008%.
    assert m.max_drawdown_pct == D("26.90")
    # Day 8: (89,296 - 116,056) / 116,056 = -23.058%.
    assert [d.strategy_pct for d in results.drawdown][7:] == [D("0.00"), D("-23.06"), D("-26.90")]
    assert m.trades_closed == 1 and m.trades_open == 0
    assert m.win_rate_pct == D("0.00") and m.average_win is None
    assert m.average_loss == D(-15164) and m.profit_factor == D("0.00")  # lost money, won none: a factor of 0
    assert m.exposure_pct == D("30.00")  # a position at the close of days 6, 7, 8 of 10
    assert m.total_charges == 0 and m.charges_pct_of_gross_profit is None
    assert m.sharpe is None and "at least 20 days" in m.sharpe_note
    assert m.cagr_pct is None and "at least a year" in m.cagr_note and "12 days" in m.cagr_note

    hold = results.buy_and_hold
    assert hold.purchases[0].at == open_of(DAYS[0])
    assert hold.purchases[0].quantity == D(1000) and hold.purchases[0].price == D(100)
    assert hold.final_equity == D(70000)  # 1,000 x 70
    assert hold.total_return_pct == D("-30.00")
    assert [p.buy_hold_equity for p in results.equity_curve][:4] == [
        D(100000),
        D(100000),
        D(100000),
        D(90000),
    ]

    assert scratch_accounts(db) == []  # nothing left behind
    assert db.scalars(select(Trade)).all() == [] and db.scalars(select(Order)).all() == []


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
def test_uploaded_source_runs_in_the_sandbox_with_the_same_result(db: Session, sma_world: FixtureProvider):
    path = Path(__file__).parents[1] / "app" / "algos" / "library" / "sma_crossover.py"
    args = dict(
        params=SMA_PARAMS, symbols=[SYMBOL], interval="1d", start=DAYS[0], end=DAYS[-1],
        starting_cash=D(100000), account_currency="INR", today=TODAY,
    )  # fmt: skip
    from_source = run_backtest(db, sma_world, source=path.read_text(encoding="utf-8"), **args)
    from_class = run_backtest(db, sma_world, strategy_key="sma_crossover", **args)
    assert from_source.trades == from_class.trades and from_source.trades
    assert from_source.metrics.final_equity == from_class.metrics.final_equity
    assert multiprocessing.active_children() == []
    assert scratch_accounts(db) == []


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
def test_the_same_inputs_give_identical_results(db: Session, sma_world: FixtureProvider):
    first = backtest(db, sma_world, "sma_crossover", SMA_PARAMS)
    # Something else in the tables moves the row ids a rerun would get.
    db.add(Account(currency="INR", cash=D(1), starting_cash=D(1), realized_pnl=D(0), margin_used=D(0),
                   created_at=at(DAYS[0], 0), kind=AccountKind.SIM))  # fmt: skip
    db.commit()
    second = backtest(db, sma_world, "sma_crossover", SMA_PARAMS)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


# --- no look-ahead, end to end ---------------------------------------------------------------

SEEN: list = []


class Peeker(hq.Strategy):
    """Does everything it can to see the future."""

    name = "Peeker"
    interval = "1d"
    warmup_bars = 1

    def on_bar(self, ctx):
        everything = ctx.bars(SYMBOL, 10**9)  # more bars than exist
        SEEN.append((ctx.now, [b.time for b in everything], ctx.price(SYMBOL), everything[-1].close))
        try:
            ctx.price("TSLA")  # a symbol that is not in the run
        except ValueError:
            SEEN.append("refused")


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
def test_a_strategy_that_peeks_only_ever_sees_closed_bars(db: Session, sma_world: FixtureProvider):
    SEEN.clear()
    results = backtest(db, sma_world, Peeker)
    calls = [s for s in SEEN if s != "refused"]
    assert SEEN.count("refused") == 10 and results.errors == []
    assert len(calls) == 10  # on_bar ran once per closed bar, at the close, never at the open
    for k, (now, times, price, last_close) in enumerate(calls):
        assert now == close_of(DAYS[k])
        assert times == [d.isoformat() for d in DAYS[: k + 1]]  # today's bar and nothing after it
        assert price == last_close == D(SMA_CLOSES[k])  # not tomorrow's open (SMA_OPENS[k + 1])


# --- charges --------------------------------------------------------------------------------


class Idle(hq.Strategy):
    name = "Idle"
    interval = "1d"
    warmup_bars = 1


@pytest.mark.real_calendar
def test_buy_and_hold_pays_real_charges(db: Session):
    # Five sessions with the price at 1,000 until the last close of 1,100. 100,000 rupees at Groww.
    # The first price is day 0's open, 1,000. 100 shares would cost 100,000 before any charge, so
    # the quantity steps down to 99 (value 99,000):
    #   brokerage  0.1% = 99.00, capped at 20.00                      20.00
    #   exchange   0.00307% of 99,000 = 3.0393                         3.04
    #   STT        0.1% of 99,000                                     99.00
    #   stamp duty 0.015% of 99,000 = 14.85                           14.85
    #   SEBI       0.0001% of 99,000 = 0.099                           0.10
    #   GST        18% of (20.00 + 3.04 + 0.10) = 4.1652               4.17
    #   total 141.16;  99,000 + 141.16 = 99,141.16 fits in 100,000 (100 shares would not)
    # Cash left 858.84. On day 4's close: 99 x 1,100 = 108,900 + 858.84 = 109,758.84, i.e. +9.76%.
    provider = FixtureProvider()
    provider.set_daily(SYMBOL, DAYS[:5], [1000] * 5, [1000, 1000, 1000, 1000, 1100])
    results = backtest(db, provider, Idle, end=DAYS[4])

    hold = results.buy_and_hold
    (purchase,) = hold.purchases
    assert purchase.quantity == D(99) and purchase.price == D(1000) and purchase.at == open_of(DAYS[0])
    assert purchase.charges == D("141.16")
    assert hold.total_charges == D("141.16")
    assert hold.final_equity == D("109758.84")
    assert hold.total_return_pct == D("9.76")
    assert results.equity_curve[-1].buy_hold_equity == D("109758.84")
    # Idle never traded: flat, free, and 9.76 points behind.
    assert results.metrics.final_equity == D(100000) and results.metrics.total_charges == 0


@pytest.mark.real_calendar
def test_charges_are_reported_by_category_and_against_gross_profit(db: Session):
    # An SMA round trip that wins. Fast=2, slow=3, 100% cash; closes 100 100 100 90 80 110 120 130
    # 100 70 would lose, so use a rising tail: opens/closes below are made so day 8 sells high.
    #   buy decided day 5 -> day 6 open 112 (as above)    sell decided day 8 -> day 9 open 140
    provider = FixtureProvider()
    provider.set_daily(SYMBOL, DAYS, SMA_OPENS[:9] + [140], SMA_CLOSES)
    results = backtest(db, provider, "sma_crossover", SMA_PARAMS)
    (trade,) = results.trades
    # 99,904 of shares at the 112 open fit in 100,000 only without charges: with them the order
    # steps down, so the quantity is below 892.
    assert trade.quantity < D(892)
    assert trade.realized_pnl > 0
    assert trade.charges_total == trade.entry_charges + trade.exit_charges
    assert sum(trade.charges_by_category.values()) == trade.charges_total
    assert set(trade.charges_by_category) >= {"brokerage", "exchange", "tax", "gst", "depository"}
    # Gross profit is what the price move paid before charges; the charges are measured against it.
    assert trade.gross_pnl == trade.realized_pnl + trade.charges_total + trade.financing
    m = results.metrics
    assert m.total_charges == trade.charges_total
    assert m.gross_profit == trade.gross_pnl
    assert m.charges_pct_of_gross_profit == (trade.charges_total / trade.gross_pnl * 100).quantize(D("0.01"))
    assert m.win_rate_pct == D("100.00") and m.average_win == trade.realized_pnl.quantize(D("0.01"))
    assert m.profit_factor is None  # no losing trade to divide by


# --- Sharpe, drawdown and CAGR by hand ----------------------------------------------------------


def test_drawdown_by_hand():
    # From 100: 110 is a new high (0), 99 is 10% under it, 121 a new high, 108.9 is 10% under 121.
    equities = [D(110), D(99), D(121), D("108.9")]
    series = drawdown_series(equities, D(100))
    assert series == [D("0.00"), D("-10.00"), D("0.00"), D("-10.00")]
    assert max_drawdown_pct(series) == D("10.00")
    # The starting cash is itself a peak: falling straight from 100 to 80 is a 20% drawdown.
    assert drawdown_series([D(80)], D(100)) == [D("-20.00")]
    assert max_drawdown_pct([]) == 0


def test_sharpe_by_hand():
    # Twenty days alternating +2% and -1%, from 100,000: 102,000, 100,980, 102,999.60, ...
    equities, value = [], D(100000)
    for day in range(20):
        value *= D("1.02") if day % 2 == 0 else D("0.99")
        equities.append(value)
    # Returns: ten of +0.02 and ten of -0.01. Mean 0.005; every return is 0.015 from it, so the
    # sample variance is 20 x 0.015^2 / 19 = 0.0045 / 19 = 0.00023684 and the deviation 0.015390.
    # Sharpe = 0.005 / 0.015390 x sqrt(252) = 0.32490 x 15.8745 = 5.1576; with sqrt(365) = 19.1050
    # (crypto trades every day) it is 6.2071.
    ratio, note = sharpe_ratio(equities, D(100000), 252)
    assert ratio == D("5.16") and note is None
    assert sharpe_ratio(equities, D(100000), 365)[0] == D("6.21")

    short = sharpe_ratio(equities[:19], D(100000), 252)  # one day too few
    assert short[0] is None and "at least 20 days" in short[1] and "has 19" in short[1]
    flat = sharpe_ratio([D(100000)] * 25, D(100000), 252)
    assert flat[0] is None and "never varied" in flat[1]


def test_daily_equity_keeps_the_last_point_of_each_utc_day():
    stamps = [(int(at(DAYS[0], h).timestamp()), D(100 + h)) for h in (3, 9, 15)]
    stamps += [(int(at(DAYS[1], 0).timestamp()), D(150))]  # midnight closes the day before
    stamps += [(int(at(DAYS[1], 3).timestamp()), D(200))]
    assert daily_equity(stamps) == [D(150), D(200)]


def test_cagr_by_hand():
    # 100 -> 121 over 730 days: 1.21 ^ (365 / 730) - 1 = 1.1 - 1 = 10%.
    assert cagr_pct(D(100), D(121), 730) == (D("10.00"), None)
    value, note = cagr_pct(D(100), D(121), 364)
    assert value is None and "364 days" in note


# --- refusals ---------------------------------------------------------------------------------


def test_dates_out_of_range_are_refused_with_the_earliest_date(db: Session):
    provider = FakeProvider()
    kw = dict(symbols=["BTC-USD"], interval="1h", starting_cash=D(1000), account_currency="USD", today=TODAY)
    algo = "crypto_volatility_breakout"
    # 1h bars reach back 729 days from 2 Mar 2026: the earliest day is 2 Mar 2026 - 729 days = 3 Mar 2024.
    with pytest.raises(HistoryRangeError, match=r"earliest date available is 03 Mar 2024"):
        run_backtest(db, provider, strategy_key=algo, start=date(2024, 1, 1), end=date(2024, 1, 5), **kw)
    with pytest.raises(HistoryRangeError, match="no data after today"):
        run_backtest(db, provider, strategy_key=algo, start=date(2026, 2, 20), end=date(2026, 3, 9), **kw)
    with pytest.raises(HistoryRangeError, match="after the end date"):
        run_backtest(db, provider, strategy_key=algo, start=date(2026, 2, 20), end=date(2026, 2, 10), **kw)
    assert scratch_accounts(db) == []


def test_requests_that_cannot_run_are_refused_in_a_sentence(db: Session):
    provider = FakeProvider()
    kw = dict(
        symbols=["AAPL"],
        start=DAYS[0],
        end=DAYS[-1],
        starting_cash=D(1000),
        account_currency="USD",
        today=TODAY,
    )
    with pytest.raises(BacktestError, match="built for 1d bars, so it can't be tested on 1h"):
        run_backtest(db, provider, strategy_key="sma_crossover", interval="1h", **kw)
    with pytest.raises(BacktestError, match="There is no algorithm 'nope'"):
        run_backtest(db, provider, strategy_key="nope", interval="1d", **kw)
    with pytest.raises(ParameterError, match="Slow period must be at most 300"):
        run_backtest(
            db, provider, strategy_key="sma_crossover", interval="1d", params={"slow_period": 999}, **kw
        )
    with pytest.raises(BacktestError, match="can be charted but not traded"):
        run_backtest(
            db, provider, strategy_key="sma_crossover", interval="1d", **{**kw, "symbols": ["^GSPC"]}
        )
    # Only the ten window sessions exist (the fixture holds nothing earlier), so the 31 bars of
    # warmup can't be had: 0 before the start and 10 in the range.
    thin = FixtureProvider()
    thin.set_daily("AAPL", DAYS, SMA_OPENS, SMA_CLOSES)
    with pytest.raises(BacktestError, match=r"needs 31 bars.*only 10 1d bars exist"):
        run_backtest(db, thin, strategy_key="sma_crossover", interval="1d", **kw)
    assert scratch_accounts(db) == []


# --- an intraday run -------------------------------------------------------------------------


def test_an_hourly_crypto_backtest_runs(db: Session):
    provider = FakeProvider()
    start, end = date(2026, 2, 16), date(2026, 2, 22)  # seven days of 24 hourly bars
    results = run_backtest(
        db, provider, strategy_key="crypto_volatility_breakout", symbols=["BTC-USD"], interval="1h",
        start=start, end=end, starting_cash=D(10000), account_currency="USD", today=TODAY,
    )  # fmt: skip
    assert results.bars == 7 * 24 == len(results.equity_curve)  # a point for every bar
    assert results.curve_stride == 1
    assert results.errors == []
    assert results.equity_curve[0].at == datetime(2026, 2, 16, 1, 0, tzinfo=UTC)  # the first bar's close
    assert results.equity_curve[-1].at == datetime(2026, 2, 23, 0, 0, tzinfo=UTC)
    assert results.metrics.final_equity == results.equity_curve[-1].equity
    assert results.metrics.sharpe is None and "has 7" in results.metrics.sharpe_note  # seven days only
    # Crypto: the account is in dollars and the symbol too, so no FX pair was needed.
    assert results.buy_and_hold.purchases[0].symbol == "BTC-USD"
    assert scratch_accounts(db) == []


# --- sizing a percent of cash that includes charges --------------------------------------------


class AllIn(hq.Strategy):
    name = "All in"
    interval = "1d"
    warmup_bars = 1

    def on_bar(self, ctx):
        if not ctx.open_trades(SYMBOL) and not ctx.position(SYMBOL).quantity:
            ctx.buy(SYMBOL, percent_of_cash=100)


def test_one_hundred_percent_of_cash_leaves_room_for_the_charges(db: Session):
    # Groww, RELIANCE.NS at 1,000, 100,000 rupees, 100% of cash. Sizing by price alone gives 100
    # shares = 100,000, and the engine refuses the buy because the charges come on top. The
    # quantity must step down until value + charges fits. 99 shares (value 99,000):
    #   brokerage 20.00 (0.1% would be 99.00, capped at 20), exchange 3.04, STT 99.00,
    #   stamp duty 14.85, SEBI 0.10, GST 18% x (20.00 + 3.04 + 0.10) = 4.17  -> charges 141.16
    #   99,000 + 141.16 = 99,141.16 <= 100,000, so 99 shares; cash left 858.84.
    replay = ReplayProvider(
        at(DAYS[0], 0),
        instruments={SYMBOL: Instrument(SYMBOL, "Reliance", "NSE", "equity", "INR")},
    )
    replay.load(SYMBOL, "1d", [Bar(d.isoformat(), D(1000), D(1001), D(999), D(1000), 1) for d in DAYS[:3]])
    account = Account(currency="INR", cash=D(100000), starting_cash=D(100000), realized_pnl=D(0),
                      margin_used=D(0), created_at=at(DAYS[0], 0), kind=AccountKind.ALGO)  # fmt: skip
    db.add(account)
    db.commit()
    ctx = TradingContext(db, account, replay, lambda: replay.cursor)
    run = run_strategy_on(ctx, AllIn, {}, [SYMBOL])
    # The legacy replay (no hours) closes bar k at the end of its UTC day.
    for k in range(3):
        replay.cursor = datetime.fromtimestamp(int(at(DAYS[k], 0).timestamp()) + 86400, UTC)
        run.step()
    (trade,) = db.scalars(select(Trade).where(Trade.account_id == account.id)).all()
    assert trade.quantity == D(99)
    assert trade.entry_charges == D("141.16")
    assert account.cash == D("858.84")
    assert not [line for line in run.logs if "refused" in line.text]


# --- the job and the API -----------------------------------------------------------------------

BODY = {
    "strategy": "sma_crossover",
    "params": {"fast_period": 5, "slow_period": 10, "percent_of_cash": "50"},
    "symbols": ["AAPL"],
    "interval": "1d",
    "start_date": "2026-01-05",
    "end_date": "2026-02-27",
}


def test_a_backtest_is_queued_run_and_read_back(client, db_session: Session, fake_provider: FakeProvider):
    created = client.post("/api/backtests", json=BODY)
    assert created.status_code == 200, created.text
    summary = created.json()
    assert summary["status"] == "queued" and summary["progress"] == 0
    assert summary["params"]["slow_period"] == 10 and summary["params"]["percent_of_cash"] == "50"
    backtest_id = summary["id"]

    jobs.run_backtest_job(db_session, backtest_id, fake_provider, today=TODAY)

    detail = client.get(f"/api/backtests/{backtest_id}").json()
    assert detail["status"] == "done" and detail["progress"] == 100 and detail["error"] is None
    results = detail["results"]
    assert results["strategy_key"] == "sma_crossover" and results["interval"] == "1d"
    assert (
        results["bars"] == len(results["equity_curve"]) == 40
    )  # 5 Jan to 27 Feb 2026: eight weeks of weekdays
    assert isinstance(results["metrics"]["final_equity"], str)  # money travels as strings
    assert results["buy_and_hold"]["purchases"][0]["symbol"] == "AAPL"
    assert scratch_accounts(db_session) == []  # the scratch accounts are gone, the results stay

    assert [row["id"] for row in client.get("/api/backtests").json()] == [backtest_id]
    assert "results" not in client.get("/api/backtests").json()[0]

    assert client.delete(f"/api/backtests/{backtest_id}").status_code == 204
    assert client.get(f"/api/backtests/{backtest_id}").status_code == 404
    assert client.get("/api/backtests").json() == []


def test_a_bad_request_is_refused_before_it_is_queued(client):
    bad = client.post("/api/backtests", json={**BODY, "params": {"slow_period": 999}})
    assert bad.status_code == 400 and "Slow period must be at most 300" in bad.json()["detail"]
    wrong = client.post("/api/backtests", json={**BODY, "interval": "1h"})
    assert wrong.status_code == 400 and "built for 1d bars" in wrong.json()["detail"]
    future = client.post("/api/backtests", json={**BODY, "end_date": "2030-01-01"})
    assert future.status_code == 400 and "no data after today" in future.json()["detail"]
    assert client.get("/api/backtests").json() == []


def test_a_failed_backtest_says_why_and_a_running_one_cannot_be_deleted(
    client, db_session: Session, fake_provider: FakeProvider
):
    row_id = client.post("/api/backtests", json=BODY).json()["id"]
    # Run it as if a year had passed, so the 1d range is fine but the start predates nothing; use a
    # run date before the range to make the end date "in the future" and the job fail.
    jobs.run_backtest_job(db_session, row_id, fake_provider, today=date(2026, 1, 10))
    failed = client.get(f"/api/backtests/{row_id}").json()
    assert failed["status"] == "failed" and "no data after today" in failed["error"]
    assert failed["results"] is None
    assert scratch_accounts(db_session) == []

    row = db_session.get(Backtest, row_id)
    row.status = BacktestStatus.RUNNING
    db_session.commit()
    busy = client.delete(f"/api/backtests/{row_id}")
    assert busy.status_code == 409 and "is running" in busy.json()["detail"]


def test_a_restart_fails_runs_it_cut_off_and_sweeps_leftover_accounts(db_session: Session):
    row = Backtest(
        strategy_key="sma_crossover", params={}, symbols=["AAPL"], interval="1d", start_date=DAYS[0],
        end_date=DAYS[-1], starting_cash=D(1000), account_currency="USD", brokers={},
        status=BacktestStatus.RUNNING, progress=40, created_at=at(DAYS[0], 0),
    )  # fmt: skip
    db_session.add_all(
        [
            row,
            Account(
                currency="USD",
                cash=D(1),
                starting_cash=D(1),
                realized_pnl=D(0),
                margin_used=D(0),
                created_at=at(DAYS[0], 0),
                kind=AccountKind.BACKTEST,
            ),
        ]  # fmt: skip
    )
    db_session.commit()
    jobs._recover(db_session)
    assert db_session.get(Backtest, row.id).status == BacktestStatus.FAILED
    assert "restarted" in db_session.get(Backtest, row.id).error
    assert scratch_accounts(db_session) == []


def test_every_library_algorithm_has_a_backtestable_interval():
    assert {cls.interval for cls in LIBRARY.values()} <= {"1d", "1h"}


# --- saved algorithms ("my algorithms") ---------------------------------------------------


def test_a_saved_algorithm_is_created_read_changed_and_deleted(client):
    made = client.post(
        "/api/algos/mine",
        json={
            "name": "  My RSI ",
            "description": "Buys dips",
            "strategy": "rsi_reversion",
            "params": {"oversold": 35},
        },
    )
    assert made.status_code == 200, made.text
    row = made.json()
    assert row["name"] == "My RSI" and row["strategy"] == "rsi_reversion" and row["interval"] == "1d"
    assert row["params"]["oversold"] == 35  # the tuned value
    assert len(row["params"]) == len(LIBRARY["rsi_reversion"].PARAMETERS)  # and every default beside it

    algo_id = row["id"]
    assert client.get(f"/api/algos/mine/{algo_id}").json()["name"] == "My RSI"
    assert [r["id"] for r in client.get("/api/algos/mine").json()] == [algo_id]

    changed = client.put(
        f"/api/algos/mine/{algo_id}",
        json={"name": "Renamed", "strategy": "rsi_reversion", "params": {"oversold": 25}},
    )
    assert changed.status_code == 200 and changed.json()["params"]["oversold"] == 25
    assert changed.json()["name"] == "Renamed" and changed.json()["description"] == ""

    assert client.delete(f"/api/algos/mine/{algo_id}").status_code == 204
    assert client.get(f"/api/algos/mine/{algo_id}").status_code == 404
    gone = client.put(f"/api/algos/mine/{algo_id}", json={"name": "x", "strategy": "rsi_reversion"})
    assert gone.status_code == 404
    assert client.delete(f"/api/algos/mine/{algo_id}").status_code == 404
    assert client.get("/api/algos/mine").json() == []


def test_a_saved_algorithm_with_bad_settings_is_refused_in_the_servers_words(client):
    bad = client.post(
        "/api/algos/mine", json={"name": "x", "strategy": "sma_crossover", "params": {"slow_period": 999}}
    )
    assert bad.status_code == 400 and "Slow period must be at most 300" in bad.json()["detail"]
    unknown = client.post("/api/algos/mine", json={"name": "x", "strategy": "nope"})
    assert unknown.status_code == 400 and "There is no algorithm 'nope'" in unknown.json()["detail"]
    nameless = client.post("/api/algos/mine", json={"name": "   ", "strategy": "sma_crossover"})
    assert nameless.status_code == 422
    assert client.get("/api/algos/mine").json() == []


def test_a_backtest_can_start_from_a_saved_algorithm(client, db_session: Session, fake_provider):
    saved = client.post(
        "/api/algos/mine", json={"name": "Quick", "strategy": "sma_crossover", "params": {"slow_period": 12}}
    ).json()
    body = {k: v for k, v in BODY.items() if k not in ("strategy", "params")}

    made = client.post("/api/backtests", json={**body, "algo_id": saved["id"]})
    assert made.status_code == 200, made.text
    assert made.json()["strategy_key"] == "sma_crossover" and made.json()["params"]["slow_period"] == 12

    # Settings sent with the request win over the saved ones.
    over = client.post("/api/backtests", json={**body, "algo_id": saved["id"], "params": {"slow_period": 15}})
    assert over.json()["params"]["slow_period"] == 15

    jobs.run_backtest_job(db_session, made.json()["id"], fake_provider, today=TODAY)
    assert client.get(f"/api/backtests/{made.json()['id']}").json()["status"] == "done"

    missing = client.post("/api/backtests", json={**body, "algo_id": 999})
    assert missing.status_code == 404 and "no saved algorithm 999" in missing.json()["detail"]
    neither = client.post("/api/backtests", json=body)
    assert neither.status_code == 400 and "Say which algorithm" in neither.json()["detail"]


# --- warmup history is loaded before the window ---------------------------------------------------


class Warm5(hq.Strategy):
    """Needs 5 bars, buys 10% of cash once as soon as it may act."""

    name = "Warm5"
    interval = "1d"
    warmup_bars = 5

    def on_bar(self, ctx):
        if not ctx.open_trades(SYMBOL) and not ctx.position(SYMBOL).quantity:
            ctx.buy(SYMBOL, percent_of_cash=10)


WARM_DAYS = [date(2026, 1, d) for d in (19, 20, 21, 22, 23)]  # Mon-Fri before the window
WARM_OPENS = [100 + i for i in range(10)]  # window days 0..9 open at 100, 101, ... 109
WARM_CLOSES = [101 + i for i in range(10)]  # and close one rupee higher


@pytest.fixture
def warm_world() -> FixtureProvider:
    provider = FixtureProvider()
    # Five warmup sessions at 50, then the ten window sessions. A fill at 50 would be a trade
    # made before the window started.
    provider.set_daily(SYMBOL, WARM_DAYS + DAYS, [50] * 5 + WARM_OPENS, [50] * 5 + WARM_CLOSES)
    return provider


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
def test_warmup_bars_come_from_before_the_window_so_the_first_day_can_trade(
    db: Session, warm_world: FixtureProvider
):
    # Window 2-13 Feb, Warm5 needs 5 bars. The five sessions 19-23 Jan are loaded before the
    # window (the span is ceil(5 x 1.5) + 7 = 15 days back from 2 Feb, i.e. from 18 Jan), so they
    # are already closed when the first session opens. The strategy decides on them, and the order
    # fills at the first price after that: day 0's open, 100 (not 50, and not 5 days in).
    #   10% of 100,000 = 10,000 / 100 = 100 shares, no charges; cash 90,000.
    #   day 0 close 101: equity 90,000 + 100 x 101 = 100,100 (the curve's first point)
    #   day 9 close 110: equity 90,000 + 100 x 110 = 101,000
    results = backtest(db, warm_world, Warm5)

    (trade,) = results.trades
    assert trade.entry_at == open_of(DAYS[0])
    assert trade.entry_price == D(100) and trade.quantity == D(100)
    assert results.errors == []
    assert "loaded from before 02 Feb 2026" in results.notes[0]

    # Everything measured covers the window only: ten sessions, from day 0's close.
    assert results.bars == 10 and len(results.equity_curve) == 10
    assert results.equity_curve[0].at == close_of(DAYS[0])
    assert results.equity_curve[0].equity == D(100100)
    assert results.equity_curve[-1].equity == D(101000)
    assert results.first_bar == close_of(DAYS[0])
    assert results.metrics.final_equity == D(101000)
    # Buy-and-hold is bought on day 0's open too: 1,000 shares at 100 -> day 9's close 110 x 1,000.
    assert results.buy_and_hold.final_equity == D(110000)
    assert results.buy_and_hold.purchases[0].at == open_of(DAYS[0])


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
def test_nothing_fills_before_the_start_date(db: Session, warm_world: FixtureProvider):
    # Starting a day later (3 Feb) the warmup is 2 Feb's session plus the five from January, but
    # the window still opens on 3 Feb: no order, trade or curve point may be dated earlier.
    results = backtest(db, warm_world, Warm5, start=DAYS[1])
    begin = open_of(DAYS[1])
    assert all(o.filled_at >= begin for o in results.orders if o.filled_at is not None)
    assert [t.entry_at for t in results.trades] == [begin]
    assert results.trades[0].entry_price == D(101)  # day 1's open, not 50 or day 0's 100
    assert results.equity_curve[0].at == close_of(DAYS[1])
    assert results.bars == 9


WARM5_SOURCE = """from app.algos import hq


class Warm5Src(hq.Strategy):
    name = "Warm5 source"
    description = "Needs 5 bars, buys 10% of cash once as soon as it may act."
    markets = ("india",)
    interval = "1d"
    warmup_bars = 5
    PARAMETERS = {}

    def on_bar(self, ctx):
        for symbol in ctx.symbols:
            if not ctx.open_trades(symbol) and not ctx.position(symbol).quantity:
                ctx.buy(symbol, percent_of_cash=10)
"""


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
def test_uploaded_code_gets_its_declared_warmup_before_the_window(db: Session, warm_world: FixtureProvider):
    # Same world and hand figures as Warm5 above: the class literal `warmup_bars = 5` is read
    # without running the code, so the five January sessions are loaded before the window and the
    # first order fills at day 0's open, 100 (a strategy counted as 0 warmup would fill on day 1 at 101).
    #   10% of 100,000 = 10,000 / 100 = 100 shares; day 9 close 110 -> 90,000 + 11,000 = 101,000.
    results = backtest(db, warm_world, None, source=WARM5_SOURCE)
    (trade,) = results.trades
    assert trade.entry_at == open_of(DAYS[0])
    assert trade.entry_price == D(100) and trade.quantity == D(100)
    assert results.warmup_bars == 5 and results.errors == []
    assert "loaded from before 02 Feb 2026" in results.notes[0]
    assert results.metrics.final_equity == D(101000)


def test_a_three_month_window_runs_a_41_week_strategy(db: Session):
    # Slowking-shaped: weekly bars, 41 of warmup. The window 1 Dec 2025 - 1 Mar 2026 holds 13
    # Monday-stamped weekly bars (1, 8, 15, 22, 29 Dec; 5, 12, 19, 26 Jan; 2, 9, 16, 23 Feb), far
    # fewer than 41, so before this the run was refused. The warmup reaches back
    # ceil(41 x 7 x 1.2) + 14 = 359 days from 1 Dec 2025, which covers the 41 weeks.
    class Slow(hq.Strategy):
        name = "Slow"
        interval = "1wk"
        warmup_bars = 41

    results = run_backtest(
        db, FakeProvider(), strategy_cls=Slow, symbols=["AAPL"], interval="1wk",
        start=date(2025, 12, 1), end=date(2026, 3, 1), starting_cash=D(100000),
        account_currency="USD", today=TODAY,
    )  # fmt: skip
    assert results.bars == 13 and results.errors == []
    assert results.warmup_bars == 41
    assert "loaded from before 01 Dec 2025" in results.notes[0]
    assert scratch_accounts(db) == []
