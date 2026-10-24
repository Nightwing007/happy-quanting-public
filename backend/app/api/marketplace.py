"""The marketplace: listings of algorithms, with server-measured performance and never the code.

Every public model here is built field by field from the row, never with `model_validate`, so a
column added to `AlgoListing` later can't reach a buyer by accident. Only `/mine` builds
`ListingOwnerOut`, which carries the code reference.
"""

from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Provider
from app.badges.award import creator_badges
from app.marketplace import listings, performance, subscriptions
from app.marketplace.performance import HEADLINE_ORDER
from app.models import (
    AlgoListing,
    ListingPerformance,
    ListingStatus,
    PerformanceStatus,
    Subscription,
    SubscriptionStatus,
    User,
)
from app.schemas import (
    CreatorProfileOut,
    EarningsOut,
    ListingCreatorOut,
    ListingDetailOut,
    ListingEarningsOut,
    ListingIn,
    ListingOwnerOut,
    ListingPerformanceOut,
    ListingPublicOut,
    ListingUpdateIn,
    ListingVersionOut,
    PerformanceResultsOut,
    SubscribeIn,
    SubscriptionOut,
)
from app.trading import engine

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


def _performance_out(row: ListingPerformance) -> ListingPerformanceOut:
    return ListingPerformanceOut(
        window=row.window,  # type: ignore[arg-type]
        start=row.start,
        end=row.end,
        status=row.status,  # type: ignore[arg-type]
        # A window that will be tried again shows a calm sentence, not the raw data error.
        note=performance.WAITING_NOTE if performance.is_waiting_to_retry(row) else row.note,
        computed_at=row.computed_at,
        results=PerformanceResultsOut.model_validate(row.results) if row.results else None,
    )


def _headline(rows: list[ListingPerformance]) -> ListingPerformanceOut | None:
    done = {r.window: r for r in rows if r.status == PerformanceStatus.DONE}
    for window in HEADLINE_ORDER:
        if window in done:
            return _performance_out(done[window])
    return None


def _public_fields(db: DbSession, listing: AlgoListing, rows: list[ListingPerformance]) -> dict:
    creator = db.get(User, listing.owner_user_id)
    assert creator is not None
    return dict(
        id=listing.id,
        name=listing.name,
        tagline=listing.tagline,
        description=listing.description,
        markets=list(listing.markets),
        interval=listing.interval,
        fee_percent=listing.fee_percent,
        version=listing.version,
        status=listing.status,
        creator=ListingCreatorOut(
            id=creator.id,
            username=creator.username,
            display_name=creator.display_name,
            avatar_url=creator.avatar_url,
            badges=creator_badges(db, creator.id),
        ),
        headline=_headline(rows),
    )  # fmt: skip


def _public(db: DbSession, listing: AlgoListing) -> ListingPublicOut:
    return ListingPublicOut(**_public_fields(db, listing, listings.performance_rows(db, listing)))


def _versions(db: DbSession, listing: AlgoListing) -> list[ListingVersionOut]:
    # Field by field: the row also holds the version's code.
    return [
        ListingVersionOut(version=v.version, created_at=v.created_at, changelog=v.changelog)
        for v in listings.versions_of(db, listing)
    ]


def _detail(db: DbSession, listing: AlgoListing) -> ListingDetailOut:
    rows = listings.performance_rows(db, listing)
    return ListingDetailOut(
        **_public_fields(db, listing, rows),
        performance=[_performance_out(r) for r in rows],
        versions=_versions(db, listing),
    )


def _owner(db: DbSession, listing: AlgoListing) -> ListingOwnerOut:
    rows = listings.performance_rows(db, listing)
    return ListingOwnerOut(
        **_public_fields(db, listing, rows),
        performance=[_performance_out(r) for r in rows],
        versions=_versions(db, listing),
        test_symbols=list(listing.test_symbols),
        source=listing.source,
        strategy_key=listing.strategy_key,
        params=listing.params,
        created_at=listing.created_at,
        updated_at=listing.updated_at,
    )


@router.get("/listings", response_model=list[ListingPublicOut])
def list_listings(
    db: DbSession,
    user: CurrentUser,
    market: str | None = Query(default=None, description="A segment (india) or market code (NSE)"),
    creator: str | None = Query(default=None, description="Only this creator's listings (username)"),
):
    return [_public(db, row) for row in listings.list_published(db, market, creator)]


@router.get("/creators/{username}", response_model=CreatorProfileOut)
def get_creator(username: str, db: DbSession, user: CurrentUser):
    found = db.scalar(select(User).where(User.username == username.strip().lower()))
    if found is None:
        raise listings.MarketplaceError("creator_not_found", f"There is no creator @{username}.", 404)
    count = db.scalar(
        select(func.count())
        .select_from(AlgoListing)
        .where(AlgoListing.owner_user_id == found.id, AlgoListing.status == ListingStatus.PUBLISHED)
    )
    return CreatorProfileOut(
        username=found.username,
        display_name=found.display_name,
        avatar_url=found.avatar_url,
        bio=found.bio,
        listing_count=count or 0,
    )


