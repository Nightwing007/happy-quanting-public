"""The block catalog, as data.

Each `BlockSpec` is one big chunk of strategy logic: a name, a plain sentence of help, bounded
settings (`params`), the ports other blocks plug into, how many bars of history it needs
(`lookback`) and the Python it emits. The compiler (`compile.py`) only fills these templates in,
so a new block is a new entry here and nothing else.

Ports carry one of three kinds of value:
- `signal`: true or false for one symbol on the latest bar. Signal and Combine blocks output it.
- `trigger`: an action. Action blocks output it so Risk blocks can attach to them.
- Universe has no ports; it only decides the bar size and the markets.

Snippet templates use `$name` for a setting (`string.Template`): the compiler swaps it for the
strategy parameter that holds the setting's value, e.g. `p["rsi_below_period"]`. Only logic goes
in a template; there is deliberately no if/else block, `if` lives inside the big blocks.
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal

from app.algos.api import Param
from app.algos.rules import INTERVALS

D = Decimal

SIGNAL = "signal"
TRIGGER = "trigger"

CATEGORIES = ("universe", "signal", "combine", "action", "risk", "custom")


@dataclass(frozen=True)
class Port:
    name: str
    type: str  # SIGNAL or TRIGGER
    multi: bool = False  # an input that takes several connections
    min: int = 1  # connections an input needs


@dataclass(frozen=True)
class BlockSpec:
    type: str
    category: str
    label: str
    help: str
    params: dict[str, Param] = field(default_factory=dict)
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
    # Bars of history needed, as arithmetic over `$setting` names ("$period + 1").
    lookback: str = "0"
    # The Python this block emits (see the module docstring). Meaning depends on the category:
    # a signal's is the body of a method returning bool; an action's lines run when its signal is on.
    snippet: str = ""
    # Settings that must hold together: (left, "<", right, a clause finishing "This X block's ...").
    rules: tuple[tuple[str, str, str, str], ...] = ()
    # custom blocks only
    custom_id: int | None = None
    custom_kind: str | None = None  # "group" or "code"

    @property
    def noun(self) -> str:
        """The short name messages use ("This Buy block ...")."""
        return SHORT.get(self.type) or self.label


# Short names for messages, and the words a block's settings are named after when the label is long.
SHORT = {
    "universe": "Universe",
    "rsi_below": "RSI",
    "rsi_above": "RSI",
    "breakout": "Breakout",
    "bollinger_touch": "Bollinger",
    "price_vs_sma": "Price vs SMA",
    "buy": "Buy",
    "short": "Short",
    "sell_all": "Sell all",
    "exit_all": "Exit all",
    "stop_loss": "Stop-loss",
    "target": "Target",
    "trading_hours": "Trading-hours",
}
SLUG_HINTS = {
    "buy": "buy",
    "short": "short",
    "breakout": "breakout",
    "bollinger_touch": "bollinger",
    "price_vs_sma": "price_vs_sma",
    "universe": "universe",
}


def _int(default: int, lo: int, hi: int, label: str, help: str) -> Param:
    return Param("int", default, min=lo, max=hi, label=label, help=help)


def _dec(default: str, lo: str, hi: str, label: str, help: str) -> Param:
    return Param("decimal", D(default), min=D(lo), max=D(hi), label=label, help=help)


def _choice(default: str, choices: tuple[str, ...], label: str, help: str) -> Param:
    return Param("choice", default, choices=choices, label=label, help=help)


def _period(default: int, help: str) -> Param:
    return _int(default, 2, 400, "Period", help)


_PERCENT_OF_CASH = _dec(
    "50", "1", "100", "Cash per entry (%)", "Share of available cash spent on each entry."
)

MARKET_CHOICES = ("all", "india", "international", "crypto")

_UNIVERSE = BlockSpec(
    type="universe",
    category="universe",
    label="Symbols & interval",
    help="Sets the bar size and the markets this algorithm is meant for; add exactly one.",
    params={
        "interval": _choice(
            "1d", INTERVALS, "Bar size", "How long each bar is. Everything else reads these bars."
        ),
        "markets": _choice("all", MARKET_CHOICES, "Markets", "Which markets the algorithm suits."),
    },
)

_SIGNALS = [
    BlockSpec(
        type="sma_cross",
        category="signal",
        label="SMA crossover",
        help="On when the fast moving average has just crossed the slow one, upward or downward.",
        params={
            "fast_period": _int(10, 2, 200, "Fast period", "Bars in the fast average."),
            "slow_period": _int(30, 3, 400, "Slow period", "Bars in the slow average."),
            "direction": _choice("up", ("up", "down"), "Direction", "Up: fast crosses above slow."),
        },
        outputs=(Port("signal", SIGNAL),),
        lookback="$slow_period + 1",
        rules=(
            (
                "fast_period",
                "<",
                "slow_period",
                "fast period must be below the slow period, or the averages never cross",
            ),
        ),
        snippet="""\
