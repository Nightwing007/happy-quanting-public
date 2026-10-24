"""What a strategy may use. This module is the whole contract; uploaded code sees it as `hq`.

Nothing here imports the engine, a database session or a provider. A strategy is handed a
`StrategyContext`, a small facade over a `Backend` the runner supplies, so the surface a strategy can
reach is exactly the methods below and nothing a strategy does can touch another account.

Orders a strategy places are *intents*: the runner submits them at the next bar (see
`app/algos/runner.py`), never at the price the strategy decided on.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar, Protocol

import pandas as pd

from app import indicators as _ind

PARAM_KINDS = ("int", "decimal", "choice", "bool")
MAX_LOG_CHARS = 200
MAX_LOG_LINES = 500
MAX_BARS = 5000  # most bars one `bars()` call returns

D = Decimal


# --- parameters -------------------------------------------------------------------------


@dataclass(frozen=True)
class Param:
    """A setting a person can change before running a strategy. `min` and `max` bound `int` and
    `decimal` kinds, `choices` lists the allowed values of a `choice`."""

    kind: str
    default: Any
    min: Decimal | int | None = None
    max: Decimal | int | None = None
    choices: tuple[str, ...] = ()
    help: str = ""
    label: str = ""

    def __post_init__(self) -> None:
        if self.kind not in PARAM_KINDS:
            raise ValueError(
                f"A parameter's kind must be one of {', '.join(PARAM_KINDS)}, not {self.kind!r}."
            )
        if self.kind == "decimal":
            # Floats are fine to write in a declaration but are stored as the Decimal they print as.
            object.__setattr__(self, "default", D(str(self.default)))
            if self.min is not None:
                object.__setattr__(self, "min", D(str(self.min)))
            if self.max is not None:
                object.__setattr__(self, "max", D(str(self.max)))
        if self.kind == "choice":
            object.__setattr__(self, "choices", tuple(self.choices))
            if not self.choices:
                raise ValueError("A choice parameter needs choices.")
        elif self.choices:
            raise ValueError("Only a choice parameter takes choices.")
        if self.kind not in ("int", "decimal") and (self.min is not None or self.max is not None):
            raise ValueError("Only int and decimal parameters take a min or max.")
        problem = _check_value(self, self.default, "default")
        if problem:
            raise ValueError(problem)


class ParameterError(ValueError):
    """Settings a strategy can't be run with. `problems` has one sentence per bad field."""

    def __init__(self, problems: list[str]):
        super().__init__(" ".join(problems))
        self.problems = problems


def _label(name: str, param: Param) -> str:
    return param.label or name.replace("_", " ").capitalize()


def _check_value(param: Param, value: Any, what: str) -> str | None:
    if param.kind in ("int", "decimal"):
        if param.min is not None and value < param.min:
            return f"The {what} {value} is below the minimum {param.min}."
        if param.max is not None and value > param.max:
            return f"The {what} {value} is above the maximum {param.max}."
    elif param.kind == "choice" and value not in param.choices:
        return f"The {what} {value!r} is not one of {', '.join(param.choices)}."
    return None


def _coerce(param: Param, raw: Any) -> Any:
    """The value in the parameter's own type, or ValueError saying what it should have been."""
    if param.kind == "int":
        if isinstance(raw, bool):
            raise ValueError("a whole number")
        if isinstance(raw, int):
            return raw
        try:
            number = D(str(raw).strip())
        except InvalidOperation:
            raise ValueError("a whole number") from None
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError("a whole number")
        return int(number)
    if param.kind == "decimal":
        if isinstance(raw, bool):
            raise ValueError("a number")
        try:
            number = D(str(raw).strip())
        except InvalidOperation:
            raise ValueError("a number") from None
        if not number.is_finite():
            raise ValueError("a number")
        return number
    if param.kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true"
        raise ValueError("true or false")
    if raw in param.choices:
        return raw
    raise ValueError(f"one of {', '.join(param.choices)}")


