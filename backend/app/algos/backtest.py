"""Backtest a strategy: replay a past date range through the real engine and measure what happened.

Nothing here is a second engine. The strategy trades a scratch `kind="backtest"` account through
`run_strategy_on`, the replay provider moves the clock bar by bar, and every order is costed by
`plan_cost` like a live one, so charges, market hours, the square-off, shorting rules and
financing are the live ones. This module adds only the loop around them and the arithmetic of the
results (equity, drawdown, Sharpe, a buy-and-hold to compare with).

Money is `Decimal` throughout. Ratios that need a square root or a power (Sharpe, CAGR) go through
float for that one operation and come back as a rounded `Decimal`.
"""

import logging
import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import clock
from app.algos.api import OrderIntent, Strategy, validate_params
from app.algos.library import LIBRARY
from app.algos.runner import _EngineBackend, run_strategy_on
from app.market_data.base import TRADABLE_TYPES, Bar, Instrument, MarketDataProvider
from app.market_data.fx import get_fx_rate
from app.market_data.history import HistoryRangeError, get_history, today_utc, validate_range
from app.market_data.replay import ReplayProvider
from app.models import Account, AccountKind, Order, OrderStatus, Trade, TradeDirection, TradeStatus
from app.schemas import (
    BacktestBrokersIn,
    BacktestBuyHoldOut,
    BacktestDrawdownOut,
    BacktestInstrumentOut,
    BacktestLogOut,
    BacktestMetricsOut,
    BacktestPointOut,
    BacktestPurchaseOut,
    BacktestResultsOut,
    BacktestTradeOut,
    OrderOut,
)
from app.sim.runner import FX_LOOKBACK_DAYS, MAX_SYMBOLS, _instrument, fx_pairs, session_functions
from app.trading import brokers as broker_data
from app.trading import engine, hours
from app.trading.context import TradingContext
from app.trading.markets import Market, market_for
from app.trading.money import trim8

logger = logging.getLogger(__name__)

D = Decimal
ZERO = Decimal(0)
HUNDRED = Decimal(100)
CENT = Decimal("0.01")
# Curves longer than this are thinned for storage and the chart; the metrics always use every bar.
MAX_CURVE_POINTS = 3000
MIN_SHARPE_DAYS = 20
SEGMENT_YEAR_DAYS = {"crypto": 365}  # trading days a year; everything else 252
_OPENING = ("open_long", "open_short")

Progress = Callable[[int], None]


