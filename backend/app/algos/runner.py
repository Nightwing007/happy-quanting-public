"""Drive a strategy through bars with the real engine.

`run_strategy_on` gives back a `StrategyRun`; the caller (the sim, the backtester) moves the
context's clock to the end of each bar and calls `step()`. A step does, in this order:

1. submit the orders the strategy asked for earlier (they meet the next price that exists),
2. call `on_bar` when new bars have closed,
3. `run_tick`: resting orders, stops and targets, the square-off, financing.

Why orders wait: `on_bar` learns the close of the bar that just ended, and a trader cannot act at
a price they only learned at the close. If a strategy's order filled right away it would fill at
exactly the price that triggered it, which flatters every backtest. So `buy`, `sell`, `short` and
`exit` only record an intent; the intent is submitted on the first step whose quote is newer than
the one the strategy decided on. For intraday bars that is the close of the next bar. For daily
bars the replay quotes the open at the session open, so a decision made on day t's close fills at
day t+1's open, which is what a real broker gives you.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from app.algos.api import (
    MAX_LOG_LINES,
    Bar,
    OrderIntent,
    OrderResult,
    Position,
    Strategy,
    StrategyContext,
    TradeInfo,
    validate_params,
)
from app.market_data.base import MarketDataError
from app.market_data.fx import get_fx_rate
from app.models import OrderSide, OrderType, Trade, TradeDirection, TradeStatus
from app.trading import engine
from app.trading import markets as market_data
from app.trading.context import TradingContext
from app.trading.engine import protection_price_step
from app.trading.errors import TradingError
from app.trading.money import trim8
from app.trading.tick import run_tick

D = Decimal
ZERO = Decimal(0)
# Enough range for any bar count a strategy can ask for; the cap on `bars()` is what limits it.
_ALL_HISTORY = "10y"


class StrategyRunError(Exception):
    """The run can't start (no bars of the interval the strategy wants, no symbols)."""


@dataclass(frozen=True)
class LogLine:
    at: datetime
    text: str


