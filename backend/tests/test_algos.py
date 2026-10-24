"""The strategy framework: the `hq` API, parameter checking, the per-bar runner and the five
predefined algorithms, all through the real engine on bars made up for the test.

Prices are chosen so the arithmetic is easy to follow. The tests trade for free (`zero_costs`):
they are about when orders are sent and at what price, not about charges. A bar's close is known
when the bar ends, so the cursor sits at the end of bar i when `on_bar` sees bar i.
"""

import ast
import pathlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algos import hq
from app.algos.api import MAX_LOG_CHARS, MAX_LOG_LINES, ParameterError, validate_params
from app.algos.library import LIBRARY
from app.algos.library.crypto_volatility_breakout import CryptoVolatilityBreakout
from app.algos.library.donchian_breakout import DonchianBreakout
from app.algos.library.sma_crossover import SmaCrossover
from app.algos.runner import StrategyRunError, round_down_to_step, run_strategy_on
from app.market_data.base import Bar, Instrument
from app.market_data.fake import FakeProvider
from app.market_data.replay import ReplayProvider, bar_span
from app.models import Account, AccountKind, Order, OrderStatus, Trade, TradeStatus
from app.trading.context import TradingContext
from app.trading.markets import MARKETS

D = Decimal
pytestmark = pytest.mark.usefixtures("zero_costs")

START = date(2026, 1, 5)
HOUR0 = int(datetime(2026, 1, 5, tzinfo=UTC).timestamp())


class World:
    """Bars loaded into a replay, an account, and a way to play the bars one at a time."""

    def __init__(self, db: Session, closes: dict[str, list], interval="1d", cash="100000", currency="USD"):
        fake = FakeProvider()
        instruments = {}
        for symbol in closes:
            q = fake.get_quote(symbol)
            instruments[symbol] = Instrument(symbol, q.name, q.exchange, q.type, q.currency)
        self.interval = interval
        self.replay = ReplayProvider(datetime(2026, 1, 1, tzinfo=UTC), instruments=instruments)
        self.ends: list[int] = []
        for symbol, series in closes.items():
            bars = [self._bar(i, series, interval) for i in range(len(series))]
            self.replay.load(symbol, interval, bars)
            self.ends = [bar_span(b, interval)[1] for b in bars]
        account = Account(
            currency=currency, cash=D(cash), starting_cash=D(cash), realized_pnl=D(0),
            margin_used=D(0), created_at=datetime(2025, 1, 1, tzinfo=UTC), kind=AccountKind.ALGO,
        )  # fmt: skip
        db.add(account)
        db.commit()
        self.db, self.account = db, account
        self.ctx = TradingContext(db, account, self.replay, lambda: self.replay.cursor)

    @staticmethod
    def _bar(i: int, series: list, interval: str) -> Bar:
        close = D(str(series[i]))
        open_ = D(str(series[i - 1])) if i else close
        when = (START + timedelta(days=i)).isoformat() if interval == "1d" else HOUR0 + 3600 * i
        return Bar(when, open_, max(open_, close) + 1, min(open_, close) - 1, close, 1000)

    def close_of(self, bar: int) -> datetime:
        return datetime.fromtimestamp(self.ends[bar], UTC)

    def play(self, run, upto: int | None = None, first: int = 0) -> None:
        for i in range(first, len(self.ends) if upto is None else upto + 1):
            self.replay.cursor = self.close_of(i)
            run.step()

    def trades(self) -> list[Trade]:
        return list(
            self.db.scalars(select(Trade).where(Trade.account_id == self.account.id).order_by(Trade.id))
        )

    def orders(self) -> list[Order]:
        return list(
            self.db.scalars(select(Order).where(Order.account_id == self.account.id).order_by(Order.id))
        )


def run_algo(db, algo, params, closes, symbols=None, interval=None, **world_args):
    world = World(db, closes, interval or algo.interval, **world_args)
    run = run_strategy_on(world.ctx, algo, params, symbols or list(closes))
    world.play(run)
    return world, run


