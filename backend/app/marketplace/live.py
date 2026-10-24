"""Running subscriptions live: one strategy run per subscription, held in memory.

The background loop calls `run_subscriptions_once` after the live tick. Each active subscription
keeps a `StrategyRun` (and, for uploaded code, its sandbox child process) between passes; after a
restart the runs are simply rebuilt on the next pass, which loses only the strategy's own memory.
Every failure is contained to its subscription.
"""

import logging
import threading
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algos.library import LIBRARY
from app.algos.runner import StrategyRun, run_strategy_on
from app.algos.sandbox import SandboxedStrategy, load_strategy
from app.market_data.base import MarketDataProvider
from app.marketplace import listings, subscriptions
from app.models import Subscription, SubscriptionStatus
from app.trading.tick import run_tick

logger = logging.getLogger(__name__)


@dataclass
class _Live:
    run: StrategyRun
    sandbox: SandboxedStrategy | None  # the child process of uploaded code; None for a library algo
    version: int  # the listing version it was built from (the subscription's pin)


_runs: dict[int, _Live] = {}
# The loop thread steps runs while a request thread may stop one; a run is never closed mid-step.
_lock = threading.RLock()


def drop(sub_id: int) -> None:
    """Forget a subscription's run and close its sandbox child."""
    with _lock:
        live = _runs.pop(sub_id, None)
    if live is not None and live.sandbox is not None:
        live.sandbox.close()


def drop_all() -> None:
    for sub_id in list(_runs):
        drop(sub_id)


def _build(ctx, listing_id: int, sub: Subscription) -> _Live:
    """Build from the version the subscriber is pinned to, never the listing's current fields."""
    code, _interval = listings.code_for(ctx.db, listing_id, sub.listing_version)
    if isinstance(code, str):
        sandbox, params = load_strategy(code), None
        strategy = sandbox
    else:
        sandbox, (key, params) = None, code
        strategy = LIBRARY[key]
    try:
        run = run_strategy_on(ctx, strategy, params, list(sub.symbols), closed_only=True)
    except BaseException:
        if sandbox is not None:
            sandbox.close()
        raise
    return _Live(run, sandbox, sub.listing_version)


def _step_active(db: Session, provider: MarketDataProvider, sub: Subscription) -> None:
    ctx = subscriptions.sub_context(db, provider, sub)
    with _lock:
        live = _runs.get(sub.id)
        if live is not None and live.version != sub.listing_version:
            drop(sub.id)  # the subscriber upgraded: run the version they moved to
            live = None
        if live is None:
            live = _runs[sub.id] = _build(ctx, sub.listing_id, sub)
        else:
            live.run.rebind(ctx)
        live.run.step()
    subscriptions.settle_fees(db, sub)


def _advance(db: Session, provider: MarketDataProvider, sub: Subscription) -> None:
    if sub.status == SubscriptionStatus.ACTIVE:
        _step_active(db, provider, sub)
        return
    drop(sub.id)
    run_tick(subscriptions.sub_context(db, provider, sub))  # fills the exits that were waiting
    subscriptions.advance_stop(db, provider, sub)


def run_subscriptions_once(db: Session, provider: MarketDataProvider) -> None:
    subs = list(
        db.scalars(
            select(Subscription)
            .where(Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.STOPPING]))
            .order_by(Subscription.id)
        )
    )
    for sub in subs:
        try:
            _advance(db, provider, sub)
        except Exception:  # noqa: BLE001 - one subscription's failure must not stop the others
            db.rollback()
            logger.exception("Subscription %s failed; will retry", sub.id)
    # Anything no longer active (stopped just now, or deleted) must not keep a child process alive.
    still_active = {s.id for s in subs if s.status == SubscriptionStatus.ACTIVE}
    for sub_id in list(_runs):
        if sub_id not in still_active:
            drop(sub_id)