def validate_params(strategy_cls: type[Strategy], raw: dict[str, Any]) -> dict[str, Any]:
    """Settings for a run: `raw` over the defaults, each coerced to its kind and bounds-checked.
    Raises one `ParameterError` that names every bad field, so a form can show them together."""
    declared = strategy_cls.PARAMETERS
    problems: list[str] = []
    for name in raw:
        if name not in declared:
            known = ", ".join(declared) or "none"
            problems.append(
                f"{name!r} is not a setting of {strategy_cls.name or 'this algorithm'} (it has: {known})."
            )
    values: dict[str, Any] = {}
    for name, param in declared.items():
        label = _label(name, param)
        if name not in raw:
            values[name] = param.default
            continue
        try:
            value = _coerce(param, raw[name])
        except ValueError as why:
            problems.append(f"{label} must be {why}, not {raw[name]!r}.")
            continue
        if param.kind in ("int", "decimal"):
            if param.min is not None and value < param.min:
                problems.append(f"{label} must be at least {param.min}, not {value}.")
                continue
            if param.max is not None and value > param.max:
                problems.append(f"{label} must be at most {param.max}, not {value}.")
                continue
        values[name] = value
    if not problems:
        problems.extend(strategy_cls.check_params(values))
    if problems:
        raise ParameterError(problems)
    return values


# --- what a strategy reads and returns --------------------------------------------------


@dataclass(frozen=True)
class Bar:
    """One finished candle. `time` is a "YYYY-MM-DD" date for daily bars and unix seconds for
    intraday ones, as the market data layer gives it."""

    time: str | int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class Position:
    """Net holding in one symbol: positive quantity is long, negative is short, zero is flat.
    `avg_price` is the average entry price of the open trades, in the instrument's currency."""

    symbol: str
    quantity: Decimal
    avg_price: Decimal


@dataclass(frozen=True)
class TradeInfo:
    """A read-only copy of a trade. Changing it changes nothing. `realized_pnl` and `closed_how`
    are filled once the trade has closed."""

    id: int
    symbol: str
    direction: str  # "long" or "short"
    quantity: Decimal  # still open
    entry_price: Decimal
    opened_at: datetime
    stop_price: Decimal | None
    target_price: Decimal | None
    status: str  # "open" or "closed"
    realized_pnl: Decimal | None = None  # account currency, after charges
    closed_how: str | None = None  # exit, sell, cover, square_off, stop_loss or target


@dataclass(frozen=True)
class OrderResult:
    """What asking for an order came to. `accepted` means it was queued for the next bar, which
    is not a promise it will fill: the engine may still refuse it then (the runner logs why)."""

    accepted: bool
    message: str = ""


@dataclass(frozen=True)
class OrderIntent:
    """An order a strategy asked for, waiting for the next bar. Sized when it is submitted, so
    the quantity reflects the price and cash it will really meet."""

    kind: str  # buy | sell | short | exit
    symbol: str = ""
    quantity: Decimal | None = None
    percent_of_cash: Decimal | None = None
    trade_id: int | None = None


class Backend(Protocol):
    """What the runner supplies. The facade below is all a strategy ever holds."""

    symbols: tuple[str, ...]

    def now(self) -> datetime: ...
    def cash(self) -> Decimal: ...
    def available_cash(self) -> Decimal: ...
    def bars(self, symbol: str, n: int) -> tuple[Bar, ...]: ...
    def price(self, symbol: str) -> Decimal: ...
    def position(self, symbol: str) -> Position: ...
    def open_trades(self, symbol: str | None) -> tuple[TradeInfo, ...]: ...
    def queue(self, intent: OrderIntent) -> None: ...
    def set_protection(self, trade_id: int, stop: Decimal | None, target: Decimal | None) -> OrderResult: ...
    def log(self, message: str) -> None: ...


# --- indicators for plain lists ----------------------------------------------------------


def _series(values: Sequence[float]) -> pd.Series:
    return pd.Series([float(v) for v in values], dtype=float)