# --- indicators through the facade, parameters -----------------------------------------


def test_validate_params_fills_defaults_and_coerces():
    got = validate_params(SmaCrossover, {"fast_period": "5", "slow_period": 20.0, "percent_of_cash": "25.5"})
    assert got == {"fast_period": 5, "slow_period": 20, "percent_of_cash": D("25.5")}
    assert validate_params(SmaCrossover, {}) == {
        "fast_period": 10,
        "slow_period": 30,
        "percent_of_cash": D("50"),
    }


def test_bad_parameters_are_refused_with_one_sentence_each():
    with pytest.raises(ParameterError) as caught:
        validate_params(
            SmaCrossover,
            {"fast_period": "ten", "slow_period": 1000, "percent_of_cash": 0, "colour": "red"},
        )
    problems = caught.value.problems
    assert len(problems) == 4
    assert "Fast period must be a whole number, not 'ten'." in problems
    assert "Slow period must be at most 300, not 1000." in problems
    assert "Cash per entry (%) must be at least 1, not 0." in problems
    assert any(p.startswith("'colour' is not a setting of SMA crossover") for p in problems)
    assert str(caught.value) == " ".join(problems)


def test_settings_that_only_fail_together_are_refused():
    with pytest.raises(ParameterError, match="Fast period must be smaller than Slow period"):
        validate_params(SmaCrossover, {"fast_period": 30, "slow_period": 30})
    with pytest.raises(ParameterError, match="Exit lookback must not be longer"):
        validate_params(DonchianBreakout, {"lookback": 5, "exit_lookback": 9})


def test_booleans_and_choices_are_checked():
    assert validate_params(DonchianBreakout, {"allow_shorts": "true"})["allow_shorts"] is True
    with pytest.raises(ParameterError, match="Allow shorts must be true or false"):
        validate_params(DonchianBreakout, {"allow_shorts": "maybe"})
    with pytest.raises(ParameterError, match="Entry lookback must be a whole number"):
        validate_params(DonchianBreakout, {"lookback": True})

    class Picky(hq.Strategy):
        PARAMETERS = {"mode": hq.Param("choice", "fast", choices=("fast", "slow"))}

    with pytest.raises(ParameterError, match="Mode must be one of fast, slow, not 'medium'"):
        validate_params(Picky, {"mode": "medium"})


def test_a_badly_declared_param_fails_when_the_class_is_written():
    with pytest.raises(ValueError, match="above the maximum"):
        hq.Param("int", 50, min=1, max=10)
    with pytest.raises(ValueError, match="kind must be one of"):
        hq.Param("text", "x")
    with pytest.raises(ValueError, match="needs choices"):
        hq.Param("choice", "a")


def test_run_strategy_refuses_bad_params_and_missing_data(db: Session):
    world = World(db, {"AAPL": [100] * 5})
    with pytest.raises(ParameterError):
        run_strategy_on(world.ctx, SmaCrossover, {"fast_period": 99, "slow_period": 5}, ["AAPL"])
    with pytest.raises(StrategyRunError, match="No 1h bars for AAPL"):
        run_strategy_on(world.ctx, CryptoVolatilityBreakout, {}, ["AAPL"])
    with pytest.raises(StrategyRunError, match="at least one symbol"):
        run_strategy_on(world.ctx, SmaCrossover, {}, [])


# --- the runner: next-bar fills, refusals, rounding --------------------------------------


class BuyOnce(hq.Strategy):
    name = "Buy once"
    warmup_bars = 2

    def on_bar(self, ctx):
        if not ctx.open_trades("AAPL") and not ctx.position("AAPL").quantity:
            ctx.buy("AAPL", quantity=10)