def round_down_to_step(quantity: Decimal, step: Decimal) -> Decimal:
    """Round down to a whole multiple of `step`. Down, never to the nearest: rounding up could
    spend cash the strategy does not have."""
    return (quantity // step) * step


def _info(trade: Trade) -> TradeInfo:
    return TradeInfo(
        id=trade.id,
        symbol=trade.symbol,
        direction=trade.direction,
        quantity=trade.open_quantity,
        entry_price=trade.entry_price,
        opened_at=trade.opened_at,
        stop_price=trade.stop_price,
        target_price=trade.target_price,
        status=trade.status,
        realized_pnl=trade.realized_pnl if trade.status == TradeStatus.CLOSED else None,
        closed_how=trade.closed_how,
    )


@dataclass
class _Pending:
    intent: OrderIntent
    symbol: str | None  # whose price gates the submission; None submits at the next step
    decided_on: int | None  # as_of of that symbol's quote when the strategy decided


class _EngineBackend:
    """The `Backend` over a real context. Imports the engine so the facade need not."""

    def __init__(self, ctx: TradingContext, strategy: Strategy, symbols: tuple[str, ...]):
        self.ctx = ctx
        self.interval = strategy.interval
        self.symbols = symbols
        self.pending: list[_Pending] = []
        self.logs: list[LogLine] = []
        self._log_full = False

    # reading
    def now(self) -> datetime:
        return self.ctx.now()

    def cash(self) -> Decimal:
        return self.ctx.account.cash

    def available_cash(self) -> Decimal:
        account = self.ctx.account
        return max(ZERO, account.cash - account.margin_used)

    def bars(self, symbol: str, n: int) -> tuple[Bar, ...]:
        if n <= 0:
            return ()
        provider = self.ctx.provider
        recent = getattr(provider, "recent_bars", None)  # the replay can skip building the past
        raw = (
            recent(symbol, self.interval, n)
            if recent is not None
            else provider.get_bars(symbol, self.interval, _ALL_HISTORY)[-n:]
        )
        return tuple(Bar(b.time, b.open, b.high, b.low, b.close, b.volume) for b in raw)

    def quote_stamp(self, symbol: str) -> int | None:
        """When the symbol's current price came into being; changes only when a new price does."""
        try:
            return self.ctx.provider.get_quote(symbol).as_of
        except MarketDataError:
            return None

    def price(self, symbol: str) -> Decimal:
        return self.ctx.provider.get_quote(symbol).price

    def _open(self, symbol: str | None) -> list[Trade]:
        query = select(Trade).where(Trade.account_id == self.ctx.account.id, Trade.status == TradeStatus.OPEN)
        if symbol is not None:
            query = query.where(Trade.symbol == symbol)
        return list(self.ctx.db.scalars(query.order_by(Trade.opened_at, Trade.id)))

    def open_trades(self, symbol: str | None) -> tuple[TradeInfo, ...]:
        return tuple(_info(t) for t in self._open(symbol))

    def _held_long(self, symbol: str) -> Decimal:
        return sum((t.open_quantity for t in self._open(symbol) if t.direction == TradeDirection.LONG), ZERO)

    def position(self, symbol: str) -> Position:
        quantity, weighted = ZERO, ZERO
        for t in self._open(symbol):
            signed = t.open_quantity if t.direction == TradeDirection.LONG else -t.open_quantity
            quantity += signed
            weighted += t.open_quantity * t.entry_price
        total = sum((t.open_quantity for t in self._open(symbol)), ZERO)
        return Position(symbol, quantity, weighted / total if total else ZERO)

    # acting
    def queue(self, intent: OrderIntent) -> None:
        symbol = intent.symbol or None
        if intent.kind == "exit":
            trade = self.ctx.db.get(Trade, intent.trade_id)
            symbol = trade.symbol if trade is not None and trade.account_id == self.ctx.account.id else None
        decided_on = self.quote_stamp(symbol) if symbol else None
        self.pending.append(_Pending(intent, symbol, decided_on))

    def set_protection(self, trade_id: int, stop: Decimal | None, target: Decimal | None) -> OrderResult:
        try:
            trade = self.ctx.db.get(Trade, trade_id)
            if trade is not None and trade.account_id == self.ctx.account.id:
                # A computed price such as entry x 0.95 has more decimals than the market quotes;
                # snap it so a sound stop is not refused for its spelling.
                quote = self.ctx.provider.get_quote(trade.symbol)
                step = protection_price_step(market_data.market_for(trade.symbol, quote.type))
                stop = None if stop is None else stop.quantize(step, ROUND_HALF_UP)
                target = None if target is None else target.quantize(step, ROUND_HALF_UP)
            engine.set_protection(self.ctx, trade_id, stop, target)
        except (TradingError, MarketDataError) as why:
            message = getattr(why, "message", str(why))
            self.log(f"Protection on trade {trade_id} refused: {message}")
            return OrderResult(False, message)
        return OrderResult(True)

    def log(self, message: str) -> None:
        if self._log_full:
            return
        if len(self.logs) >= MAX_LOG_LINES:
            self._log_full = True
            self.logs.append(
                LogLine(self.ctx.now(), f"Log full after {MAX_LOG_LINES} lines; the rest is dropped.")
            )
            return
        self.logs.append(LogLine(self.ctx.now(), message))

    # submitting
    def submit_now(self, intent: OrderIntent) -> None:
        """Send an intent immediately, sized and refused like any other (for the buy-and-hold)."""
        self._submit(intent)

    def flush(self) -> None:
        """Submit every intent whose symbol has a price newer than the one it was decided on."""
        waiting: list[_Pending] = []
        for item in self.pending:
            if item.symbol is not None and self.quote_stamp(item.symbol) in (item.decided_on, None):
                waiting.append(item)
                continue
            self._submit(item.intent)
        self.pending = waiting

    def _submit(self, intent: OrderIntent) -> None:
        try:
            if intent.kind == "exit":
                engine.exit_trade(self.ctx, intent.trade_id)
                return
            quantity = self._size(intent)
            if quantity is None:
                return
            side = OrderSide.BUY if intent.kind == "buy" else OrderSide.SELL
            engine.place_order(
                self.ctx, symbol=intent.symbol, side=side, type=OrderType.MARKET, quantity=quantity
            )
        except (TradingError, MarketDataError) as why:
            # A refused order is a normal outcome (no cash, market shut, no shorting): record it
            # and carry on, never crash the strategy.
            what = (
                f"exit trade {intent.trade_id}" if intent.kind == "exit" else f"{intent.kind} {intent.symbol}"
            )
            self.log(f"Order refused ({what}): {getattr(why, 'message', str(why))}")

    def _size(self, intent: OrderIntent) -> Decimal | None:
        """The quantity to send, or None (after logging why) when there is nothing to send."""
        symbol, kind = intent.symbol, intent.kind
        quote = self.ctx.provider.get_quote(symbol)
        market = market_data.market_for(symbol, quote.type)
        step = market.quantity_step
        if kind == "short" and market.short_rule is not None:
            step = max(step, market.short_rule.min_shortable_step)
        held = self._held_long(symbol)

        if kind == "short" and held > 0:
            self.log(f"Skipped short {symbol}: a long position is open, and selling would only close it.")
            return None
        allotted: Decimal | None = None
        if intent.quantity is not None:
            raw = intent.quantity
        elif intent.percent_of_cash is not None:
            fx = trim8(get_fx_rate(self.ctx.provider, quote.currency, self.ctx.account.currency))
            allotted = self.available_cash() * intent.percent_of_cash / 100
            raw = allotted / (quote.price * fx)
        else:  # a bare sell: everything held long
            raw = held
        if kind == "sell":
            raw = min(raw, held)
            if held <= 0:
                self.log(f"Skipped sell {symbol}: no long position to sell.")
                return None
        quantity = round_down_to_step(raw, step)
        if kind == "buy" and allotted is not None and quantity > 0:
            quantity = self._fit_charges(symbol, quantity, step, allotted)
        if quantity <= 0:
            self.log(f"Skipped {kind} {symbol}: {raw:f} is less than the smallest tradable step, {step:f}.")
            return None
        return quantity

    def _fit_charges(self, symbol: str, quantity: Decimal, step: Decimal, allotted: Decimal) -> Decimal:
        """Shrink a purchase until its value plus its charges is within `allotted`.

        Sizing by price alone spends the whole allotment on shares, leaving nothing for brokerage,
        taxes and the rest, so at 100% of cash the engine would refuse the buy. The charges come
        from the engine's own preview (the calculator the fill uses), so what is checked here is
        what will be charged. They are not proportional to the quantity (minimum brokerage, flat
        fees), so the quantity is scaled down by the shortfall and checked again, a few times, then
        stepped down one lot at a time.
        """
        for _ in range(60):
            cost = engine.preview_order(
                self.ctx, symbol=symbol, side=OrderSide.BUY, type=OrderType.MARKET, quantity=quantity
            )
            need = -cost.cash_change + cost.margin_change
            if need <= allotted:
                return quantity
            scaled = round_down_to_step(quantity * allotted / need, step)
            quantity = scaled if scaled < quantity else quantity - step
            if quantity <= 0:
                return ZERO
        return ZERO


class StrategyRun:
    """One strategy trading one account. Call `step()` after each bar closes."""

    def __init__(self, ctx: TradingContext, strategy: Strategy, params: dict, symbols: tuple[str, ...]):
        self.trading = ctx
        self.strategy = strategy
        self.params = params
        self.symbols = symbols
        self._backend = _EngineBackend(ctx, strategy, symbols)
        self.api = StrategyContext(self._backend, params)  # type: ignore[arg-type]
        self.errors: list[str] = []
        self._last_bars: tuple | None = None
        self._open_ids: set[int] = {t.id for t in self._backend._open(None)}

    @property
    def logs(self) -> list[LogLine]:
        return self._backend.logs

    def _guard(self, hook: str, call, *args) -> None:
        # A strategy's own bug ends that bar's work, not the run: it is recorded where the
        # person can read it.
        try:
            call(self.api, *args)
        except Exception as why:  # noqa: BLE001 - strategy code is untrusted
            self.errors.append(f"{hook}: {type(why).__name__}: {why}")
            self._backend.log(f"{hook} raised {type(why).__name__}: {why}")

    def start(self) -> None:
        self._guard("on_start", self.strategy.on_start)

    def _ready(self) -> tuple | None:
        """Time of each symbol's last bar when every symbol has the warmup it needs, else None."""
        needed = max(1, self.strategy.warmup_bars)
        times = []
        for symbol in self.symbols:
            try:
                bars = self._backend.bars(symbol, needed)
            except MarketDataError:
                return None
            if len(bars) < needed:
                return None
            times.append(bars[-1].time)
        return tuple(times)

    def step(self) -> None:
        backend = self._backend
        backend.flush()  # before on_bar: an order is sent at the first price after it was decided
        self._remember_open()
        fresh = self._ready()
        if fresh is not None and fresh != self._last_bars:
            self._last_bars = fresh
            self._guard("on_bar", self.strategy.on_bar)
        run_tick(self.trading)
        self._report_closed()

    def _remember_open(self) -> None:
        self._open_ids |= {t.id for t in self._backend._open(None)}

    def _report_closed(self) -> None:
        now_open = {t.id for t in self._backend._open(None)}
        gone = self._open_ids - now_open
        self._open_ids = now_open
        for trade_id in sorted(gone):
            trade = self.trading.db.get(Trade, trade_id)
            if trade is not None and trade.status == TradeStatus.CLOSED:
                self._guard("on_trade_closed", self.strategy.on_trade_closed, _info(trade))


def run_strategy_on(
    ctx: TradingContext, strategy: Strategy | type[Strategy], params: dict | None, symbols: list[str]
) -> StrategyRun:
    """Validate the settings, check the data exists, call `on_start` and return the run.

    `strategy` may be a class (a fresh instance is made) or an instance. The same function serves
    the sim and the backtester: neither is special-cased, both move `ctx.now()` and call `step()`.
    """
    instance = strategy() if isinstance(strategy, type) else strategy
    # The instance, not its class: a sandboxed strategy keeps its settings per instance.
    values = validate_params(instance, params or {})  # type: ignore[arg-type]
    names = tuple(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    if not names:
        raise StrategyRunError("Pick at least one symbol to run the algorithm on.")
    probe = _EngineBackend(ctx, instance, names)
    for symbol in names:
        try:
            probe.bars(symbol, 1)
        except MarketDataError as why:
            raise StrategyRunError(f"No {instance.interval} bars for {symbol}: {why}") from why
    run = StrategyRun(ctx, instance, values, names)
    run.start()
    return run


__all__ = ["LogLine", "StrategyRun", "StrategyRunError", "round_down_to_step", "run_strategy_on"]