closes = ctx.close_series(symbol, $slow_period + 1)
if len(closes) < 2:
    return False
fast = ctx.indicators.sma(closes, $fast_period)
slow = ctx.indicators.sma(closes, $slow_period)
if $direction == "up":
    return fast[-2] <= slow[-2] and fast[-1] > slow[-1]
return fast[-2] >= slow[-2] and fast[-1] < slow[-1]""",
    ),
    BlockSpec(
        type="rsi_below",
        category="signal",
        label="RSI below",
        help="On while the RSI is under the level, a sign the price has dropped hard.",
        params={
            "period": _period(14, "Bars in the RSI."),
            "level": _int(30, 1, 99, "Level", "On when the RSI is below this."),
        },
        outputs=(Port("signal", SIGNAL),),
        lookback="$period + 1",
        # Four periods of closes let the smoothed RSI settle; it is the same window the library uses.
        snippet="""\
closes = ctx.close_series(symbol, $period * 4)
if not closes:
    return False
return ctx.indicators.rsi(closes, $period)[-1] < $level""",
    ),
    BlockSpec(
        type="rsi_above",
        category="signal",
        label="RSI above",
        help="On while the RSI is over the level, a sign the price has run up or recovered.",
        params={
            "period": _period(14, "Bars in the RSI."),
            "level": _int(70, 1, 99, "Level", "On when the RSI is above this."),
        },
        outputs=(Port("signal", SIGNAL),),
        lookback="$period + 1",
        snippet="""\
closes = ctx.close_series(symbol, $period * 4)
if not closes:
    return False
return ctx.indicators.rsi(closes, $period)[-1] > $level""",
    ),
    BlockSpec(
        type="breakout",
        category="signal",
        label="Price breaks N-bar high or low",
        help="On when the price closes above the highest high, or below the lowest low, of the last N bars.",
        params={
            "period": _period(20, "How many earlier bars to look back over."),
            "direction": _choice("high", ("high", "low"), "Breaks the", "High: new high. Low: new low."),
        },
        outputs=(Port("signal", SIGNAL),),
        lookback="$period + 1",
        snippet="""\
bars = ctx.bars(symbol, $period + 1)
if len(bars) < $period + 1:
    return False
if $direction == "high":
    return bars[-1].close > max(b.high for b in bars[:-1])
return bars[-1].close < min(b.low for b in bars[:-1])""",
    ),
    BlockSpec(
        type="bollinger_touch",
        category="signal",
        label="Price touches Bollinger band",
        help="On when the close reaches the lower or the upper Bollinger band.",
        params={
            "period": _period(20, "Bars in the middle average."),
            "k": _dec("2", "0.5", "5", "Width (k)", "Standard deviations between the middle and each band."),
            "band": _choice("lower", ("lower", "upper"), "Band", "Which band to watch."),
        },
        outputs=(Port("signal", SIGNAL),),
        lookback="$period",
        snippet="""\
closes = ctx.close_series(symbol, $period)
if len(closes) < $period:
    return False
