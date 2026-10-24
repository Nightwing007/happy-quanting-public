"""Gym badges: the catalog, my badges (with what is new), and anyone's public badge list.

Badges are ids and dates only: they say nothing about code, settings or trades.
"""

from fastapi import APIRouter
from sqlalchemy import select

from app import clock
from app.api.deps import CurrentUser, DbSession
from app.badges import award
from app.badges.catalog import BADGES, REGIONS
from app.marketplace.listings import MarketplaceError
from app.models import User, UserBadge
from app.schemas import (
    BadgeCatalogOut,
    BadgeOut,
    BadgeRegionOut,
    BadgesSeenIn,
    EarnedBadgeOut,
    MyBadgesOut,
    UserBadgesOut,
)

router = APIRouter(tags=["badges"])


def _earned(db: DbSession, user_id: int) -> list[UserBadge]:
    rows = db.scalars(select(UserBadge).where(UserBadge.user_id == user_id)).all()
    return sorted(rows, key=lambda r: (r.earned_at, BADGES[r.badge_id].region, BADGES[r.badge_id].order))


def _mine(db: DbSession, user: User) -> MyBadgesOut:
    rows = _earned(db, user.id)
    return MyBadgesOut(
        earned=[EarnedBadgeOut(id=r.badge_id, earned_at=r.earned_at) for r in rows],
        new=[r.badge_id for r in rows if not r.seen],
        backfill_summary=award.backfill_summary(db, user),
    )


@router.get("/api/badges/catalog", response_model=BadgeCatalogOut)
def get_catalog(user: CurrentUser) -> BadgeCatalogOut:
    return BadgeCatalogOut(
        regions=[
            BadgeRegionOut(
                id=region.id,
                name=region.name,
                group=region.group,  # type: ignore[arg-type]
                badges=[
                    BadgeOut(id=b.id, name=b.name, order=b.order, hint=b.hint, kind=b.kind)
                    for b in sorted(BADGES.values(), key=lambda b: b.order)
                    if b.region == region.id
                ],
            )
            for region in REGIONS.values()
        ]
    )


@router.get("/api/badges/me", response_model=MyBadgesOut)
def get_my_badges(db: DbSession, user: CurrentUser) -> MyBadgesOut:
    # Checked on every read, so the page never waits for the next background sweep.
    award.award_new(db, user.id, clock.now())
    return _mine(db, user)


@router.post("/api/badges/me/seen", response_model=MyBadgesOut)
def mark_badges_seen(body: BadgesSeenIn, db: DbSession, user: CurrentUser) -> MyBadgesOut:
    award.mark_seen(db, user.id, body.ids)
    return _mine(db, user)


@router.post("/api/badges/me/summary-seen", response_model=MyBadgesOut)
def acknowledge_summary(db: DbSession, user: CurrentUser) -> MyBadgesOut:
    award.acknowledge_summary(db, user)
    return _mine(db, user)


@router.get("/api/users/{username}/badges", response_model=UserBadgesOut)
def get_user_badges(username: str, db: DbSession, user: CurrentUser) -> UserBadgesOut:
    other = db.scalar(select(User).where(User.username == username))
    if other is None:
        raise MarketplaceError("user_not_found", f"There is no user @{username}.", 404)
    return UserBadgesOut(
        username=other.username,
        earned=[EarnedBadgeOut(id=r.badge_id, earned_at=r.earned_at) for r in _earned(db, other.id)],
    )