def test_an_order_fills_at_the_next_bar_not_the_bar_it_was_decided_on(db: Session):
    # Closes 100, 110, 120, 130. Warmup is 2 bars, so on_bar first runs when bar 1 (close 110) has
    # closed and decides to buy. The order must not fill at 110; it fills at bar 2's close, 120.
    world = World(db, {"AAPL": [100, 110, 120, 130]})
    run = run_strategy_on(world.ctx, BuyOnce, {}, ["AAPL"])
    world.play(run, upto=1)
    assert world.orders() == [] and world.trades() == []  # decided, not yet sent
    world.play(run, upto=2, first=2)
    (trade,) = world.trades()
    assert trade.entry_price == D("120")
    assert trade.opened_at == world.close_of(2)
    assert world.account.cash == D("100000") - D("1200")


def test_on_bar_does_not_run_again_without_a_new_bar(db: Session):
    calls = []

    class Counting(hq.Strategy):
        def on_bar(self, ctx):
            calls.append(ctx.now)

    world = World(db, {"AAPL": [100, 101, 102]})
    run = run_strategy_on(world.ctx, Counting, {}, ["AAPL"])
    world.replay.cursor = world.close_of(1)
    run.step()
    run.step()  # the clock moved on a gap in the data, but no new bar closed
    assert calls == [world.close_of(1)]


def test_the_strategy_never_sees_a_bar_that_has_not_closed(db: Session):
    seen = []

    class Peeker(hq.Strategy):
        def on_bar(self, ctx):
            seen.append((len(ctx.bars("AAPL", 100)), ctx.price("AAPL")))

    world = World(db, {"AAPL": [100, 110, 120, 130]})
    run = run_strategy_on(world.ctx, Peeker, {}, ["AAPL"])
    world.play(run)
    assert seen == [(1, D("100")), (2, D("110")), (3, D("120")), (4, D("130"))]


def test_a_refused_order_is_logged_not_raised(db: Session):
    class Spender(hq.Strategy):
        def on_bar(self, ctx):
            result = ctx.buy("AAPL", quantity=5)
            assert result.accepted  # it is queued; the engine's verdict comes with the fill

    # 5 shares at 100 cost 500 but the account holds 10.
    world = World(db, {"AAPL": [100, 100, 100]}, cash="10")
    run = run_strategy_on(world.ctx, Spender, {}, ["AAPL"])
    world.play(run)
    assert run.errors == []
    assert world.trades() == [] and world.orders() == []
    refusals = [line.text for line in run.logs if line.text.startswith("Order refused (buy AAPL)")]
    assert refusals and "cash" in refusals[0].lower()


def test_quantity_rounds_down_to_the_market_step():
    assert round_down_to_step(D("7.9"), D(1)) == 7
    assert round_down_to_step(D("0.123456789"), D("0.00000001")) == D("0.12345678")
    assert round_down_to_step(D("0.4"), D(1)) == 0
    assert round_down_to_step(D("10"), D("0.0001")) == 10


def test_order_sizes_round_down_and_a_zero_size_is_skipped_with_a_log_line(db: Session):
    class Sizer(hq.Strategy):
        def on_bar(self, ctx):
            if ctx.now == self.when:
                ctx.buy("RELIANCE.NS", percent_of_cash=50)  # 50,000 / 333 = 150.15 -> 150
                ctx.buy("RELIANCE.NS", quantity="7.9")  # -> 7
                ctx.buy("RELIANCE.NS", quantity="0.5")  # rounds to 0: skipped

    world = World(db, {"RELIANCE.NS": [333, 333, 333]}, cash="100000", currency="INR")
    Sizer.when = world.close_of(0)
    run = run_strategy_on(world.ctx, Sizer, {}, ["RELIANCE.NS"])
    world.play(run)
    assert [t.open_quantity for t in world.trades()] == [D(150), D(7)]
    skipped = [line.text for line in run.logs if "Skipped buy RELIANCE.NS" in line.text]
    assert len(skipped) == 1 and "smallest tradable step" in skipped[0]