class BacktestError(Exception):
    """A request the backtester can't honour. `status_code` is what the API answers with."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class BacktestNotFound(BacktestError):
    status_code = 404


class BacktestConflict(BacktestError):
    status_code = 409


# --- the arithmetic of the results ----------------------------------------------------------
# Pure functions, so a test can check them against figures worked by hand.


def _pct(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def drawdown_series(equities: Sequence[Decimal], baseline: Decimal) -> list[Decimal]:
    """How far each point sits below the highest equity seen so far (the starting cash counts as
    a peak), in percent: 0 at a new high, negative below it."""
    peak = baseline
    out = []
    for equity in equities:
        peak = max(peak, equity)
        out.append(_pct((equity - peak) / peak * HUNDRED) if peak else ZERO)
    return out


def max_drawdown_pct(drawdowns: Sequence[Decimal]) -> Decimal:
    """The deepest fall, as a positive percentage."""
    return -min(drawdowns, default=ZERO) if drawdowns else ZERO


def daily_equity(points: Sequence[tuple[int, Decimal]]) -> list[Decimal]:
    """The last equity of each UTC day, from (unix seconds, equity) pairs in time order. A point
    stamped exactly at midnight is the close of the day that just ended, so it counts there."""
    last: dict[date, Decimal] = {}
    for stamp, equity in points:
        last[datetime.fromtimestamp(stamp - 1, UTC).date()] = equity
    return list(last.values())


def sharpe_ratio(
    daily: Sequence[Decimal], baseline: Decimal, trading_days: int
) -> tuple[Decimal | None, str | None]:
    """Mean daily return over its sample standard deviation, times the square root of the trading
    days in a year. The risk-free rate is taken as zero. The first return is measured from the
    starting cash. None (with the reason) when there are under 20 days or no variation."""
    if len(daily) < MIN_SHARPE_DAYS:
        return None, (f"Sharpe needs at least {MIN_SHARPE_DAYS} days of returns; this run has {len(daily)}.")
    previous = [baseline, *daily[:-1]]
    returns = [float(now / before - 1) for now, before in zip(daily, previous, strict=True)]
    spread = statistics.stdev(returns)
    if spread == 0:
        return None, "Sharpe is undefined: the account's value never varied from day to day."
    ratio = statistics.fmean(returns) / spread * math.sqrt(trading_days)
    return D(str(round(ratio, 4))).quantize(CENT), None


def cagr_pct(start: Decimal, final: Decimal, days: int) -> tuple[Decimal | None, str | None]:
    """Compound annual growth, only for a run of at least a year (shorter, it is a projection)."""
    if days < 365:
        return None, f"CAGR needs at least a year of data; this run covers {days} days."
    if start <= 0 or final <= 0:
        return None, "CAGR is undefined: the account ended with nothing."
    growth = math.pow(float(final / start), 365 / days) - 1
    return D(str(round(growth * 100, 4))).quantize(CENT), None


# --- the run ------------------------------------------------------------------------------


@dataclass
class _Point:
    stamp: int
    equity: Decimal
    cash: Decimal
    positions: Decimal
    invested: bool


def _resolve_strategy(key: str | None, cls: type[Strategy] | None) -> tuple[str, type[Strategy]]:
    if cls is not None:
        return key or cls.__name__, cls
    if key is None or key not in LIBRARY:
        known = ", ".join(LIBRARY)
        raise BacktestError(f"There is no algorithm '{key}'. Choose one of: {known}.")
    return key, LIBRARY[key]


def default_brokers(db: Session) -> dict[str, str]:
    """The live account's broker per segment, or the app's defaults before it exists."""
    live = db.scalar(select(Account).where(Account.kind == AccountKind.LIVE).order_by(Account.id).limit(1))
    if live is None:
        return dict(broker_data.DEFAULT_BROKERS)
    return {
        "india": live.broker_india,
        "international": live.broker_international,
        "crypto": live.broker_crypto,
    }


def resolve_brokers(db: Session, chosen: BacktestBrokersIn | dict[str, str | None] | None) -> dict[str, str]:
    base = default_brokers(db)
    given = chosen.model_dump() if isinstance(chosen, BacktestBrokersIn) else dict(chosen or {})
    return {segment: given.get(segment) or code for segment, code in base.items()}


def _check_brokers(markets: list[Market], brokers: dict[str, str]) -> None:
    """Refuse up front a broker that doesn't offer a market, rather than log a refusal on every bar."""
    probe = Account(
        currency="USD", broker_india=brokers["india"], broker_international=brokers["international"],
        broker_crypto=brokers["crypto"],
    )  # fmt: skip
    for market in markets:
        engine._broker_for(probe, market)  # raises BrokerNotAvailable with the sentence to show


def _new_account(
    db: Session, *, currency: str, cash: Decimal, brokers: dict[str, str], owner: int | None
) -> Account:
    account = Account(
        currency=currency, cash=cash, starting_cash=cash, realized_pnl=ZERO, margin_used=ZERO,
        created_at=clock.now(), kind=AccountKind.BACKTEST, user_id=owner,
        broker_india=brokers["india"], broker_international=brokers["international"],
        broker_crypto=brokers["crypto"],
    )  # fmt: skip
    db.add(account)
    db.flush()
    return account


def discard_account(db: Session, account_id: int) -> None:
    """Delete a scratch account with its orders and trades (orders point at trades: they go first)."""
    db.execute(delete(Order).where(Order.account_id == account_id))
    db.execute(delete(Trade).where(Trade.account_id == account_id))
    db.execute(delete(Account).where(Account.id == account_id))
    db.commit()


