"""Running subscriptions live: one strategy run per subscription, held in memory.

The background loop calls `run_subscriptions_once` after the live tick. Each active subscription
keeps a `StrategyRun` (and, for uploaded code, its sandbox child process) between passes; after a
restart the runs are simply rebuilt on the next pass, which loses only the strategy's own memory.
Every failure is contained to its subscription. The registry of runs is shared with the user's own
deployments (`algos/live_runs.py`).
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algos import live_runs
from app.algos.library import LIBRARY
from app.algos.live_runs import Held
from app.algos.sandbox import load_strategy
from app.market_data.base import MarketDataProvider
from app.marketplace import listings, subscriptions
from app.models import Subscription, SubscriptionStatus
from app.trading.tick import run_tick

logger = logging.getLogger(__name__)

_Live = Held
_registry = live_runs.Registry()
_runs = _registry.runs  # tests read it; the registry owns the lock


def drop(sub_id: int) -> None:
    """Forget a subscription's run and close its sandbox child."""
    _registry.drop(sub_id)


def drop_all() -> None:
    _registry.drop_all()


def _build(ctx, listing_id: int, sub: Subscription) -> Held:
    """Build from the version the subscriber is pinned to, never the listing's current fields."""
    code, _interval = listings.code_for(ctx.db, listing_id, sub.listing_version)
    if isinstance(code, str):
        sandbox, params = load_strategy(code), None
        strategy = sandbox
    else:
        sandbox, (key, params) = None, code
        strategy = LIBRARY[key]
    return live_runs.build_held(ctx, strategy, sandbox, params, list(sub.symbols), sub.listing_version)


def _step_active(db: Session, provider: MarketDataProvider, sub: Subscription) -> None:
    ctx = subscriptions.sub_context(db, provider, sub)
    # The subscriber upgraded: the registry drops a run built from another version and rebuilds.
    _registry.step(sub.id, ctx, lambda: _build(ctx, sub.listing_id, sub), sub.listing_version)
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