def test_sell_never_opens_a_short_and_short_does_not_close_a_long(db: Session):
    class Muddled(hq.Strategy):
        def on_bar(self, ctx):
            if ctx.now == self.t0:
                ctx.sell("AAPL")  # nothing held
                ctx.buy("AAPL", quantity=10)
            if ctx.now == self.t1:
                ctx.short("AAPL", quantity=5)  # a long is open
                ctx.sell("AAPL", quantity=100)  # more than held: capped at 10

    world = World(db, {"AAPL": [100, 100, 100, 100]})
    Muddled.t0, Muddled.t1 = world.close_of(0), world.close_of(1)
    run = run_strategy_on(world.ctx, Muddled, {}, ["AAPL"])
    world.play(run)
    (trade,) = world.trades()
    assert trade.status == TradeStatus.CLOSED and trade.quantity == 10
    texts = [line.text for line in run.logs]
    assert any("Skipped sell AAPL: no long position" in t for t in texts)
    assert any("Skipped short AAPL: a long position is open" in t for t in texts)


def test_bad_order_arguments_are_refused_at_the_call(db: Session):
    results = []

    class Careless(hq.Strategy):
        def on_bar(self, ctx):
            results.extend([
                ctx.buy("AAPL"),
                ctx.buy("AAPL", quantity=1, percent_of_cash=10),
                ctx.buy("AAPL", quantity=-1),
                ctx.buy("AAPL", percent_of_cash=101),
                ctx.buy("MSFT", quantity=1),
                ctx.buy("AAPL", quantity="lots"),
            ])  # fmt: skip

    world = World(db, {"AAPL": [100, 100]})
    run = run_strategy_on(world.ctx, Careless, {}, ["AAPL"])
    world.play(run, upto=0)
    assert [r.accepted for r in results] == [False] * 6
    assert "not one of this run's symbols" in results[4].message
    assert run.errors == []


def test_a_crash_in_on_bar_is_recorded_and_the_run_goes_on(db: Session):
    class Broken(hq.Strategy):
        def on_bar(self, ctx):
            raise RuntimeError("boom")

    world = World(db, {"AAPL": [100, 101, 102]})
    run = run_strategy_on(world.ctx, Broken, {}, ["AAPL"])
    world.play(run)
    assert len(run.errors) == 3 and run.errors[0] == "on_bar: RuntimeError: boom"


def test_log_lines_are_capped_in_length_and_count(db: Session):
    class Chatty(hq.Strategy):
        def on_bar(self, ctx):
            ctx.log("x" * 1000)
            for _ in range(MAX_LOG_LINES + 50):
                ctx.log("again")

    world = World(db, {"AAPL": [100, 101]})
    run = run_strategy_on(world.ctx, Chatty, {}, ["AAPL"])
    world.play(run, upto=0)
    assert len(run.logs[0].text) == MAX_LOG_CHARS and run.logs[0].text.endswith("...")
    assert len(run.logs) == MAX_LOG_LINES + 1 and "Log full" in run.logs[-1].text


def test_on_trade_closed_reports_the_closed_trade(db: Session):
    closed = []

    class RoundTrip(hq.Strategy):
        def on_bar(self, ctx):
            if ctx.now == self.t_buy:
                ctx.buy("AAPL", quantity=10)
            if ctx.now == self.t_sell:
                ctx.sell("AAPL")

        def on_trade_closed(self, ctx, trade):
            closed.append(trade)

    world = World(db, {"AAPL": [100, 100, 120, 130, 140]})
    RoundTrip.t_buy, RoundTrip.t_sell = world.close_of(0), world.close_of(2)
    run = run_strategy_on(world.ctx, RoundTrip, {}, ["AAPL"])
    world.play(run)
    # Bought at bar 1's close (100), sold at bar 3's close (130): 10 x 30 = 300.
    (trade,) = closed
    assert (trade.status, trade.closed_how, trade.realized_pnl) == ("closed", "sell", D("300"))
    assert trade.entry_price == D("100") and run.errors == []