def sweep_scratch_accounts(db: Session) -> int:
    """Remove backtest accounts a crashed run left behind. Only call when no run is in progress."""
    ids = list(db.scalars(select(Account.id).where(Account.kind == AccountKind.BACKTEST)))
    for account_id in ids:
        discard_account(db, account_id)
    return len(ids)


def _mark(ctx: TradingContext) -> tuple[Decimal, Decimal, bool]:
    """(cash + positions, positions, whether anything is open): what the account is worth at the
    replay's price, valued as `get_portfolio` does so the two agree. A long counts at market
    value, a short at what it took in less what covering would cost."""
    trades = list(
        ctx.db.scalars(
            select(Trade).where(Trade.account_id == ctx.account.id, Trade.status == TradeStatus.OPEN)
        )
    )
    positions = ZERO
    for trade in trades:
        try:
            quote = ctx.provider.get_quote(trade.symbol)
            fx = trim8(get_fx_rate(ctx.provider, trade.currency, ctx.account.currency))
        except Exception:  # noqa: BLE001 - an unpriced position is valued at cost, as the portfolio does
            quote, fx = None, None
        view = engine._value_trade(trade, quote, fx)
        if trade.direction == TradeDirection.LONG:
            positions += view.market_value
        else:
            positions += trade.entry_value - view.market_value
    return ctx.account.cash + positions, positions, bool(trades)


def _charges_by_category(orders: Sequence[Order]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for order in orders:
        if order.status != OrderStatus.FILLED:
            continue
        for charge in order.charges:
            totals[charge["category"]] += D(charge["amount"])
    return dict(totals)


def _trade_rows(
    trades: Sequence[Trade],
    orders: Sequence[Order],
    last_prices: dict[int, Decimal],
    trade_numbers: dict[int, int],
) -> list[BacktestTradeOut]:
    """Each trade with what it paid in and out, read from the orders' legs (the immutable record;
    a trade's own charge columns shrink as it is exited)."""
    entry: dict[int, Decimal] = defaultdict(lambda: ZERO)
    exit_: dict[int, Decimal] = defaultdict(lambda: ZERO)
    by_category: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    exits: dict[int, list[tuple[Decimal, Decimal]]] = defaultdict(list)  # (quantity, price)
    for order in orders:
        if order.status != OrderStatus.FILLED:
            continue
        for leg in order.legs:
            trade_id = leg["trade_id"]
            if trade_id is None:
                continue
            total = D(leg["charges_total"])
            if leg["kind"] in _OPENING:
                entry[trade_id] += total
            else:
                exit_[trade_id] += total
                exits[trade_id].append((D(leg["quantity"]), D(leg["price"])))
            for charge in leg["charges"]:
                by_category[trade_id][charge["category"]] += D(charge["amount"])
    rows = []
    for trade in trades:
        closed = trade.status == TradeStatus.CLOSED
        sold = exits.get(trade.id, [])
        sold_quantity = sum((q for q, _ in sold), ZERO)
        exit_price = sum((q * p for q, p in sold), ZERO) / sold_quantity if sold_quantity else None
        charges = entry[trade.id] + exit_[trade.id]
        gross = trade.realized_pnl + charges + trade.financing_paid if closed else None
        unrealized = None
        if not closed and trade.id in last_prices:
            unrealized = last_prices[trade.id]
        rows.append(
            BacktestTradeOut(
                id=trade_numbers[trade.id],
                symbol=trade.symbol,
                name=trade.name,
                currency=trade.currency,
                direction=trade.direction,
                product=trade.product,
                quantity=trade.quantity,
                entry_at=trade.opened_at,
                entry_price=trade.entry_price,
                exit_at=trade.closed_at,
                exit_price=trim8(exit_price) if exit_price is not None else None,
                status=trade.status,
                closed_how=trade.closed_how,
                entry_charges=entry[trade.id],
                exit_charges=exit_[trade.id],
                charges_total=charges,
                charges_by_category=dict(by_category[trade.id]),
                financing=trade.financing_paid,
                gross_pnl=gross,
                realized_pnl=trade.realized_pnl if closed else None,
                unrealized_pnl=unrealized,
            )
        )
    return rows


def _thin(items: list, stride: int) -> list:
    if stride <= 1:
        return items
    return [x for i, x in enumerate(items) if i % stride == 0 or i == len(items) - 1]


def _trade_metrics(
    rows: list[BacktestTradeOut],
    points: list[_Point],
    orders: Sequence[Order],
    start: Decimal,
    final: Decimal,
) -> BacktestMetricsOut:
    closed = [r for r in rows if r.status == "closed"]
    pnl = [r.realized_pnl for r in closed]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]
    gross_profit = sum((r.gross_pnl for r in closed if r.gross_pnl > 0), ZERO)
    closed_charges = sum((r.charges_total for r in closed), ZERO)
    by_category = _charges_by_category(orders)
    return BacktestMetricsOut(
        starting_cash=start,
        final_equity=final,
        total_return_pct=_pct((final - start) / start * HUNDRED),
        cagr_pct=None,  # filled by the caller, which knows the dates
        cagr_note=None,
        max_drawdown_pct=ZERO,
        sharpe=None,
        sharpe_note=None,
        trades_closed=len(closed),
        trades_open=len(rows) - len(closed),
        win_rate_pct=_pct(D(len(wins)) / len(closed) * HUNDRED) if closed else None,
        average_win=_pct(sum(wins, ZERO) / len(wins)) if wins else None,
        average_loss=_pct(sum(losses, ZERO) / len(losses)) if losses else None,
        profit_factor=(_pct(sum(wins, ZERO) / -sum(losses, ZERO)) if wins and losses else None),
        total_charges=sum(by_category.values(), ZERO),
        charges_by_category=by_category,
        gross_profit=gross_profit if gross_profit > 0 else None,
        charges_pct_of_gross_profit=_pct(closed_charges / gross_profit * HUNDRED)
        if gross_profit > 0
        else None,
        financing_paid=sum((r.financing for r in rows), ZERO),
        exposure_pct=_pct(D(sum(p.invested for p in points)) / len(points) * HUNDRED) if points else ZERO,
    )