middle, upper, lower = ctx.indicators.bollinger(closes, $period, float($k))
if $band == "lower":
    return closes[-1] <= lower[-1]
return closes[-1] >= upper[-1]""",
    ),
    BlockSpec(
        type="volume_spike",
        category="signal",
        label="Volume spike",
        help="On when the latest volume is a multiple of the average volume of the N bars before it.",
        params={
            "period": _period(20, "Bars in the average volume."),
            "k": _dec(
                "2", "1.1", "20", "Multiple (k)", "On when volume is more than this many times the average."
            ),
        },
        outputs=(Port("signal", SIGNAL),),
        lookback="$period + 1",
        snippet="""\
bars = ctx.bars(symbol, $period + 1)
if len(bars) < $period + 1:
    return False
average = sum(b.volume for b in bars[:-1]) / $period
return bars[-1].volume > average * float($k)""",
    ),
    BlockSpec(
        type="price_vs_sma",
        category="signal",
        label="Price above or below SMA",
        help="On while the close is above, or below, its simple moving average.",
        params={
            "period": _period(50, "Bars in the average."),
            "side": _choice("above", ("above", "below"), "Price is", "Above or below the average."),
        },
        outputs=(Port("signal", SIGNAL),),
        lookback="$period",
        snippet="""\
closes = ctx.close_series(symbol, $period)
if len(closes) < $period:
    return False
average = ctx.indicators.sma(closes, $period)[-1]
if $side == "above":
    return closes[-1] > average
return closes[-1] < average""",
    ),
]

# Combine blocks are the only logic blocks. `snippet` is an expression over the input variables.
_COMBINE = [
    BlockSpec(
        type="all_of",
        category="combine",
        label="All of",
        help="On only when every connected signal is on.",
        inputs=(Port("signals", SIGNAL, multi=True, min=2),),
        outputs=(Port("signal", SIGNAL),),
        snippet="all",
    ),
    BlockSpec(
        type="any_of",
        category="combine",
        label="Any of",
        help="On when at least one connected signal is on.",
        inputs=(Port("signals", SIGNAL, multi=True, min=2),),
        outputs=(Port("signal", SIGNAL),),
        snippet="any",
    ),
    BlockSpec(
        type="not",
        category="combine",
        label="Not",
        help="On when the connected signal is off.",
        inputs=(Port("signal", SIGNAL),),
        outputs=(Port("signal", SIGNAL),),
        snippet="not",
    ),
]

# Action snippets run inside `for symbol in ctx.symbols:` when the signal is on. `$gate` is where
# the compiler adds the attached Max-open-trades and Trading-hours conditions.
_ACTIONS = [
    BlockSpec(
        type="buy",
        category="action",
        label="Buy % of cash",
        help="Buys with a share of the available cash. Skipped when you already hold the symbol.",
        params={"percent_of_cash": _PERCENT_OF_CASH},
        inputs=(Port("signal", SIGNAL),),
        outputs=(Port("trigger", TRIGGER, multi=True, min=0),),
        snippet="""\
if ctx.position(symbol).quantity <= 0$gate:
    ctx.buy(symbol, percent_of_cash=$percent_of_cash)""",
    ),
    BlockSpec(
        type="sell_all",
        category="action",
        label="Sell all",
        help="Sells everything you hold in the symbol. Does nothing when you hold none.",
        inputs=(Port("signal", SIGNAL),),
        outputs=(Port("trigger", TRIGGER, multi=True, min=0),),
        snippet="""\
if ctx.position(symbol).quantity > 0:
    ctx.sell(symbol)""",
    ),
    BlockSpec(
        type="short",
        category="action",
        label="Short % of cash",
        help="Sells shares you don't hold, sized by a share of cash, where the market allows shorting.",
        params={"percent_of_cash": _PERCENT_OF_CASH},
        inputs=(Port("signal", SIGNAL),),
        outputs=(Port("trigger", TRIGGER, multi=True, min=0),),
        snippet="""\