def test_a_stop_set_through_the_facade_fires_in_the_tick(db: Session):
    closed = []

    class Guarded(hq.Strategy):
        def on_bar(self, ctx):
            for t in ctx.open_trades("AAPL"):
                if t.stop_price is None:
                    ctx.set_protection(t.id, stop=D("95"))
            if ctx.now == self.t0:
                ctx.buy("AAPL", quantity=10)

        def on_trade_closed(self, ctx, trade):
            closed.append(trade)

    world = World(db, {"AAPL": [100, 100, 100, 90, 90]})
    Guarded.t0 = world.close_of(0)
    run = run_strategy_on(world.ctx, Guarded, {}, ["AAPL"])
    world.play(run)
    # Bought at bar 1 (100), stop 95 set that bar, bar 3 closes at 90: the stop fires at 90.
    (trade,) = closed
    assert trade.closed_how == "stop_loss" and trade.realized_pnl == D("-100")


def test_the_facade_does_not_hand_out_the_engine(db: Session):
    world = World(db, {"AAPL": [100, 101]})
    run = run_strategy_on(world.ctx, BuyOnce, {}, ["AAPL"])
    facade = run.api
    assert not hasattr(facade, "__dict__")  # slots only: nothing to stash or reach through
    for name in ("db", "account", "provider", "ctx", "engine", "session"):
        assert not hasattr(facade, name)
    assert set(hq.__all__) == {
        "Bar",
        "OrderResult",
        "Param",
        "Position",
        "Strategy",
        "StrategyContext",
        "TradeInfo",
    }
    assert isinstance(facade.bars("AAPL", 5), tuple)


# --- the SMA crossover, worked by hand ---------------------------------------------------

SMA_CLOSES = [100, 100, 100, 90, 80, 90, 110, 125, 120, 100, 80, 70]


def test_sma_crossover_trades_on_the_bars_worked_out_by_hand(db: Session):
    # fast 2, slow 3, 50% of cash, 100,000 USD. Averages at each close (fast / slow):
    #   bar 2  100 / 100     bar 3   95 / 96.67    bar 4  85 / 90      bar 5  85 / 86.67
    #   bar 6  100 / 93.33   bar 7 117.5 / 108.33  bar 8 122.5 / 118.33
    #   bar 9  110 / 115     bar 10  90 / 100      bar 11 75 / 83.33
    # Bar 3 crosses down but nothing is held. Bar 6 is the first cross up (85 <= 86.67, then
    # 100 > 93.33): buy, filled at bar 7's close, 125. 50,000 / 125 = 400 shares. Bar 9 crosses
    # down (122.5 > 118.33, then 110 < 115): sell, filled at bar 10's close, 80.
    # Result: 400 x (80 - 125) = -18,000; cash 100,000 - 50,000 + 32,000 = 82,000.
    world, run = run_algo(db, SmaCrossover, {"fast_period": 2, "slow_period": 3}, {"AAPL": SMA_CLOSES})
    (trade,) = world.trades()
    assert (trade.entry_price, trade.quantity) == (D("125"), D("400"))
    assert trade.opened_at == world.close_of(7)
    assert trade.closed_at == world.close_of(10) and trade.closed_how == "sell"
    assert trade.realized_pnl == D("-18000")
    assert world.account.cash == D("82000")
    assert [o.fill_price for o in world.orders()] == [D("125"), D("80")]
    assert run.errors == []


# --- every predefined algorithm places an order ------------------------------------------


def test_the_library_is_five_honest_algorithms():
    assert list(LIBRARY) == [
        "sma_crossover", "rsi_reversion", "donchian_breakout", "bollinger_reversion",
        "crypto_volatility_breakout",
    ]  # fmt: skip
    valid_markets = {"india", "international", "crypto"} | set(MARKETS)
    for key, algo in LIBRARY.items():
        assert issubclass(algo, hq.Strategy) and algo.name and len(algo.description) > 100, key
        assert algo.markets and set(algo.markets) <= valid_markets, key
        assert validate_params(algo, {}), key  # the defaults are themselves valid