def _load(
    db: Session,
    provider: MarketDataProvider,
    names: list[str],
    instruments: list[Instrument],
    interval: str,
    start: date,
    end: date,
    currency: str,
    today: date,
) -> tuple[dict[str, list[Bar]], dict[str, list[Bar]]]:
    bars = {s: get_history(db, provider, s, interval, start, end, today) for s in names}
    empty = [s for s, series in bars.items() if not series]
    if len(empty) == len(names):
        raise HistoryRangeError(
            f"No {interval} bars between {start:%d %b %Y} and {end:%d %b %Y}: the market was shut "
            "(weekend or holiday). Pick a longer range."
        )
    if empty:
        raise HistoryRangeError(f"No {interval} bars for {', '.join(empty)} in that range.")
    fx_start = start - timedelta(days=FX_LOOKBACK_DAYS)
    fx = {
        pair: get_history(db, provider, pair, "1d", fx_start, end, today)
        for pair in fx_pairs(instruments, currency)
    }
    return bars, fx


@dataclass
class Request:
    """A backtest request that has passed every check that needs no history."""

    key: str
    cls: type[Strategy]
    values: dict
    names: list[str]
    instruments: list[Instrument]
    markets: list[Market]
    brokers: dict[str, str]
    today: date


def check_request(
    db: Session,
    provider: MarketDataProvider,
    *,
    strategy_key: str | None,
    strategy_cls: type[Strategy] | None,
    params: dict | None,
    symbols: list[str],
    interval: str,
    start: date,
    end: date,
    starting_cash: Decimal,
    brokers: dict[str, str] | BacktestBrokersIn | None,
    today: date | None,
) -> Request:
    """Everything that can be refused before any history is fetched or any account made. Raises
    with a sentence a person can act on; the API runs it when a backtest is queued, so a bad
    request is answered at once instead of failing in the queue."""
    key, cls = _resolve_strategy(strategy_key, strategy_cls)
    values = validate_params(cls, params or {})
    if interval != cls.interval:
        raise BacktestError(
            f"{cls.name or key} is built for {cls.interval} bars, so it can't be tested on {interval} bars."
        )
    names = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    if not names or len(names) > MAX_SYMBOLS:
        raise BacktestError(f"Pick between 1 and {MAX_SYMBOLS} symbols.")
    if starting_cash <= 0:
        raise BacktestError("The starting cash must be above zero.")
    today = today or today_utc()
    validate_range(interval, start, end, today)

    instruments = [_instrument(provider, s) for s in names]
    for inst in instruments:
        if inst.type not in TRADABLE_TYPES:
            raise BacktestError(
                f"{inst.name} ({inst.symbol}) can be charted but not traded, so it can't be backtested."
            )
    markets = [market_for(i.symbol, i.type) for i in instruments]
    chosen = resolve_brokers(db, brokers)
    _check_brokers(markets, chosen)
    return Request(key, cls, values, names, instruments, markets, chosen, today)


