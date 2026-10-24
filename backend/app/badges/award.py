"""Turning the evaluator's answer into `user_badges` rows.

Three entry points: `award_new` (a badge earned now, shown as a toast), `backfill_all` (once, at
start-up, for past activity: stored as already seen so there is no toast per badge) and `sweep`
(the background loop, which re-checks only users with recent activity). Rows are never deleted.
"""

import threading
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.badges.catalog import BADGES, CHAMPION, ELITE_FOUR
from app.badges.evaluate import LONG_HOLD, evaluate_user
from app.models import (
    Account,
    AccountKind,
    AlgoListing,
    Backtest,
    BacktestStatus,
    ListingPerformance,
    ListingStatus,
    Order,
    PerformanceStatus,
    SimSession,
    SimStatus,
    Subscription,
    Trade,
    TradeStatus,
    User,
    UserBadge,
)

FIRST_SWEEP_LOOKBACK = timedelta(minutes=5)

_state_lock = threading.Lock()
_last_sweep: datetime | None = None
_inflight_owners: set[int] = set()  # owners of sims, backtests and measurements still running


def _ordered(ids: set[str]) -> list[str]:
    return sorted(ids, key=lambda i: (BADGES[i].region, BADGES[i].order))


def earned_ids(db: Session, user_id: int) -> set[str]:
    return set(db.scalars(select(UserBadge.badge_id).where(UserBadge.user_id == user_id)))


def _insert(
    db: Session, user_id: int, ids: set[str], now: datetime, *, seen: bool, backfilled: bool
) -> list[str]:
    """Insert the ids that aren't rows yet. A concurrent writer winning the unique key is fine."""
    added: list[str] = []
    for badge_id in _ordered(ids):
        try:
            with db.begin_nested():
                db.add(
                    UserBadge(
                        user_id=user_id, badge_id=badge_id, earned_at=now, seen=seen, backfilled=backfilled
                    )
                )
            added.append(badge_id)
        except IntegrityError:
            continue
    db.commit()
    return added


def award_new(db: Session, user_id: int, now: datetime) -> list[str]:
    """Award what the user has earned and doesn't hold yet, unseen. Returns the new ids."""
    fresh = evaluate_user(db, user_id, now) - earned_ids(db, user_id)
    return _insert(db, user_id, fresh, now, seen=False, backfilled=False)


def backfill_all(db: Session, now: datetime) -> int:
    """Award past activity to every user who holds no badge yet, as seen and backfilled: they get
    one summary instead of a toast each. Users who already hold rows are left to `award_new`."""
    total = 0
    for user_id in db.scalars(select(User.id).order_by(User.id)).all():
        if db.scalar(select(func.count()).select_from(UserBadge).where(UserBadge.user_id == user_id)):
            continue
        total += len(_insert(db, user_id, evaluate_user(db, user_id, now), now, seen=True, backfilled=True))
    return total


def backfill_summary(db: Session, user: User) -> int | None:
    """How many badges were awarded for past activity, until the user acknowledges it."""
    if user.badge_summary_seen:
        return None
    count = db.scalar(
        select(func.count())
        .select_from(UserBadge)
        .where(UserBadge.user_id == user.id, UserBadge.backfilled.is_(True))
    )
    return count or None


def creator_badges(db: Session, user_id: int) -> list[str]:
    """The badges shown on a marketplace card: the Elite Four and the Champion, nothing else."""
    shown = {*ELITE_FOUR, CHAMPION}
    return _ordered(earned_ids(db, user_id) & shown)


def mark_seen(db: Session, user_id: int, ids: list[str]) -> None:
    db.execute(
        update(UserBadge).where(UserBadge.user_id == user_id, UserBadge.badge_id.in_(ids)).values(seen=True)
    )
    db.commit()


def acknowledge_summary(db: Session, user: User) -> None:
    user.badge_summary_seen = True
    db.commit()


# --- the background loop ---------------------------------------------------------------------