def test_rsi_reversion_buys_the_dip_and_protects_it(db: Session):
    closes = [100, 102, 104, 106, 108, 100, 92, 84, 84, 84, 84]
    world, run = run_algo(
        db, LIBRARY["rsi_reversion"], {"period": 3, "oversold": 30, "exit_level": 60}, {"AAPL": closes}
    )
    trade = world.trades()[0]
    assert trade.direction == "long" and trade.stop_price is not None
    assert trade.stop_price == D(str(trade.entry_price)) * D("0.95")
    assert run.errors == []


def test_donchian_buys_a_breakout_and_exits_on_the_way_down(db: Session):
    # Lookback 3: bar 4 (close 108) is above the highest high of bars 1-3 (101), so it buys at
    # bar 5's close (112). Exit lookback 2 lows: bar 8 (close 90) is below them, sells at bar 9.
    closes = [100, 100, 100, 100, 108, 112, 115, 112, 90, 85, 85]
    params = {"lookback": 3, "exit_lookback": 2}
    world, run = run_algo(db, LIBRARY["donchian_breakout"], params, {"AAPL": closes})
    (trade,) = world.trades()
    assert trade.direction == "long" and trade.entry_price == D("112")
    assert trade.status == TradeStatus.CLOSED and trade.closed_at == world.close_of(9)


FALLING = [100, 100, 100, 100, 92, 88, 85, 90, 99, 110, 110]


def test_donchian_shorts_only_when_allowed(db: Session):
    params = {"lookback": 3, "exit_lookback": 2, "allow_shorts": True}
    world, run = run_algo(db, DonchianBreakout, params, {"AAPL": FALLING})
    short, long = world.trades()
    # Bar 4 (close 92) is below the lowest low of bars 1-3 (99): short, filled at bar 5's close, 88.
    # Bar 8 (close 99) is above the highs of bars 6-7 (89, 91): cover, filled at bar 9's close, 110.
    # That same bar 9 (close 110) beats the highs of bars 6-8 (100): a long, filled at bar 10, 110.
    assert short.direction == "short" and short.entry_price == D("88")
    assert short.status == TradeStatus.CLOSED and short.closed_at == world.close_of(9)
    assert long.direction == "long" and long.entry_price == D("110")

    world, run = run_algo(db, DonchianBreakout, {**params, "allow_shorts": False}, {"AAPL": FALLING})
    assert [t.direction for t in world.trades()] == ["long"]  # the breakdown is left alone


def test_donchian_short_refused_by_a_market_without_shorting_is_logged(db: Session):
    # The engine decides where shorting exists; the strategy just asks.
    params = {"lookback": 3, "exit_lookback": 2, "allow_shorts": True}
    world, run = run_algo(db, DonchianBreakout, params, {"VOD.L": FALLING}, currency="GBP")
    assert [t.direction for t in world.trades()] == ["long"] and run.errors == []  # the later breakout
    assert any(line.text.startswith("Order refused (short VOD.L)") for line in run.logs)