@router.get("/listings/{listing_id}", response_model=ListingDetailOut)
def get_listing(listing_id: int, db: DbSession, user: CurrentUser):
    return _detail(db, listings.get_listing_for(db, user, listing_id))


@router.get("/mine", response_model=list[ListingOwnerOut])
def my_listings(db: DbSession, user: CurrentUser):
    return [_owner(db, row) for row in listings.list_mine(db, user)]


@router.post("/listings", response_model=ListingDetailOut)
def create_listing(body: ListingIn, db: DbSession, user: CurrentUser):
    row = listings.create_listing(
        db, user, name=body.name, tagline=body.tagline, description=body.description,
        markets=body.markets, test_symbols=body.test_symbols, interval=body.interval,
        fee_percent=body.fee_percent, from_source=body.source, from_user_algo_id=body.user_algo_id,
    )  # fmt: skip
    return _detail(db, row)


@router.put("/listings/{listing_id}", response_model=ListingDetailOut)
def update_listing(listing_id: int, body: ListingUpdateIn, db: DbSession, user: CurrentUser):
    return _detail(db, listings.update_listing(db, user, listing_id, body.model_dump(exclude_unset=True)))


@router.post("/listings/{listing_id}/publish", response_model=ListingDetailOut)
def publish_listing(listing_id: int, db: DbSession, provider: Provider, user: CurrentUser):
    return _detail(db, listings.publish_listing(db, provider, user, listing_id))


@router.post("/listings/{listing_id}/retire", response_model=ListingDetailOut)
def retire_listing(listing_id: int, db: DbSession, user: CurrentUser):
    return _detail(db, listings.retire_listing(db, user, listing_id))


@router.post("/listings/{listing_id}/refresh-performance", response_model=ListingDetailOut)
def refresh_performance(listing_id: int, db: DbSession, provider: Provider, user: CurrentUser):
    return _detail(db, listings.refresh_performance(db, provider, user, listing_id))


# --- subscriptions -------------------------------------------------------------------------------


def _subscription_out(db: DbSession, provider: Provider, sub: Subscription) -> SubscriptionOut:
    listing = db.get(AlgoListing, sub.listing_id)
    assert listing is not None
    ctx = subscriptions.sub_context(db, provider, sub)
    if sub.status == SubscriptionStatus.STOPPED:
        # Flat and emptied: what came back is the final worth, and nothing is left unrealized.
        equity, unrealized = subscriptions.returned_cash(db, sub), Decimal(0)
    else:
        portfolio = engine.get_portfolio(ctx)
        equity, unrealized = portfolio.total_value, portfolio.unrealized_pnl
    return SubscriptionOut(
        id=sub.id,
        listing_id=sub.listing_id,
        listing_name=listing.name,
        listing_version=sub.listing_version,
        latest_version=listing.version,
        upgrade_available=sub.status == SubscriptionStatus.ACTIVE
        and listing.status == ListingStatus.PUBLISHED
        and listing.version != sub.listing_version,
        symbols=list(sub.symbols),
        status=sub.status,  # type: ignore[arg-type]
        currency=ctx.account.currency,
        capital=sub.capital,
        equity=equity,
        realized_pnl=ctx.account.realized_pnl,
        unrealized_pnl=unrealized,
        fee_percent=sub.fee_percent,
        fees_paid=sub.fees_paid,
        high_water_mark=sub.high_water_mark,
        created_at=sub.created_at,
        stopped_at=sub.stopped_at,
    )


@router.post("/listings/{listing_id}/subscribe", response_model=SubscriptionOut)
def subscribe(listing_id: int, body: SubscribeIn, db: DbSession, provider: Provider, user: CurrentUser):
    sub = subscriptions.subscribe(db, provider, user, listing_id, body.symbols, body.capital)
    return _subscription_out(db, provider, sub)


@router.get("/subscriptions", response_model=list[SubscriptionOut])
def my_subscriptions(db: DbSession, provider: Provider, user: CurrentUser):
    return [_subscription_out(db, provider, sub) for sub in subscriptions.list_subscriptions(db, user)]


@router.post("/subscriptions/{subscription_id}/stop", response_model=SubscriptionOut)
def stop_subscription(subscription_id: int, db: DbSession, provider: Provider, user: CurrentUser):
    return _subscription_out(db, provider, subscriptions.stop(db, provider, user, subscription_id))


@router.post("/subscriptions/{subscription_id}/upgrade", response_model=SubscriptionOut)
def upgrade_subscription(subscription_id: int, db: DbSession, provider: Provider, user: CurrentUser):
    return _subscription_out(db, provider, subscriptions.upgrade(db, user, subscription_id))


@router.get("/earnings", response_model=EarningsOut)
def my_earnings(db: DbSession, user: CurrentUser):
    rows = subscriptions.earnings(db, user)
    return EarningsOut(
        currency=engine.account_for_user(db, user.id).currency,
        total=sum((r["fees_received"] for r in rows), Decimal(0)),
        listings=[ListingEarningsOut(**r) for r in rows],
    )