if ctx.position(symbol).quantity >= 0$gate:
    ctx.short(symbol, percent_of_cash=$percent_of_cash)""",
    ),
    BlockSpec(
        type="exit_all",
        category="action",
        label="Exit all trades",
        help="Closes every open trade in the symbol, long or short.",
        inputs=(Port("signal", SIGNAL),),
        outputs=(Port("trigger", TRIGGER, multi=True, min=0),),
        snippet="""\
for trade in ctx.open_trades(symbol):
    ctx.exit(trade.id)""",
    ),
]

# Actions a Risk block may attach to: the ones that open trades.
ENTRY_ACTIONS = ("buy", "short")

_RISK = [
    BlockSpec(
        type="stop_loss",
        category="risk",
        label="Stop-loss %",
        help="Puts a stop-loss this far from the entry price on each trade the action opens.",
        params={
            "percent": _dec("5", "0.5", "50", "Stop-loss (%)", "Distance of the stop from the entry price.")
        },
        inputs=(Port("trigger", TRIGGER),),
    ),
    BlockSpec(
        type="target",
        category="risk",
        label="Target %",
        help="Puts a profit target this far from the entry price on each trade the action opens.",
        params={
            "percent": _dec("10", "0.5", "500", "Target (%)", "Distance of the target from the entry price.")
        },
        inputs=(Port("trigger", TRIGGER),),
    ),
    BlockSpec(
        type="max_open_trades",
        category="risk",
        label="Max open trades",
        help="The action is skipped while this many trades (across all symbols) are already open.",
        params={"count": _int(3, 1, 50, "Trades", "Most trades open at once.")},
        inputs=(Port("trigger", TRIGGER),),
    ),
    BlockSpec(
        type="trading_hours",
        category="risk",
        label="Trading-hours window",
        help="The action only runs between two exchange-local times; needs bars shorter than a day.",
        params={
            "start_hour": _int(9, 0, 23, "Start hour", "Hour the window opens (exchange time)."),
            "start_minute": _int(15, 0, 59, "Start minute", "Minute the window opens."),
            "end_hour": _int(15, 0, 23, "End hour", "Hour the window closes (exchange time)."),
            "end_minute": _int(0, 0, 59, "End minute", "Minute the window closes."),
            "utc_offset_minutes": _int(
                330,
                -720,
                840,
                "Exchange offset from UTC (minutes)",
                "India 330, London 0 or 60, New York -300 or -240 (clocks change in summer).",
            ),
        },
        inputs=(Port("trigger", TRIGGER),),
    ),
]

CATALOG: dict[str, BlockSpec] = {b.type: b for b in [_UNIVERSE, *_SIGNALS, *_COMBINE, *_ACTIONS, *_RISK]}

# Strategy markets for each Universe choice.
MARKETS_FOR = {
    "all": ("india", "international", "crypto"),
    "india": ("india",),
    "international": ("international",),
    "crypto": ("crypto",),
}

# Bars added on top of the longest lookback, so the first bar the strategy trades on has real history.
WARMUP_MARGIN = 5


# --- writing parameters as source ---------------------------------------------------------


def literal(value: object) -> str:
    """A value as a plain Python literal the validator reads without running anything. Text goes
    through JSON, whose escapes are valid Python and never include `.format` braces tricks."""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return f'Decimal("{value:f}")'
    if isinstance(value, str):
        return json.dumps(value)
    raise TypeError(f"Can't write {value!r} as a literal.")


def render_param(param: Param, label: str) -> str:
    """`hq.Param(...)` for one setting, as one line. `label` replaces the setting's own label."""
    parts = [literal(param.kind), literal(param.default)]
    if param.min is not None:
        parts.append(f"min={literal(param.min)}")
    if param.max is not None:
        parts.append(f"max={literal(param.max)}")
    if param.choices:
        parts.append("choices=(" + ", ".join(literal(c) for c in param.choices) + ",)")
    parts.append(f"label={literal(label)}")
    if param.help:
        parts.append(f"help={literal(param.help)}")
    return "hq.Param(" + ", ".join(parts) + ")"