def test_bollinger_reversion_buys_below_the_band_with_the_mid_as_target(db: Session):
    # Period 5, k 1.5. Bars 0-4 close 100. Bar 5 closes 90: window 100,100,100,100,90 has mean 98
    # and population deviation 4, so the lower band is 98 - 1.5 x 4 = 92 and 90 is below it: buy,
    # filled at bar 6's close, 94. 50,000 / 94 = 531.9148 shares (US step 0.0001, rounded down).
    # Protected that bar: stop 94 x 0.96 = 90.24, target the middle band of bars 2-6,
    # (100+100+100+90+94)/5 = 96.8. Bar 7 closes 96 (short of it); bar 8 closes 97, so the
    # target fires at 97. Each side is rounded to the cent: bought 531.9148 x 94 = 49,999.9912 ->
    # 49,999.99, sold 531.9148 x 97 = 51,595.7356 -> 51,595.74, so the profit is 1,595.75.
    closes = [100, 100, 100, 100, 100, 90, 94, 96, 97, 98, 98]
    world, run = run_algo(db, LIBRARY["bollinger_reversion"], {"period": 5, "k": "1.5"}, {"AAPL": closes})
    (trade,) = world.trades()
    assert trade.entry_price == D("94") and trade.quantity == D("531.9148")
    assert trade.status == TradeStatus.CLOSED and trade.closed_how == "target"
    assert trade.closed_at == world.close_of(8) and trade.realized_pnl == D("1595.75")
    assert run.errors == [] and not any("refused" in line.text for line in run.logs)


def test_crypto_breakout_buys_a_jump_with_an_atr_stop(db: Session):
    # Flat at 100 with highs 101 and lows 99 gives a true range of 2, so ATR 2 (period 3). Bar 10
    # closes 110, above 100 + 1.5 x 2 = 103: buy, filled at bar 11's close, 111. The stop is then
    # set from the ATR at that bar, which is fiddly by hand, so the test checks its shape: below
    # the entry, above zero, and accepted by the engine (a long's stop sits under the price).
    closes = [100] * 10 + [110, 111, 111, 111]
    params = {"atr_period": 3}
    world, run = run_algo(db, CryptoVolatilityBreakout, params, {"BTC-USD": closes})
    trade = world.trades()[0]
    assert trade.entry_price == D("111") and trade.direction == "long"
    assert D(0) < trade.stop_price < trade.entry_price
    assert not any("refused" in line.text for line in run.logs)
    assert run.errors == []


# --- the rule that keeps the library livable for uploaded code ---------------------------

ALLOWED_IMPORTS = {"math", "statistics", "decimal"}


def test_library_files_import_only_hq_and_the_allowed_standard_modules():
    folder = pathlib.Path(__file__).parent.parent / "app" / "algos" / "library"
    files = [f for f in folder.glob("*.py") if f.name != "__init__.py"]
    assert len(files) == 5
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert {a.name for a in node.names} <= ALLOWED_IMPORTS, path.name
            elif isinstance(node, ast.ImportFrom):
                is_hq = (node.module == "app.algos" and [a.name for a in node.names] == ["hq"]) or (
                    node.module == "app.algos.hq"
                )
                assert is_hq or node.module in ALLOWED_IMPORTS, f"{path.name} imports {node.module}"


# --- the API -----------------------------------------------------------------------------


def test_library_route_lists_every_algorithm_with_its_schema(client):
    body = client.get("/api/algos/library").json()
    assert [a["key"] for a in body] == list(LIBRARY)
    sma = body[0]
    assert (sma["name"], sma["interval"], sma["warmup_bars"]) == ("SMA crossover", "1d", 31)
    assert sma["markets"] == ["india", "international", "crypto"]
    params = {p["name"]: p for p in sma["parameters"]}
    assert params["fast_period"] == {
        "name": "fast_period", "label": "Fast period", "kind": "int", "default": 10, "min": 2,
        "max": 100, "choices": [], "help": "Bars in the fast average.",
    }  # fmt: skip
    cash = params["percent_of_cash"]
    assert (cash["kind"], cash["default"], cash["min"], cash["max"]) == ("decimal", "50", "1", "100")
    donchian = {p["name"]: p for p in body[2]["parameters"]}
    assert donchian["allow_shorts"]["default"] is False


def test_nothing_in_the_library_route_leaks_an_order_state(client, db: Session):
    # A read-only route: it must not create anything.
    client.get("/api/algos/library")
    assert db.scalars(select(Order).where(Order.status == OrderStatus.OPEN)).first() is None