def _active_users(db: Session, since: datetime, now: datetime) -> tuple[set[int], set[int]]:
    """(users whose data changed since `since`, owners of work still in flight). Anything a user
    does leaves a timestamp after `since`, except time passing on an open trade and a subscriber
    upgrading, which two of the reads below cover."""
    owner_of = {a.id: a.user_id for a in db.scalars(select(Account).where(Account.kind == AccountKind.LIVE))}
    live = list(owner_of)

    def owners(account_ids) -> set[int]:
        return {owner_of[i] for i in account_ids if owner_of.get(i) is not None}

    changed: set[int] = set()
    changed |= owners(
        db.scalars(
            select(Order.account_id).where(
                Order.account_id.in_(live), or_(Order.created_at >= since, Order.filled_at >= since)
            )
        )
    )
    changed |= owners(
        db.scalars(
            select(Trade.account_id).where(
                Trade.account_id.in_(live), or_(Trade.opened_at >= since, Trade.closed_at >= since)
            )
        )
    )
    changed |= owners(  # an open trade crossing the 30-day mark needs nobody to act
        db.scalars(
            select(Trade.account_id).where(
                Trade.account_id.in_(live),
                Trade.status == TradeStatus.OPEN,
                Trade.opened_at <= now - LONG_HOLD,
            )
        )
    )
    changed |= set(db.scalars(select(Backtest.owner_user_id).where(Backtest.created_at >= since)))
    changed |= set(db.scalars(select(SimSession.owner_user_id).where(SimSession.created_at >= since)))
    changed |= set(db.scalars(select(AlgoListing.owner_user_id).where(AlgoListing.updated_at >= since)))
    changed |= set(
        db.scalars(
            select(AlgoListing.owner_user_id)
            .join(ListingPerformance, ListingPerformance.listing_id == AlgoListing.id)
            .where(ListingPerformance.computed_at >= since)
        )
    )
    changed |= set(
        db.scalars(
            select(AlgoListing.owner_user_id)
            .join(Subscription, Subscription.listing_id == AlgoListing.id)
            .where(or_(Subscription.created_at >= since, Subscription.stopped_at >= since))
        )
    )
    # An upgrade rewrites a subscription without a timestamp, so creators of a version 2+ listing
    # are always looked at: there are few of them.
    changed |= set(
        db.scalars(
            select(AlgoListing.owner_user_id).where(
                AlgoListing.version >= 2,
                AlgoListing.status.in_([ListingStatus.PUBLISHED, ListingStatus.RETIRED]),
            )
        )
    )
    inflight: set[int] = set(
        db.scalars(select(SimSession.owner_user_id).where(SimSession.status == SimStatus.RUNNING))
    )
    inflight |= set(
        db.scalars(
            select(Backtest.owner_user_id).where(
                Backtest.status.in_([BacktestStatus.QUEUED, BacktestStatus.RUNNING])
            )
        )
    )
    inflight |= set(
        db.scalars(
            select(AlgoListing.owner_user_id)
            .join(ListingPerformance, ListingPerformance.listing_id == AlgoListing.id)
            .where(ListingPerformance.status.in_([PerformanceStatus.QUEUED, PerformanceStatus.RUNNING]))
        )
    )
    return {u for u in changed if u is not None}, {u for u in inflight if u is not None}


def sweep(db: Session, now: datetime) -> dict[int, list[str]]:
    """Award new badges to the users with recent activity: everyone changed since the last sweep,
    plus owners of work that was still running then (so a finishing sim or backtest is seen).
    Returns {user_id: new ids} for the users who earned something."""
    global _last_sweep, _inflight_owners
    with _state_lock:
        since = _last_sweep if _last_sweep is not None else now - FIRST_SWEEP_LOOKBACK
        previous = _inflight_owners
    changed, inflight = _active_users(db, since, now)
    out: dict[int, list[str]] = {}
    for user_id in sorted(changed | inflight | previous):
        new = award_new(db, user_id, now)
        if new:
            out[user_id] = new
    with _state_lock:
        _last_sweep, _inflight_owners = now, inflight
    return out


def reset_sweep_state() -> None:
    """For tests: forget the last sweep."""
    global _last_sweep, _inflight_owners
    with _state_lock:
        _last_sweep, _inflight_owners = None, set()
