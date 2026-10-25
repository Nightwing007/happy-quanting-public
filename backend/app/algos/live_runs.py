"""What marketplace subscriptions and the user's own deployments share: both run a strategy live on
a dedicated `kind="algo"` paper account funded from the person's live cash.

This module holds the parts that must behave identically for both: picking and checking symbols,
moving the capital out and back, winding an account down to flat, the per-entity lock, and the
registry of in-memory `StrategyRun`s (with the sandbox child of uploaded code). What differs stays
with each caller: a subscription pays a creator fee and follows a listing version; a deployment
pins its own snapshot and can pause.

Checks raise whatever `err(code, message)` builds, so each caller keeps its own error type.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.algos.runner import StrategyRun, run_strategy_on
from app.algos.sandbox import SandboxedStrategy
from app.market_data.base import TRADABLE_TYPES, MarketDataError, MarketDataProvider
from app.models import (
    Account,
    AccountKind,
    CashTransfer,
    Order,
    OrderOrigin,
    OrderStatus,
    Trade,
    TradeStatus,
)
from app.sim.runner import MAX_SYMBOLS, _instrument
from app.trading import engine
from app.trading.context import TradingContext
from app.trading.errors import TradingError
from app.trading.markets import market_for
from app.trading.money import money

logger = logging.getLogger(__name__)
ZERO = Decimal(0)

ErrorFactory = Callable[[str, str], Exception]


# --- choosing what to run on -------------------------------------------------------------------


def clean_symbols(symbols: list[str], err: ErrorFactory) -> list[str]:
    names = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    if not names:
        raise err("no_symbols", "Pick at least one symbol to run the algorithm on.")
    if len(names) > MAX_SYMBOLS:
        raise err("too_many_symbols", f"Pick at most {MAX_SYMBOLS} symbols.")
    return names


def check_symbols(
    provider: MarketDataProvider, live: Account, names: list[str], allowed: set[str], err: ErrorFactory
) -> None:
    """Each symbol must exist, be tradable, have a broker on the live account, and trade on one of
    the `allowed` market codes."""
    for symbol in names:
        try:
            inst = _instrument(provider, symbol)
            if inst.type not in TRADABLE_TYPES:
                raise err("symbol_not_tradable", f"{symbol} can be charted but not traded.")
            market = market_for(inst.symbol, inst.type)
            engine._broker_for(live, market)  # the user's broker for this segment must offer the market
        except MarketDataError as why:
            raise err("symbol_unknown", f"Symbol {symbol}: {why.message}") from why
        except TradingError as why:
            raise err(why.code, why.message) from why
        if market.code not in allowed:
            raise err(
                "symbol_market",
                f"{symbol} trades on {market.name}, which this algorithm doesn't support.",
            )


# --- the capital -------------------------------------------------------------------------------


def check_capital(live: Account, capital: Decimal, err: ErrorFactory) -> Decimal:
    """The capital rounded to money, once it is positive and no more than the live account has free."""
    if not capital.is_finite() or money(capital) <= 0:
        raise err("invalid_capital", "Capital must be more than zero.")
    capital = money(capital)
    available = live.cash - live.margin_used
    if capital > available:
        raise err(
            "insufficient_cash",
            f"You have {available:f} {live.currency} available and asked to allocate {capital:f}.",
        )
    return capital


def open_account(db: Session, live: Account, user_id: int, capital: Decimal) -> Account:
    """A funded `kind="algo"` account with the live account's brokers. Takes the capital out of the
    live account; the caller records the `CashTransfer` once it has the row that owns the money."""
    account = Account(
        currency=live.currency, cash=capital, starting_cash=capital, realized_pnl=ZERO, margin_used=ZERO,
        created_at=clock.now(), kind=AccountKind.ALGO, user_id=user_id, broker_india=live.broker_india,
        broker_international=live.broker_international, broker_crypto=live.broker_crypto,
    )  # fmt: skip
    db.add(account)
    db.flush()
    live.cash -= capital
    return account


def return_cash(db: Session, account: Account, user_id: int, link: dict) -> None:
    """Move whatever cash the (flat) account holds back to the person's live account. `link` names
    the owner of the transfer row, e.g. `{"deployment_id": 3}`."""
    amount = account.cash
    if amount != 0:
        engine.account_for_user(db, user_id).cash += amount
        account.cash = ZERO
        db.add(CashTransfer(kind="return", amount=amount, created_at=clock.now(), **link))


# --- winding down ------------------------------------------------------------------------------


def wind_down(ctx: TradingContext) -> None:
    """Cancel waiting entries and ask for every open trade to be closed. Safe to repeat: a trade
    that already has a waiting exit is left alone."""
    db = ctx.db
    waiting = list(
        db.scalars(select(Order).where(Order.account_id == ctx.account.id, Order.status == OrderStatus.OPEN))
    )
    exiting = {o.trade_id for o in waiting if o.trade_id is not None}
    for order in waiting:
        if order.trade_id is None and order.origin == OrderOrigin.USER:
            engine.cancel_order(ctx, order.id)  # an entry that would reopen what we are closing
    open_trades = db.scalars(
        select(Trade)
        .where(Trade.account_id == ctx.account.id, Trade.status == TradeStatus.OPEN)
        .order_by(Trade.id)
    )
    for trade in list(open_trades):
        if trade.id in exiting:
            continue
        try:
            engine.exit_trade(ctx, trade.id)  # the Exit button's path; waits if the market is closed
        except (TradingError, MarketDataError) as why:
            db.rollback()
            logger.warning("Exit of trade %s refused while winding down, will retry: %s", trade.id, why)


def is_flat(ctx: TradingContext) -> bool:
    db, account_id = ctx.db, ctx.account.id
    open_trade = db.scalar(
        select(Trade.id).where(Trade.account_id == account_id, Trade.status == TradeStatus.OPEN).limit(1)
    )
    open_order = db.scalar(
        select(Order.id).where(Order.account_id == account_id, Order.status == OrderStatus.OPEN).limit(1)
    )
    return open_trade is None and open_order is None


def account_context(db: Session, provider: MarketDataProvider, account_id: int) -> TradingContext:
    """The account on the real clock (looked up per call so a test can replace the clock)."""
    account = db.get(Account, account_id)
    assert account is not None
    return TradingContext(db, account, provider, lambda: clock.now())


# --- locks and the live runs -------------------------------------------------------------------


class KeyedLocks:
    """One re-entrant lock per id. The background loop and a stop request can both reach the same
    subscription or deployment; settling and returning cash read the account, then write, and
    without this both threads would return it."""

    def __init__(self) -> None:
        self._locks: dict[int, threading.RLock] = {}
        self._guard = threading.Lock()

    def __call__(self, key: int) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(key, threading.RLock())


@dataclass
class Held:
    run: StrategyRun
    sandbox: SandboxedStrategy | None  # the child process of uploaded code; None for a library algo
    version: int  # what it was built from (a subscription's listing version; 0 where nothing moves)


def build_held(
    ctx: TradingContext, strategy, sandbox: SandboxedStrategy | None, params: dict | None,
    symbols: list[str], version: int,
) -> Held:  # fmt: skip
    """Start a run with `closed_only=True` (a live source's newest bar may still be forming). The
    sandbox child is closed if the run can't start."""
    try:
        run = run_strategy_on(ctx, strategy, params, symbols, closed_only=True)
    except BaseException:
        if sandbox is not None:
            sandbox.close()
        raise
    return Held(run, sandbox, version)


class Registry:
    """The in-memory run of each live entity. After a restart runs are simply rebuilt on the next
    pass, which loses only the strategy's own memory."""

    def __init__(self) -> None:
        self.runs: dict[int, Held] = {}
        # The loop thread steps runs while a request thread may stop one; a run is never closed mid-step.
        self.lock = threading.RLock()

    def drop(self, key: int) -> None:
        """Forget a run and close its sandbox child."""
        with self.lock:
            held = self.runs.pop(key, None)
        if held is not None and held.sandbox is not None:
            held.sandbox.close()

    def drop_all(self) -> None:
        for key in list(self.runs):
            self.drop(key)

    def step(
        self, key: int, ctx: TradingContext, build: Callable[[], Held], version: int | None = None
    ) -> Held:
        """Step the entity's run on a fresh context, building it first when there is none (or when
        `version` says the one held is built from something else)."""
        with self.lock:
            held = self.runs.get(key)
            if held is not None and version is not None and held.version != version:
                self.drop(key)
                held = None
            if held is None:
                held = self.runs[key] = build()
            else:
                held.run.rebind(ctx)
            held.run.step()
        return held