def _list(s: pd.Series) -> list[float]:
    return [float(v) for v in s]  # NaN where a window is not full yet


class Indicators:
    """The pure functions of `app/indicators.py` on plain lists of floats. Each returns a list
    as long as its input, with `nan` where there are too few bars (test with `math.isnan`)."""

    def sma(self, values: Sequence[float], period: int) -> list[float]:
        return _list(_ind.sma(_series(values), period))

    def ema(self, values: Sequence[float], period: int) -> list[float]:
        return _list(_ind.ema(_series(values), period))

    def rsi(self, values: Sequence[float], period: int = 14) -> list[float]:
        return _list(_ind.rsi(_series(values), period))

    def atr(
        self, highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
    ) -> list[float]:
        return _list(_ind.atr(_series(highs), _series(lows), _series(closes), period))

    def bollinger(
        self, values: Sequence[float], period: int = 20, k: float = 2.0
    ) -> tuple[list[float], list[float], list[float]]:
        mid, upper, lower = _ind.bollinger(_series(values), period, k)
        return _list(mid), _list(upper), _list(lower)

    def highest(self, values: Sequence[float], period: int) -> list[float]:
        return _list(_ind.highest(_series(values), period))

    def lowest(self, values: Sequence[float], period: int) -> list[float]:
        return _list(_ind.lowest(_series(values), period))


INDICATORS = Indicators()


# --- the context -------------------------------------------------------------------------