def run_backtest(
    db: Session,
    provider: MarketDataProvider,
    *,
    strategy_key: str | None = None,
    strategy_cls: type[Strategy] | None = None,
    params: dict | None = None,
    symbols: list[str],
    interval: str,
    start: date,
    end: date,
    starting_cash: Decimal,
    brokers: dict[str, str] | None = None,
    account_currency: str,
    today: date | None = None,
    progress: Progress | None = None,
    store: Callable[[BacktestResultsOut], None] | None = None,
    owner_user_id: int | None = None,
) -> BacktestResultsOut:
    """Play `start..end` through the engine and return the results.

    `provider` supplies instrument details and, for bars the cache lacks, history; the prices the
    strategy trades at come only from the replay. `store`, if given, is called with the results
    while the scratch accounts still exist and before they are deleted, so a caller that keeps
    the results never loses them to a failure in the cleanup. The accounts are deleted before
    this returns, whatever happens, so a run leaves nothing behind but the returned results.
    """
    req = check_request(
        db, provider, strategy_key=strategy_key, strategy_cls=strategy_cls, params=params,
        symbols=symbols, interval=interval, start=start, end=end, starting_cash=starting_cash,
        brokers=brokers, today=today,
    )  # fmt: skip
    key, cls, values, names = req.key, req.cls, req.values, req.names
    instruments, markets, chosen, today = req.instruments, req.markets, req.brokers, req.today

    bars, fx = _load(db, provider, names, instruments, interval, start, end, account_currency, today)

    replay = ReplayProvider(
        datetime.now(UTC),  # replaced below, before anything reads it
        instruments={i.symbol: i for i in instruments},
        inner=provider,
        timezones={i.symbol: hours.timezone_of(m) for i, m in zip(instruments, markets, strict=True)},
        sessions=session_functions(instruments, markets),
    )
    for symbol, series in bars.items():
        replay.load(symbol, interval, series)
    for pair, series in fx.items():
        replay.load(pair, "1d", series)
    first_cursor = replay.first_cursor(names, interval)
    assert first_cursor is not None
    replay.cursor = first_cursor
    visits = replay.visit_times(names, interval)
    closes = replay.close_times(names, interval)
    n_bars = len(closes)

    account = _new_account(
        db, currency=account_currency, cash=starting_cash, brokers=chosen, owner=owner_user_id
    )
    hold_account = _new_account(
        db, currency=account_currency, cash=starting_cash, brokers=chosen, owner=owner_user_id
    )
    db.commit()
    try:
        ctx = TradingContext(db, account, replay, lambda: replay.cursor)
        hold_ctx = TradingContext(db, hold_account, replay, lambda: replay.cursor)
        strategy = cls()
        run = run_strategy_on(ctx, strategy, values, names)
        if n_bars < strategy.warmup_bars:
            raise BacktestError(
                f"{cls.name or key} needs {strategy.warmup_bars} bars before it can act, but "
                f"{start:%d %b %Y} to {end:%d %b %Y} holds only {n_bars}. Pick a longer range."
            )
        hold = _BuyAndHold(hold_ctx, strategy, names, starting_cash)

        points: list[_Point] = []
        hold_points: list[_Point] = []
        report_every = max(1, len(visits) // 100)
        for index, stamp in enumerate(visits):
            replay.cursor = datetime.fromtimestamp(stamp, UTC)
            hold.try_buying()
            run.step()
            if stamp in closes:
                equity, positions, invested = _mark(ctx)
                points.append(_Point(stamp, equity, account.cash, positions, invested))
                hold_equity, hold_positions, _ = _mark(hold_ctx)
                hold_points.append(_Point(stamp, hold_equity, hold_account.cash, hold_positions, True))
            if progress is not None and index % report_every == 0:
                progress(min(99, 100 * index // len(visits)))

        results = _results(
            db, ctx, hold_ctx, run, key, cls, values, instruments, markets, interval, start, end,
            starting_cash, account_currency, points, hold_points, hold, n_bars,
        )  # fmt: skip
        if store is not None:
            store(results)
    finally:
        db.rollback()  # a failed run may leave the session mid-transaction
        discard_account(db, account.id)
        discard_account(db, hold_account.id)
    if progress is not None:
        progress(100)
    return results


class _BuyAndHold:
    """Equal weight in every symbol, each bought at the first price the engine will fill at, with
    the same charges. Tries each bar until it fills, then holds."""

    MAX_TRIES = 10

    def __init__(self, ctx: TradingContext, strategy: Strategy, names: list[str], cash: Decimal):
        self.backend = _EngineBackend(ctx, strategy, tuple(names))
        self.ctx = ctx
        self.allotment = cash / len(names)
        self.waiting = {s: 0 for s in names}  # symbol -> tries so far

    def try_buying(self) -> None:
        for symbol in list(self.waiting):
            if self.waiting[symbol] >= self.MAX_TRIES:
                del self.waiting[symbol]
                continue
            available = self.backend.available_cash()
            if available <= 0:
                return
            self.waiting[symbol] += 1
            percent = min(HUNDRED, self.allotment / available * HUNDRED)
            self.backend.submit_now(OrderIntent("buy", symbol, percent_of_cash=percent))
            if self.backend._held_long(symbol) > 0:
                del self.waiting[symbol]


def _results(
    db, ctx, hold_ctx, run, key, cls, values, instruments, markets, interval, start, end,
    starting_cash, currency, points, hold_points, hold, n_bars,
) -> BacktestResultsOut:  # fmt: skip
    account, hold_account = ctx.account, hold_ctx.account
    trades = list(db.scalars(select(Trade).where(Trade.account_id == account.id).order_by(Trade.id)))
    orders = list(db.scalars(select(Order).where(Order.account_id == account.id).order_by(Order.id)))

    # Open trades are marked at the last price, the way the portfolio would show them.
    unrealized: dict[int, Decimal] = {}
    for trade in trades:
        if trade.status == TradeStatus.OPEN:
            try:
                quote = ctx.provider.get_quote(trade.symbol)
                fx = trim8(get_fx_rate(ctx.provider, trade.currency, currency))
                unrealized[trade.id] = engine._value_trade(trade, quote, fx).unrealized_pnl
            except Exception:  # noqa: BLE001 - leave it unmarked rather than fail the whole run
                logger.warning("Could not mark open trade %d at the end of the backtest", trade.id)
    # Row ids depend on what else is in the tables, so the results number their own trades and
    # orders from 1: the same run always reads the same.
    trade_numbers = {t.id: n for n, t in enumerate(trades, 1)}
    rows = _trade_rows(trades, orders, unrealized, trade_numbers)
    order_out = []
    for number, order in enumerate(orders, 1):
        out = OrderOut.model_validate(order)
        out.id = number
        out.trade_id = trade_numbers.get(order.trade_id) if order.trade_id is not None else None
        for leg in out.legs:
            leg.trade_id = trade_numbers.get(leg.trade_id) if leg.trade_id is not None else None
        order_out.append(out)

    final = points[-1].equity
    equities = [p.equity for p in points]
    stamps = [(p.stamp, p.equity) for p in points]
    drawdown = drawdown_series(equities, starting_cash)
    hold_equities = [p.equity for p in hold_points]
    hold_drawdown = drawdown_series(hold_equities, starting_cash)

    year_days = 365 if all(m.segment == "crypto" for m in markets) else 252
    span_days = (
        datetime.fromtimestamp(points[-1].stamp, UTC) - datetime.fromtimestamp(points[0].stamp, UTC)
    ).days + 1
    metrics = _trade_metrics(rows, points, orders, starting_cash, final)
    metrics.max_drawdown_pct = max_drawdown_pct(drawdown)
    metrics.cagr_pct, metrics.cagr_note = cagr_pct(starting_cash, final, span_days)
    metrics.sharpe, metrics.sharpe_note = sharpe_ratio(daily_equity(stamps), starting_cash, year_days)

    hold_orders = list(
        db.scalars(select(Order).where(Order.account_id == hold_account.id).order_by(Order.id))
    )
    hold_final = hold_points[-1].equity
    hold_cagr, _ = cagr_pct(starting_cash, hold_final, span_days)
    purchases = []
    for order in hold_orders:
        if order.status == OrderStatus.FILLED:
            purchases.append(
                BacktestPurchaseOut(
                    symbol=order.symbol,
                    at=order.filled_at,
                    quantity=order.quantity,
                    price=order.fill_price,
                    charges=order.charges_total,
                )
            )
    buy_hold = BacktestBuyHoldOut(
        purchases=purchases,
        final_equity=hold_final,
        total_return_pct=_pct((hold_final - starting_cash) / starting_cash * HUNDRED),
        cagr_pct=hold_cagr,
        max_drawdown_pct=max_drawdown_pct(hold_drawdown),
        total_charges=sum(_charges_by_category(hold_orders).values(), ZERO),
    )

    stride = max(1, math.ceil(len(points) / MAX_CURVE_POINTS))
    curve = [
        BacktestPointOut(
            at=datetime.fromtimestamp(p.stamp, UTC),
            equity=p.equity,
            cash=p.cash,
            positions=p.positions,
            buy_hold_equity=h.equity,
        )
        for p, h in zip(points, hold_points, strict=True)
    ]
    drawdown_out = [
        BacktestDrawdownOut(at=c.at, strategy_pct=d, buy_hold_pct=h)
        for c, d, h in zip(curve, drawdown, hold_drawdown, strict=True)
    ]

    notes = [
        f"{cls.name or key} needs {run.strategy.warmup_bars} bars before it can act, so the first "
        f"{run.strategy.warmup_bars} of the {n_bars} bars only feed its indicators.",
    ]
    if interval in ("1d", "1wk", "1mo"):
        notes.append(
            "Daily bars give two prices a day, the open and the close. Orders decided at a close "
            "fill at the next open; a stop or target is only checked at those two prices, so a "
            "move inside the day that touched it and came back is not seen."
        )

    def plain(value):
        return f"{value:f}" if isinstance(value, Decimal) else value

    return BacktestResultsOut(
        strategy_key=key,
        strategy_name=cls.name or key,
        params={name: plain(v) for name, v in values.items()},
        account_currency=currency,
        interval=interval,
        instruments=[
            BacktestInstrumentOut(symbol=i.symbol, name=i.name, currency=i.currency, market=m.code)
            for i, m in zip(instruments, markets, strict=True)
        ],
        bars=n_bars,
        warmup_bars=run.strategy.warmup_bars,
        first_bar=curve[0].at,
        last_bar=curve[-1].at,
        curve_stride=stride,
        equity_curve=_thin(curve, stride),
        drawdown=_thin(drawdown_out, stride),
        trades=rows,
        orders=order_out,
        logs=[BacktestLogOut(at=line.at, text=line.text) for line in run.logs],
        errors=list(run.errors),
        notes=notes,
        metrics=metrics,
        buy_and_hold=buy_hold,
    )
