"""QA audit of the backtester: buy-and-hold parity, charges, accounting, metrics, position size,
look-ahead, edge cases and determinism. Figures are worked by hand in the comments; when one
disagrees, recheck the arithmetic before blaming the code.

Fixtures use real NSE/NYSE working days (Mon 2 Feb to Fri 13 Feb 2026, no holidays on either).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.algos import hq
from app.market_data.base import Bar
from tests.test_backtest import (
    DAYS,
    SYMBOL,
    TODAY,
    FixtureProvider,
    at,
    backtest,
    close_of,
    open_of,
    scratch_accounts,
)

D = Decimal
# Fri 30 Jan 2026: the one warmup session before the window on both NSE and NYSE.
PRE = date(2026, 1, 30)
WIGGLE_OPENS = [100, 104, 103, 108, 107, 111, 110, 106, 109, 113]
WIGGLE_CLOSES = [103, 102, 107, 106, 110, 109, 105, 108, 112, 115]


class BuyAll(hq.Strategy):
    """Buys with 100% of cash at the first chance and never sells."""

    name = "Buy all"
    interval = "1d"
    warmup_bars = 1

    def on_bar(self, ctx):
        for symbol in ctx.symbols:
            if not ctx.open_trades(symbol) and not ctx.position(symbol).quantity:
                ctx.buy(symbol, percent_of_cash=100)


def world(*symbols: str) -> FixtureProvider:
    provider = FixtureProvider()
    for symbol in symbols:
        provider.set_daily(symbol, [PRE, *DAYS], [99, *WIGGLE_OPENS], [100, *WIGGLE_CLOSES])
    return provider


# --- 1. buy-and-hold parity --------------------------------------------------------------------


@pytest.mark.real_calendar
@pytest.mark.parametrize("symbol, first_open", [(SYMBOL, (3, 45)), ("AAPL", (14, 30))])
def test_buying_everything_at_once_matches_the_buy_and_hold_baseline(db: Session, symbol, first_open):
    # BuyAll has one warmup bar (30 Jan), so it decides on it before the first session opens and
    # its order fills at 2 Feb's open, the same price and moment at which the baseline buys. Both
    # use the same sizing (100% of cash, stepped down until value + charges fit), so every
    # figure must be equal: the only difference a real strategy would have is that it decides at
    # a close and fills a bar later (the baseline buys at the first open of the window).
    # Groww for RELIANCE.NS (INR), IBKR for AAPL (USD in an INR account, with the FX line).
    results = backtest(db, world(symbol, "USDINR=X"), BuyAll, symbols=(symbol,), starting_cash=D(1000000))
    hold = results.buy_and_hold
    (trade,) = results.trades
    (purchase,) = hold.purchases
    assert trade.entry_at == purchase.at == at(DAYS[0], *first_open)  # 09:15 IST / 09:30 EST
    assert trade.entry_price == purchase.price and trade.quantity == purchase.quantity
    assert trade.entry_charges == purchase.charges
    assert results.metrics.final_equity == hold.final_equity
    assert results.metrics.total_return_pct == hold.total_return_pct
    assert results.metrics.total_charges == hold.total_charges
    assert [p.equity for p in results.equity_curve] == [p.buy_hold_equity for p in results.equity_curve]
    assert scratch_accounts(db) == []


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
def test_without_history_before_the_window_the_strategy_trails_the_baseline_by_one_bar(db: Session):
    # The one allowed difference. With nothing before the start there is no warmup bar to decide
    # on, so BuyAll decides at day 0's close and fills at day 1's open (104), while the baseline
    # buys at day 0's open (100). 100,000 at no charges:
    #   baseline  1,000 shares at 100, worth 1,000 x 115 = 115,000 at the last close
    #   strategy  floor(100,000 / 104) = 961 shares = 99,944, cash 56; 56 + 961 x 115 = 110,571
    provider = FixtureProvider()
    provider.set_daily(SYMBOL, DAYS, WIGGLE_OPENS, WIGGLE_CLOSES)
    results = backtest(db, provider, BuyAll, symbols=(SYMBOL,))
    (trade,) = results.trades
    assert trade.entry_at == open_of(DAYS[1]) and trade.entry_price == D(104) and trade.quantity == D(961)
    (purchase,) = results.buy_and_hold.purchases
    assert purchase.at == open_of(DAYS[0]) and purchase.price == D(100) and purchase.quantity == D(1000)
    assert results.buy_and_hold.final_equity == D(115000)
    assert results.metrics.final_equity == D(110571)


# --- shared: capture the scratch accounts while they still exist ------------------------------


def run_and_peek(db: Session, provider, strategy, params=None, **kw):
    """Run a backtest and, from the `store` hook, copy what the scratch strategy account held
    when the run ended (it is deleted before `run_backtest` returns)."""
    from sqlalchemy import select

    from app.models import Account, AccountKind, Trade, TradeStatus

    seen = {}

    def peek(_results):
        account = db.scalars(
            select(Account).where(Account.kind == AccountKind.BACKTEST).order_by(Account.id)
        ).first()
        seen["cash"] = account.cash
        seen["realized"] = account.realized_pnl
        seen["margin"] = account.margin_used
        seen["open"] = [
            (t.symbol, t.direction, t.open_quantity, t.entry_price, t.entry_value)
            for t in db.scalars(
                select(Trade).where(Trade.account_id == account.id, Trade.status == TradeStatus.OPEN)
            )
        ]

    results = backtest(db, provider, strategy, params, store=peek, **kw)
    return results, seen


def falling_world(symbol: str = "AAPL") -> FixtureProvider:
    # Five January sessions at 100, then ten falling sessions that end with a bounce.
    pre = [date(2026, 1, d) for d in (26, 27, 28, 29, 30)]
    opens = [100] * 5 + [100, 98, 96, 94, 92, 90, 88, 86, 95, 99]
    closes = [100] * 5 + [99, 97, 95, 93, 91, 89, 87, 85, 96, 100]
    provider = FixtureProvider()
    provider.set_daily(symbol, [*pre, *DAYS], opens, closes)
    return provider


SHORT_PARAMS = {"lookback": 3, "exit_lookback": 2, "allow_shorts": True, "percent_of_cash": 50}


# --- 2. charges --------------------------------------------------------------------------------


class RoundTrips(hq.Strategy):
    """Buys 40% of cash on every even bar of each symbol and exits on every odd one."""

    name = "Round trips"
    interval = "1d"
    warmup_bars = 1

    def on_bar(self, ctx):
        self.n = getattr(self, "n", 0) + 1
        for symbol in ctx.symbols:
            trades = ctx.open_trades(symbol)
            if trades:
                for trade in trades:
                    ctx.exit(trade.id)
            elif self.n % 2 == 1:
                ctx.buy(symbol, percent_of_cash=40)


@pytest.mark.real_calendar
def test_every_fills_charges_equal_the_previews_and_the_totals_add_up(db: Session, monkeypatch):
    # A wrapper previews each order the engine is about to place (or each exit) at the same
    # moment and price, then checks the order that was filled carries the same charges and price.
    # RELIANCE.NS at Groww (INR) and AAPL at IBKR (USD in an INR account, FX line) are both traded
    # round trip, plus the baseline's two buys, so every fill path is covered.
    from app.trading import engine

    real_place, real_exit = engine.place_order, engine.exit_trade
    checked = []

    def snapshot(order):  # the scratch rows are deleted when the run ends
        return SimpleNamespace(
            status=order.status, charges_total=order.charges_total, fill_price=order.fill_price,
            quantity=order.quantity, charges=list(order.charges),
        )  # fmt: skip

    def place(ctx, **kw):
        preview = engine.preview_order(ctx, **kw)
        order = real_place(ctx, **kw)
        checked.append((preview, snapshot(order)))
        return order

    def leave(ctx, trade_id, quantity=None):
        preview = engine.preview_exit(ctx, trade_id, quantity)
        order = real_exit(ctx, trade_id, quantity)
        checked.append((preview, snapshot(order)))
        return order

    monkeypatch.setattr(engine, "place_order", place)
    monkeypatch.setattr(engine, "exit_trade", leave)
    provider = world(SYMBOL, "AAPL")
    provider.set_daily("USDINR=X", [PRE, *DAYS], [83.5] * 11, [83.5] * 11)
    results = backtest(db, provider, RoundTrips, symbols=(SYMBOL, "AAPL"), starting_cash=D(1000000))

    filled = [(p, o) for p, o in checked if o.status == "filled"]
    assert len(filled) >= 10 and {p.symbol for p, _ in filled} == {SYMBOL, "AAPL"}
    for preview, order in filled:
        assert order.charges_total == preview.charges_total > 0
        assert order.fill_price == preview.price and order.quantity == preview.quantity
        assert sum(D(c["amount"]) for c in order.charges) == order.charges_total
    # Totals: each trade's entry + exit lines, the orders' lines and the category split agree.
    m = results.metrics
    assert m.total_charges == sum(t.charges_total for t in results.trades)
    assert m.total_charges == sum(t.entry_charges + t.exit_charges for t in results.trades)
    assert m.total_charges == sum(o.charges_total for o in results.orders if o.status == "filled")
    assert sum(m.charges_by_category.values()) == m.total_charges
    # The baseline's charges are its two purchases' charges.
    assert results.buy_and_hold.total_charges == sum(p.charges for p in results.buy_and_hold.purchases)


# --- 3. the accounting identity ----------------------------------------------------------------


def check_identity(results, seen, start):
    """Equity = start + realized + unrealized, and = cash + market value of longs + short value."""
    m = results.metrics
    open_ = [t for t in results.trades if t.status == "open"]
    unrealized = sum((t.unrealized_pnl for t in open_), D(0))
    # The account books realized P&L (after charges) of closed trades and the financing paid on
    # open ones; an open trade's entry charges sit in its unrealized figure.
    realized = sum((t.realized_pnl for t in results.trades if t.status == "closed"), D(0))
    assert seen["realized"] == realized - sum((t.financing for t in open_), D(0))
    assert m.final_equity == start + seen["realized"] + unrealized
    assert results.equity_curve[-1].equity == m.final_equity
    for point in results.equity_curve:
        assert point.equity == point.cash + point.positions
    assert results.equity_curve[-1].cash == seen["cash"]


@pytest.mark.real_calendar
@pytest.mark.parametrize("end, state", [(DAYS[7], "open"), (DAYS[-1], "closed")])
def test_equity_is_start_plus_realized_plus_unrealized_with_a_short(db: Session, end, state):
    from app.algos.library.donchian_breakout import DonchianBreakout

    # Ten falling sessions on AAPL (USD account, IBKR). The 3-bar channel breaks down at the 3 Feb
    # close (97 < every low of 100 - 1 = 99), so the short fills at 4 Feb's open, 96; 50% of
    # 100,000 = 50,000 / 96 = 520.8 -> 520 shares, value 49,920; charges 2.60 brokerage + 1.03
    # regulatory = 3.63.
    #  open at 11 Feb's close (85): the short has gained 520 x (96 - 85) = 5,720, so its
    #   unrealized P&L is 5,720 - 3.63 = 5,716.37; borrow fees so far 28.71 are in realized.
    #   equity = 100,000 - 28.71 + 5,716.37 = 105,687.66 = cash 99,967.66 + short value 5,720.
    #  closed: covered at 13 Feb's open 99, a 520 x 3 = 1,560 loss; with 3.63 charges and 32.81
    #   financing realized is -1,599.04, equity 98,400.96.
    results, seen = run_and_peek(
        db,
        falling_world(),
        DonchianBreakout,
        SHORT_PARAMS,
        symbols=("AAPL",),
        account_currency="USD",
        end=end,
    )
    (trade,) = results.trades
    assert trade.direction == "short" and trade.status == state and trade.quantity == D(520)
    assert trade.entry_price == D(96) and trade.entry_charges == D("3.63")
    check_identity(results, seen, D(100000))
    if state == "open":
        assert trade.unrealized_pnl == D("5716.37") and trade.financing == D("28.71")
        assert results.metrics.final_equity == D("105687.66")
        assert results.equity_curve[-1].positions == D("5720.00")
    else:
        assert trade.exit_price == D(99) and trade.realized_pnl == D("-1599.04")
        assert results.metrics.final_equity == D("98400.96")


@pytest.mark.real_calendar
def test_equity_identity_with_an_open_long_in_rupees(db: Session):
    results, seen = run_and_peek(db, world(SYMBOL), BuyAll, symbols=(SYMBOL,))
    check_identity(results, seen, D(100000))


# --- 4 and 5. metrics by hand, and how much capital was in the market --------------------------

M_OPENS = [100, 102, 110, 108, 104, 100, 105, 115, 113, 120]
M_CLOSES = [101, 105, 109, 106, 100, 102, 112, 118, 114, 121]


class Scripted(hq.Strategy):
    """Buys or sells 100 shares at the fills listed. The first `on_bar` runs on the warmup bar,
    before the window, and its order fills at day 0's open; call j fills at day j-1's open."""

    name = "Scripted"
    interval = "1d"
    warmup_bars = 1
    ACTIONS = {1: "buy", 3: "sell", 4: "buy", 6: "sell", 7: "buy", 9: "sell", 10: "buy"}

    def on_start(self, ctx):
        self.calls = 0

    def on_bar(self, ctx):
        self.calls += 1
        action = self.ACTIONS.get(self.calls)
        if action == "buy":
            ctx.buy(SYMBOL, quantity=100)
        elif action == "sell":
            ctx.sell(SYMBOL, quantity=100)


def metrics_world() -> FixtureProvider:
    provider = FixtureProvider()
    provider.set_daily(SYMBOL, [PRE, *DAYS], [99, *M_OPENS], [100, *M_CLOSES])
    return provider


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
def test_metrics_by_hand_on_four_trades(db: Session):
    # 100 shares, no charges, 100,000 start. Fills at the opens (Mon 2 Feb is day 0):
    #   T1 buy d0 100, sell d2 110: +1,000    T2 buy d3 108, sell d5 100: -800
    #   T3 buy d6 105, sell d8 113: +800      T4 buy d9 120, still open; last close 121: +100
    # Equity at each close (cash + 100 x close):
    #   d0 90,000+10,100 = 100,100   d1 90,000+10,500 = 100,500   d2 flat 101,000
    #   d3 90,200+10,600 = 100,800   d4 90,200+10,000 = 100,200   d5 flat 100,200
    #   d6 89,700+11,200 = 100,900   d7 89,700+11,800 = 101,500   d8 flat 101,000
    #   d9 89,000+12,100 = 101,100
    results, _ = run_and_peek(db, metrics_world(), Scripted, symbols=(SYMBOL,))
    m = results.metrics
    assert [p.equity for p in results.equity_curve] == [
        D(x) for x in (100100, 100500, 101000, 100800, 100200, 100200, 100900, 101500, 101000, 101100)
    ]
    assert m.final_equity == D(101100) and m.total_return_pct == D("1.10")
    # Drawdown: peaks 100,100 / 100,500 / 101,000 / 101,500. Deepest is d4 and d5: 800 / 101,000
    # = 0.792%, then d8 500/101,500 = 0.49%.
    assert m.max_drawdown_pct == D("0.79")
    # d0 to d9 is 9 days; the run counts 12 calendar days (2 Feb 10:00 to 13 Feb 10:00 + 1).
    assert m.cagr_pct is None and "covers 12 days" in m.cagr_note
    assert m.sharpe is None and "has 10" in m.sharpe_note
    assert (m.trades_closed, m.trades_open) == (3, 1)
    assert m.win_rate_pct == D("66.67")  # 2 of 3
    assert m.average_win == D("900.00") and m.average_loss == D("-800.00")  # (1000+800)/2; -800
    assert m.profit_factor == D("2.25")  # 1,800 won / 800 lost
    assert m.gross_profit == D(1800) and m.total_charges == 0
    assert m.charges_pct_of_gross_profit == D("0.00")
    assert m.exposure_pct == D("70.00")  # invested at the closes of d0 d1 d3 d4 d6 d7 d9
    # Share of equity in the market at each close: 10100/100100 10500/100500 0 10600/100800
    # 10000/100200 0 11200/100900 11800/101500 0 12100/101100 = 10.0899 10.4478 0 10.5159 9.9800 0
    # 11.1001 11.6256 0 11.9684 -> sum 75.7277 / 10 = 7.57; the most is 11.97.
    assert m.avg_exposure_pct == D("7.57") and m.max_position_pct == D("11.97")
    (_, _, _, t4) = results.trades
    assert t4.status == "open" and t4.unrealized_pnl == D(100)


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
@pytest.mark.parametrize("losing", [True, False])
def test_a_profit_factor_with_no_wins_is_zero_and_with_no_losses_is_absent(db: Session, losing):
    class OneTrade(Scripted):
        ACTIONS = {1: "buy", 3: "sell"}  # buy d0's open, sell d2's open

    provider = metrics_world()
    if losing:
        # A falling stock: buy d0 at 100, sell d2 at 90 -> a single closed loser of 1,000.
        provider = FixtureProvider()
        opens = [99] + [100, 95, 90] + [90] * 7
        provider.set_daily(SYMBOL, [PRE, *DAYS], opens, [100] + [97, 92, 90] + [90] * 7)
    m = backtest(db, provider, OneTrade, symbols=(SYMBOL,)).metrics
    if losing:
        assert m.win_rate_pct == D("0.00") and m.average_win is None
        # Gross wins 0 over gross losses 1,000 is a factor of 0, not "n/a".
        assert m.profit_factor == D("0.00")
    else:
        assert m.profit_factor is None  # one win (110 vs 100), nothing lost: not infinite, not NaN


@pytest.mark.real_calendar
def test_charges_against_gross_profit_is_blank_while_the_only_trade_is_open(db: Session):
    # The owner's observation. Today the ratio counts closed trades only, so a run whose one
    # trade is still open has no gross profit and shows nothing, though it has paid entry charges
    # (total_charges is positive). Recommendation (not applied): count an open trade's unrealized
    # gross (unrealized + entry charges + financing) as gross profit while it is positive, and
    # divide the charges paid so far by that.
    results = backtest(db, world(SYMBOL), BuyAll, symbols=(SYMBOL,))
    (trade,) = results.trades
    assert trade.status == "open" and trade.unrealized_pnl > 0
    assert results.metrics.total_charges > 0
    assert results.metrics.gross_profit is None and results.metrics.charges_pct_of_gross_profit is None


@pytest.mark.real_calendar
@pytest.mark.parametrize("symbol, days_a_year", [("AAPL", 252), ("BTC-USD", 365)])
def test_sharpe_uses_252_days_a_year_except_for_crypto(db: Session, symbol, days_a_year):
    # 25 sessions from Tue 17 Feb 2026 (US shut on the 16th), so there are enough daily returns.
    # The same prices on a stock and on a coin differ only by the annualising factor, sqrt(252)
    # against sqrt(365); the expected value is recomputed here from the equity curve.
    import math
    import statistics
    from datetime import timedelta

    from app.algos.backtest import daily_equity

    first = date(2026, 2, 17)
    days = [first + timedelta(days=i) for i in range(40)]
    days = [d for d in days if symbol == "BTC-USD" or d.weekday() < 5][:25]
    closes = [100 + (i % 5) + i // 3 for i in range(len(days))]
    provider = FixtureProvider()
    provider.set_daily(symbol, [first - timedelta(days=4), *days], [99, *closes], [100, *closes])
    results = backtest(
        db, provider, BuyAll, symbols=(symbol,), start=days[0], end=days[-1], account_currency="USD",
        today=date(2026, 4, 30),
    )  # fmt: skip
    daily = daily_equity([(int(p.at.timestamp()), p.equity) for p in results.equity_curve])
    assert len(daily) == 25
    previous = [D(100000), *daily[:-1]]
    returns = [float(a / b - 1) for a, b in zip(daily, previous, strict=True)]
    expected = statistics.fmean(returns) / statistics.stdev(returns) * math.sqrt(days_a_year)
    assert results.metrics.sharpe == D(str(round(expected, 4))).quantize(D("0.01"))


# --- 6. no look-ahead, end to end --------------------------------------------------------------


class HourlyFixture(FixtureProvider):
    """AAPL hourly bars, seven a session from 14:30 UTC (09:30 New York) on the working days of
    26 Jan to 13 Feb 2026; bar k (counting from the first) opens at 100 + k and closes at 100.5 + k,
    so every bar has a price of its own and a fill can be traced to the bar it came from."""

    def get_history(self, symbol, interval, start, end):
        if (symbol, interval) != ("AAPL", "1h"):
            return super().get_history(symbol, interval, start, end)
        bars, k = [], 0
        for n in range(19):
            day = date(2026, 1, 26) + timedelta(days=n)
            if day.weekday() >= 5:
                continue
            for hour in range(7):
                open_ = D(100 + k)
                begin = (
                    int(datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC).timestamp()) + 3600 * hour
                )
                bars.append((day, Bar(begin, open_, open_ + 1, open_ - 1, open_ + D("0.5"), 100)))
                k += 1
        return [b for day, b in bars if start <= day <= end]


class HourlyBuyer(hq.Strategy):
    name = "Hourly buyer"
    interval = "1h"
    warmup_bars = 5
    seen = None

    def on_bar(self, ctx):
        if not ctx.open_trades("AAPL") and not ctx.position("AAPL").quantity:
            ctx.buy("AAPL", percent_of_cash=100)


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
def test_an_hourly_run_decides_on_warmup_and_fills_at_the_first_fresh_price(db: Session):
    # Window Mon 9 Feb 2026 (two sessions to the 10th); the 5 warmup bars are Friday 6 Feb's last
    # five. The strategy decides on them before the window, but at 14:30 the newest price is still
    # Friday's close (older than the session open), which the engine will not fill on. The first
    # price a person could trade at is 15:30, when the 14:30 bar has closed: bar 70 (the 71st bar
    # since 26 Jan: 10 sessions of 7), closing at 170.5. Bar 70 opened at 170 and Friday's last
    # bar closed at 169.5, so a fill at either of those would be a look-ahead or a pre-window trade.
    # The baseline buys at the same moment and price.
    provider = HourlyFixture()
    results = backtest(
        db, provider, HourlyBuyer, symbols=("AAPL",), interval="1h", start=date(2026, 2, 9),
        end=date(2026, 2, 10), account_currency="USD",
    )  # fmt: skip
    assert results.errors == [] and results.bars == 14
    (trade,) = results.trades
    assert trade.entry_at == at(date(2026, 2, 9), 15, 30) and trade.entry_price == D("170.5")
    (purchase,) = results.buy_and_hold.purchases
    assert (purchase.at, purchase.price) == (trade.entry_at, trade.entry_price)
    assert results.equity_curve[0].at == at(date(2026, 2, 9), 15, 30) == results.first_bar
    assert all(o.filled_at >= at(date(2026, 2, 9), 14, 30) for o in results.orders if o.filled_at)
    assert results.metrics.final_equity == results.buy_and_hold.final_equity


# --- 7. edge cases -----------------------------------------------------------------------------


class Idle(hq.Strategy):
    name = "Idle"
    interval = "1d"
    warmup_bars = 1


@pytest.mark.real_calendar
def test_an_empty_range_and_a_range_with_no_sessions_are_refused_in_a_sentence(db: Session):
    from app.market_data.fake import FakeProvider
    from app.market_data.history import HistoryRangeError

    # End before start.
    with pytest.raises(HistoryRangeError, match="after the end date"):
        backtest(db, world(SYMBOL), Idle, start=DAYS[3], end=DAYS[1])
    # Saturday 7 Feb to Sunday 8 Feb 2026: no session on any exchange.
    with pytest.raises(HistoryRangeError, match="market was shut"):
        backtest(db, FakeProvider(), Idle, symbols=("AAPL",), start=date(2026, 2, 7), end=date(2026, 2, 8))
    # A provider that has nothing for the days (a holiday week) is the same refusal.
    empty = FixtureProvider()
    empty.series[(SYMBOL, "1d")] = []
    with pytest.raises(HistoryRangeError, match="market was shut"):
        backtest(db, empty, Idle, start=date(2026, 2, 9), end=date(2026, 2, 13))
    assert scratch_accounts(db) == []


@pytest.mark.real_calendar
def test_a_one_day_range_runs_and_a_weekend_start_first_fills_on_monday(db: Session):
    # One session: one curve point, nothing to annualise, the buy at that day's open.
    one = backtest(db, world(SYMBOL), BuyAll, symbols=(SYMBOL,), start=DAYS[0], end=DAYS[0])
    assert one.bars == 1 and len(one.equity_curve) == 1
    assert one.trades[0].entry_at == open_of(DAYS[0])
    assert one.metrics.sharpe is None and one.metrics.cagr_pct is None
    assert one.metrics.max_drawdown_pct >= 0
    # Start on Saturday 7 Feb: Friday 6 Feb is warmup (closed history), the first fill is Monday's
    # open (9 Feb), not Friday's or Saturday's.
    weekend = backtest(db, world(SYMBOL), BuyAll, symbols=(SYMBOL,), start=date(2026, 2, 7), end=DAYS[-1])
    assert weekend.trades[0].entry_at == open_of(DAYS[5])  # 9 Feb
    assert weekend.trades[0].entry_price == D(WIGGLE_OPENS[5])
    assert weekend.equity_curve[0].at == close_of(DAYS[5])


@pytest.mark.real_calendar
def test_a_symbol_with_missing_sessions_still_runs_and_matches_the_baseline(db: Session):
    # 5 and 6 Feb missing from the data (a halt, say): no curve point for those days, nothing is
    # filled on them, and the strategy and the baseline still agree.
    gap = [d for d in DAYS if d not in (DAYS[3], DAYS[4])]
    keep = [i for i, d in enumerate(DAYS) if d in gap]
    provider = FixtureProvider()
    provider.set_daily(
        SYMBOL, [PRE, *gap], [99, *(WIGGLE_OPENS[i] for i in keep)], [100, *(WIGGLE_CLOSES[i] for i in keep)]
    )
    results = backtest(db, provider, BuyAll, symbols=(SYMBOL,), starting_cash=D(1000000))
    assert results.bars == 8 == len(results.equity_curve)
    assert {p.at.date() for p in results.equity_curve}.isdisjoint({DAYS[3], DAYS[4]})
    assert results.metrics.final_equity == results.buy_and_hold.final_equity


@pytest.mark.real_calendar
def test_two_calendars_are_each_traded_and_marked_on_their_own_sessions(db: Session):
    # RELIANCE.NS (open 03:45-10:00 UTC) and AAPL (14:30-21:00 UTC) over 10-18 Feb 2026. The US
    # is shut on Mon 16 Feb (Presidents' Day), India is open, so AAPL has no bar that day.
    class BuyBoth(hq.Strategy):
        name = "Buy both"
        interval = "1d"
        warmup_bars = 1

        def on_bar(self, ctx):
            for percent, symbol in ((50, SYMBOL), (100, "AAPL")):
                if not ctx.open_trades(symbol) and not ctx.position(symbol).quantity:
                    ctx.buy(symbol, percent_of_cash=percent)

    nse = [date(2026, 2, d) for d in (10, 11, 12, 13, 16, 17, 18)]
    nyse = [d for d in nse if d != date(2026, 2, 16)]
    provider = FixtureProvider()
    provider.set_daily(SYMBOL, [date(2026, 2, 9), *nse], [100] * 8, [101, 102, 103, 104, 105, 106, 107, 108])
    provider.set_daily("AAPL", [date(2026, 2, 9), *nyse], [100] * 7, [101, 102, 103, 104, 105, 106, 107])
    provider.set_daily("USDINR=X", [date(2026, 2, 9), *nse], [83.5] * 8, [83.5] * 8)
    results = backtest(
        db, provider, BuyBoth, symbols=(SYMBOL, "AAPL"), start=nse[0], end=nse[-1], starting_cash=D(1000000)
    )  # fmt: skip
    by_symbol = {t.symbol: t for t in results.trades}
    assert by_symbol[SYMBOL].entry_at == at(nse[0], 3, 45) and by_symbol["AAPL"].entry_at == at(
        nse[0], 14, 30
    )
    # Seven NSE closes (10:00 UTC) and six NYSE closes (21:00 UTC), in time order, none on the
    # US holiday at 21:00.
    stamps = [p.at for p in results.equity_curve]
    assert stamps == sorted(stamps) and len(stamps) == 13 and results.bars == 13
    assert at(date(2026, 2, 16), 21, 0) not in stamps and at(date(2026, 2, 16), 10, 0) in stamps
    # At the India close of 16 Feb Apple is marked at its last close, 13 Feb's 105 (closes run
    # 102 from 10 Feb), converted at 83.5: positions = RELIANCE x 106 + AAPL x 105 x 83.5.
    point = next(p for p in results.equity_curve if p.at == at(date(2026, 2, 16), 10, 0))
    q_r, q_a = by_symbol[SYMBOL].quantity, by_symbol["AAPL"].quantity
    expected = (q_r * 106).quantize(D("0.01")) + (q_a * 105 * D("83.5")).quantize(D("0.01"))
    assert point.positions == expected
    assert all(p.equity == p.cash + p.positions for p in results.equity_curve)


@pytest.mark.real_calendar
def test_a_crypto_weekend_is_a_trading_day(db: Session):
    # Daily bars for BTC-USD on Sat 7 and Sun 8 Feb: 10 consecutive days, a point for each, and
    # crypto annualises with 365 days.
    days = [date(2026, 2, 2) + timedelta(days=i) for i in range(10)]
    provider = FixtureProvider()
    provider.set_daily(
        "BTC-USD", [days[0] - timedelta(days=1), *days], [99, *WIGGLE_OPENS], [100, *WIGGLE_CLOSES]
    )
    results = backtest(
        db, provider, BuyAll, symbols=("BTC-USD",), start=days[0], end=days[-1], account_currency="USD"
    )  # fmt: skip
    assert results.bars == 10 and {p.at.weekday() for p in results.equity_curve} >= {5, 6}
    assert results.trades[0].entry_at == at(days[0], 0, 0)  # a crypto day opens at midnight UTC
    assert results.metrics.final_equity == results.buy_and_hold.final_equity


@pytest.mark.real_calendar
def test_a_strategy_that_raises_in_on_bar_is_recorded_and_the_run_finishes(db: Session):
    class Explodes(BuyAll):
        name = "Explodes"

        def on_bar(self, ctx):
            super().on_bar(ctx)  # the buy goes through first
            raise RuntimeError("boom")

    results = backtest(db, world(SYMBOL), Explodes, symbols=(SYMBOL,))
    # One error per call: the warmup step plus each of the ten closes.
    assert len(results.errors) == 11 and results.errors[0] == "on_bar: RuntimeError: boom"
    assert results.bars == 10 and len(results.trades) == 1  # the order queued before the raise filled
    assert any("on_bar raised RuntimeError: boom" in line.text for line in results.logs)
    assert scratch_accounts(db) == []


@pytest.mark.real_calendar
def test_a_strategy_that_never_trades_has_flat_honest_figures(db: Session):
    results = backtest(db, world(SYMBOL), Idle, symbols=(SYMBOL,))
    m = results.metrics
    assert results.trades == [] and results.orders == []
    assert m.final_equity == D(100000) and m.total_return_pct == 0 and m.max_drawdown_pct == 0
    assert (
        m.total_charges == 0 and m.exposure_pct == 0 and m.avg_exposure_pct == 0 and m.max_position_pct == 0
    )
    assert m.win_rate_pct is None and m.average_win is None and m.profit_factor is None
    assert m.gross_profit is None and m.charges_pct_of_gross_profit is None
    assert results.buy_and_hold.purchases and results.buy_and_hold.final_equity != D(100000)


@pytest.mark.real_calendar
def test_a_hundred_percent_buy_that_charges_would_overspend_is_skipped_in_plain_words(db: Session):
    # 100.2 rupees buys no share at 100: one share costs 100 plus about 0.24 of charges (0.1%
    # brokerage 0.10, STT 0.10, stamp 0.015, exchange 0.003, GST 0.019 ...), over the 100.2 on
    # hand. The strategy must be told it is a matter of cost, not that 1.0017 is "less than the
    # smallest step of 1".
    provider = FixtureProvider()
    provider.set_daily(SYMBOL, [PRE, *DAYS], [99, *([100] * 10)], [100, *([100] * 10)])
    results = backtest(db, provider, BuyAll, symbols=(SYMBOL,), starting_cash=D("100.2"))
    assert results.trades == [] and results.errors == []
    skipped = [line.text for line in results.logs if "Skipped buy" in line.text]
    assert skipped and "less than the smallest tradable step" not in skipped[0]
    assert "charges" in skipped[0]
    assert results.metrics.final_equity == D("100.2")


@pytest.mark.real_calendar
@pytest.mark.usefixtures("zero_costs")
@pytest.mark.parametrize(
    "price, cash, expected_quantity",
    [
        # 1,000 dollars at 0.00000123 buys 1,000 / 0.00000123 = 813,008,130.08130081...; the step is
        # 0.00000001, so the quantity is cut at the 8th decimal.
        ("0.00000123", "1000", "813008130.08130081"),
        # 1,000,000 dollars at 50,000,000 buys 0.02 exactly.
        ("50000000", "1000000", "0.02"),
    ],
)
def test_extreme_crypto_prices_size_to_the_step_and_value_exactly(
    db: Session, price, cash, expected_quantity
):
    days = [date(2026, 2, 2) + timedelta(days=i) for i in range(5)]
    px = D(price)
    provider = FixtureProvider()
    provider.set_daily("BTC-USD", [days[0] - timedelta(days=1), *days], [px] * 6, [px] * 6)
    results = backtest(
        db, provider, BuyAll, symbols=("BTC-USD",), start=days[0], end=days[-1], account_currency="USD",
        starting_cash=D(cash),
    )  # fmt: skip
    (trade,) = results.trades
    assert trade.quantity == D(expected_quantity)
    assert trade.quantity * px <= D(cash) and results.metrics.final_equity <= D(cash)
    assert results.metrics.final_equity > D(cash) - px  # less than one step of value is left over
    assert results.metrics.final_equity == results.buy_and_hold.final_equity


@pytest.mark.real_calendar
def test_warmup_that_reaches_past_the_history_limit_loads_what_exists_and_says_so(db: Session):
    from app.market_data.fake import FakeProvider
    from app.market_data.history import earliest_date

    # 1h bars reach back 729 days from 2 Mar 2026, i.e. to Sun 3 Mar 2024. A 20-bar strategy asked
    # to start on that day has no warmup before it at all; five sessions of seven hourly bars
    # (35 bars) still cover it, so the run goes ahead and its first order waits for 20 bars.
    class Twenty(HourlyBuyer):
        name = "Twenty"
        warmup_bars = 20

    first = earliest_date("1h", TODAY)
    assert first == date(2024, 3, 3)
    results = backtest(
        db, FakeProvider(), Twenty, symbols=("AAPL",), interval="1h", start=first,
        end=date(2024, 3, 8), account_currency="USD",
    )  # fmt: skip
    assert "Only 0 exist before 03 Mar 2024" in results.notes[0]
    assert results.errors == [] and results.trades
    # 20 bars at 7 a day: the 20th bar is the 6th of the 3rd session (6 Mar); an order decided at
    # its close cannot fill before then, and certainly not on the first day.
    assert results.trades[0].entry_at.date() >= date(2024, 3, 6)
    assert scratch_accounts(db) == []


@pytest.mark.real_calendar
def test_the_same_inputs_give_identical_results_three_times(db_session: Session):
    # Costs, shorts, two markets and an FX line in one run; the JSON of the results, which is
    # what is stored and served, must not change between runs (ids restart at 1 in each).
    import json

    from app.algos.library.donchian_breakout import DonchianBreakout

    provider = falling_world("AAPL")
    out = []
    for _ in range(3):
        results = backtest(
            db_session, provider, DonchianBreakout, SHORT_PARAMS, symbols=("AAPL",),
            account_currency="USD", end=DAYS[7],
        )  # fmt: skip
        out.append(json.dumps(results.model_dump(mode="json"), sort_keys=True))
    assert out[0] == out[1] == out[2]
    assert '"trades": [{"closed_how"' in out[0] or "trades" in out[0]


# --- 7. the job queue --------------------------------------------------------------------------

JOB_BODY = {
    "strategy": "sma_crossover",
    "params": {"fast_period": 5, "slow_period": 10, "percent_of_cash": "50"},
    "symbols": ["AAPL"],
    "interval": "1d",
    "start_date": "2026-01-05",
    "end_date": "2026-02-27",
}


def test_a_backtest_whose_row_vanishes_mid_run_leaves_nothing_behind(
    client, db_session: Session, fake_provider
):
    from sqlalchemy import delete

    from app.algos import jobs
    from app.models import Backtest

    row_id = client.post("/api/backtests", json=JOB_BODY).json()["id"]
    real = jobs.run_backtest

    def vanishing(db, provider, **kw):
        # Something removes the row after the job started (the API refuses while it runs, so this
        # is a stray delete, e.g. the owner's rows being cleared).
        report = kw["progress"]

        def progress(percent):
            if percent >= 50 and db.get(Backtest, row_id) is not None:
                db.execute(delete(Backtest).where(Backtest.id == row_id))
                db.commit()
            report(percent)

        return real(db, provider, **{**kw, "progress": progress})

    from pytest import MonkeyPatch

    with MonkeyPatch.context() as patch:
        patch.setattr(jobs, "run_backtest", vanishing)
        jobs.run_backtest_job(db_session, row_id, fake_provider, today=TODAY)  # must not raise
    assert db_session.get(Backtest, row_id) is None
    assert scratch_accounts(db_session) == []


def test_a_queued_backtest_deleted_before_it_starts_is_skipped_quietly(
    client, db_session: Session, fake_provider
):
    from app.algos import jobs

    row_id = client.post("/api/backtests", json=JOB_BODY).json()["id"]
    assert jobs._next_queued(db_session) == row_id  # the worker has picked it ...
    assert client.delete(f"/api/backtests/{row_id}").status_code == 204  # ... and the owner deletes it
    jobs.run_backtest_job(db_session, row_id, fake_provider, today=TODAY)  # no exception for the loop to log
    assert jobs._next_queued(db_session) is None and scratch_accounts(db_session) == []


def test_two_queued_backtests_run_in_order_and_do_not_disturb_each_other(
    client, db_session: Session, fake_provider
):
    from app.algos import jobs

    first = client.post("/api/backtests", json=JOB_BODY).json()["id"]
    second = client.post("/api/backtests", json={**JOB_BODY, "symbols": ["MSFT"]}).json()["id"]
    order = []
    while (next_id := jobs._next_queued(db_session)) is not None:
        order.append(next_id)
        jobs.run_backtest_job(db_session, next_id, fake_provider, today=TODAY)
    assert order == [first, second]
    one, two = (client.get(f"/api/backtests/{i}").json() for i in (first, second))
    assert one["status"] == two["status"] == "done"
    assert one["results"]["instruments"][0]["symbol"] == "AAPL"
    assert two["results"]["instruments"][0]["symbol"] == "MSFT"
    # A solo run of the second gives the same results as when it ran after the first.
    third = client.post("/api/backtests", json={**JOB_BODY, "symbols": ["MSFT"]}).json()["id"]
    jobs.run_backtest_job(db_session, third, fake_provider, today=TODAY)
    assert client.get(f"/api/backtests/{third}").json()["results"] == two["results"]
    assert scratch_accounts(db_session) == []


def test_two_backtests_running_in_two_threads_both_finish_cleanly(tmp_path, fake_provider):
    import threading

    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    from app.algos import jobs
    from app.db import Base
    from app.models import Backtest, BacktestStatus

    engine = create_engine(
        f"sqlite:///{tmp_path / 'two.db'}", connect_args={"check_same_thread": False, "timeout": 30}
    )

    @event.listens_for(engine, "connect")
    def _wal(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    ids = []
    with make() as db:
        for symbol in ("AAPL", "MSFT"):
            row = Backtest(
                strategy_key="sma_crossover",
                params={"fast_period": 5, "slow_period": 10, "percent_of_cash": "50"},
                symbols=[symbol], interval="1d", start_date=date(2026, 1, 5), end_date=date(2026, 2, 27),
                starting_cash=D(100000), account_currency="USD", brokers={}, status=BacktestStatus.QUEUED,
                progress=0, created_at=at(DAYS[0], 0),
            )  # fmt: skip
            db.add(row)
            db.commit()
            ids.append(row.id)
    failures = []

    def work(row_id):
        try:
            with make() as db:
                jobs.run_backtest_job(db, row_id, fake_provider, today=TODAY)
        except Exception as why:  # noqa: BLE001
            failures.append(repr(why))

    threads = [threading.Thread(target=work, args=(i,)) for i in ids]
    [t.start() for t in threads]
    [t.join(timeout=120) for t in threads]
    assert failures == []
    with make() as db:
        rows = [db.get(Backtest, i) for i in ids]
        assert [r.status for r in rows] == [BacktestStatus.DONE, BacktestStatus.DONE], [r.error for r in rows]
        assert scratch_accounts(db) == []


class HourlyIdle(hq.Strategy):
    name = "Hourly idle"
    interval = "1h"
    warmup_bars = 1


@pytest.mark.real_calendar
def test_the_baseline_buys_a_stock_that_opens_hours_after_a_coin_it_shares_a_run_with(db: Session):
    from app.market_data.fake import FakeProvider

    # Hourly BTC-USD (a visit every hour from midnight UTC) next to AAPL, which only opens at
    # 14:30 UTC: the baseline retries each visit until its order fills, so it must not give up on
    # AAPL after the 14 coin-only visits that come first on Monday 9 Feb.
    results = backtest(
        db, FakeProvider(), HourlyIdle, symbols=("BTC-USD", "AAPL"), interval="1h",
        start=date(2026, 2, 9), end=date(2026, 2, 9), account_currency="USD",
    )  # fmt: skip
    bought = {p.symbol: p.at for p in results.buy_and_hold.purchases}
    assert set(bought) == {"BTC-USD", "AAPL"}
    assert bought["AAPL"].date() == date(2026, 2, 9) and bought["AAPL"].hour >= 14