class StrategyContext:
    """Everything a strategy can see and do. It is a facade: the account, the database and the
    engine are not reachable from it."""

    __slots__ = ("_backend", "_params")

    indicators = INDICATORS

    def __init__(self, backend: Backend, params: dict[str, Any]):
        self._backend = backend
        self._params = dict(params)

    # reading
    @property
    def params(self) -> dict[str, Any]:
        return dict(self._params)

    @property
    def symbols(self) -> tuple[str, ...]:
        return self._backend.symbols

    @property
    def now(self) -> datetime:
        """The context's clock: the moment the latest bar closed, never the wall clock."""
        return self._backend.now()

    @property
    def cash(self) -> Decimal:
        return self._backend.cash()

    @property
    def available_cash(self) -> Decimal:
        """Cash less the margin blocked by shorts: what a new order can use."""
        return self._backend.available_cash()

    def bars(self, symbol: str, n: int) -> tuple[Bar, ...]:
        """The last `n` finished bars, oldest first. Immutable; the bar still forming is never in it."""
        return self._backend.bars(self._known(symbol), max(0, min(int(n), MAX_BARS)))

    def close_series(self, symbol: str, n: int) -> list[float]:
        """Closing prices of the last `n` bars as floats, for the indicators (not for money)."""
        return [float(b.close) for b in self.bars(symbol, n)]

    def price(self, symbol: str) -> Decimal:
        """The latest price: the close of the last finished bar."""
        return self._backend.price(self._known(symbol))

    def position(self, symbol: str) -> Position:
        return self._backend.position(self._known(symbol))

    def open_trades(self, symbol: str | None = None) -> tuple[TradeInfo, ...]:
        if symbol is not None:
            symbol = self._known(symbol)
        return self._backend.open_trades(symbol)

    # acting
    def buy(
        self,
        symbol: str,
        quantity: Decimal | int | str | None = None,
        percent_of_cash: Decimal | int | str | None = None,
    ) -> OrderResult:
        """Buy `quantity` shares, or as many as `percent_of_cash` percent of available cash buys.
        Rounded down to the market's step. Covers a short first, as the engine does."""
        return self._order("buy", symbol, quantity, percent_of_cash)

    def sell(
        self,
        symbol: str,
        quantity: Decimal | int | str | None = None,
        percent_of_cash: Decimal | int | str | None = None,
    ) -> OrderResult:
        """Sell part of what you hold long (all of it when neither argument is given). Never
        opens a short: use `short` for that."""
        return self._order("sell", symbol, quantity, percent_of_cash)

    def short(
        self,
        symbol: str,
        quantity: Decimal | int | str | None = None,
        percent_of_cash: Decimal | int | str | None = None,
    ) -> OrderResult:
        """Sell shares you don't hold. Only works where the market offers shorting; the engine
        refuses otherwise and the refusal is logged."""
        return self._order("short", symbol, quantity, percent_of_cash)

    def exit(self, trade_id: int) -> OrderResult:
        """Close all of one open trade at the market."""
        self._backend.queue(OrderIntent("exit", trade_id=int(trade_id)))
        return OrderResult(True, "Queued for the next bar.")

    def set_protection(
        self,
        trade_id: int,
        stop: Decimal | int | str | None = None,
        target: Decimal | int | str | None = None,
    ) -> OrderResult:
        """Set a trade's stop-loss and target now (both None clears them). Unlike an order this
        takes effect at once; the engine checks both against the current price."""
        try:
            stop_d = None if stop is None else D(str(stop))
            target_d = None if target is None else D(str(target))
        except InvalidOperation:
            return self._refuse("A stop or target must be a number.")
        return self._backend.set_protection(int(trade_id), stop_d, target_d)

    def log(self, message: object) -> None:
        text = str(message)
        self._backend.log(text if len(text) <= MAX_LOG_CHARS else text[: MAX_LOG_CHARS - 3] + "...")

    # helpers
    def _known(self, symbol: str) -> str:
        symbol = str(symbol).strip().upper()
        if symbol not in self._backend.symbols:
            raise ValueError(
                f"{symbol} is not one of this run's symbols ({', '.join(self._backend.symbols)})."
            )
        return symbol

    def _refuse(self, message: str) -> OrderResult:
        self.log(message)
        return OrderResult(False, message)

    def _order(self, kind: str, symbol: str, quantity: Any, percent: Any) -> OrderResult:
        try:
            symbol = self._known(symbol)
        except ValueError as why:
            return self._refuse(str(why))
        if quantity is not None and percent is not None:
            return self._refuse(f"{kind} {symbol}: give a quantity or a percent_of_cash, not both.")
        if quantity is None and percent is None and kind != "sell":
            return self._refuse(f"{kind} {symbol}: give a quantity or a percent_of_cash.")
        try:
            qty = None if quantity is None else D(str(quantity))
            pct = None if percent is None else D(str(percent))
        except InvalidOperation:
            return self._refuse(f"{kind} {symbol}: the quantity or percent is not a number.")
        if (qty is not None and not qty > 0) or (pct is not None and not 0 < pct <= 100):
            return self._refuse(
                f"{kind} {symbol}: quantity must be above zero and percent_of_cash between 0 and 100."
            )
        self._backend.queue(OrderIntent(kind, symbol, qty, pct))
        return OrderResult(True, "Queued for the next bar.")


# --- strategies --------------------------------------------------------------------------


class Strategy:
    """Subclass this, set the class attributes and override the hooks you need. A new instance
    is made for every run, so `self` may hold state between bars."""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    # Segments ("india", "international", "crypto") and/or market codes ("NSE", "NASDAQ") it suits.
    markets: ClassVar[tuple[str, ...]] = ()
    interval: ClassVar[str] = "1d"
    warmup_bars: ClassVar[int] = 0
    PARAMETERS: ClassVar[dict[str, Param]] = {}

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> list[str]:
        """Rules that span several settings (a fast period below the slow one). One sentence
        per problem; called only once each setting is individually valid."""
        return []

    def on_start(self, ctx: StrategyContext) -> None:
        """Once, before the first bar."""

    def on_bar(self, ctx: StrategyContext) -> None:
        """After each bar closes, once `warmup_bars` bars exist. Orders placed here fill at the
        next bar's price."""

    def on_trade_closed(self, ctx: StrategyContext, trade: TradeInfo) -> None:
        """After one of this strategy's trades closed, by its own exit or by a stop, a target or
        the square-off."""
