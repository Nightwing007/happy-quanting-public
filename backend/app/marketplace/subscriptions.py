"""Subscriptions: a subscriber runs a listing's algorithm on a dedicated paper account, and the
creator is paid a share of the net realized profit above a high-water mark.

The sub-account is funded from the subscriber's live cash and is a normal `kind="algo"` account,
so every order on it goes through the same engine (charges, market hours, shorting rules) as any
other. Strategy execution lives in `marketplace/live.py`; this module is the money and the rules.
"""

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.algos import live_runs
from app.market_data.base import MarketDataProvider
from app.marketplace.listings import MarketplaceError, _load, _market_codes, not_found
from app.models import (
    Account,
    AlgoListing,
    CashTransfer,
    FeeLedger,
    ListingStatus,
    Subscription,
    SubscriptionStatus,
    User,
)
from app.trading import engine
from app.trading.context import TradingContext
from app.trading.money import money

logger = logging.getLogger(__name__)
ZERO = Decimal(0)
HUNDRED = Decimal(100)


# The background loop and a stop request can both reach a subscription at once. Settling a fee or
# returning the cash reads the account, then writes; without this both would pay or return it.
_sub_lock = live_runs.KeyedLocks()


def subscription_not_found(sub_id: int) -> MarketplaceError:
    return MarketplaceError("subscription_not_found", f"There is no subscription {sub_id}.", 404)


def sub_context(db: Session, provider: MarketDataProvider, sub: Subscription) -> TradingContext:
    """The subscription's account on the real clock (looked up per call so a test can replace it)."""
    return live_runs.account_context(db, provider, sub.account_id)


# --- reading -----------------------------------------------------------------------------------


def owned_subscription(db: Session, user: User, sub_id: int) -> Subscription:
    """The subscriber's own subscription; anyone else's is "not found"."""
    found = db.get(Subscription, sub_id)
    if found is None or found.subscriber_user_id != user.id:
        raise subscription_not_found(sub_id)
    return found


def list_subscriptions(db: Session, user: User) -> list[Subscription]:
    return list(
        db.scalars(
            select(Subscription)
            .where(Subscription.subscriber_user_id == user.id)
            .order_by(Subscription.id.desc())
        )
    )


def returned_cash(db: Session, sub: Subscription) -> Decimal:
    """What came back to the live account when the subscription stopped."""
    rows = db.scalars(
        select(CashTransfer.amount).where(
            CashTransfer.subscription_id == sub.id, CashTransfer.kind == "return"
        )
    )
    return sum(rows, ZERO)


def earnings(db: Session, creator: User) -> list[dict]:
    """Per listing of the creator's: fees received and how many subscribers (a count, never who)."""
    out = []
    for listing in db.scalars(
        select(AlgoListing).where(AlgoListing.owner_user_id == creator.id).order_by(AlgoListing.id)
    ):
        subs = list(db.scalars(select(Subscription).where(Subscription.listing_id == listing.id)))
        rows = db.scalars(select(FeeLedger).where(FeeLedger.subscription_id.in_([s.id for s in subs])))
        out.append(
            dict(
                listing_id=listing.id,
                name=listing.name,
                subscribers=len({s.subscriber_user_id for s in subs}),
                active_subscribers=len(
                    {s.subscriber_user_id for s in subs if s.status != SubscriptionStatus.STOPPED}
                ),
                fees_received=sum((r.amount for r in rows), ZERO),  # Python sum: amounts are Decimal text
            )
        )
    return out


# --- subscribing -------------------------------------------------------------------------------


def subscribe(
    db: Session,
    provider: MarketDataProvider,
    user: User,
    listing_id: int,
    symbols: list[str],
    capital: Decimal,
) -> Subscription:
    """Fund a new sub-account from the user's live cash and record the subscription. The
    algorithm starts on the next pass of the background loop."""
    listing = _load(db, listing_id)
    if listing.owner_user_id == user.id:
        raise MarketplaceError("own_listing", "You can't subscribe to your own listing.")
    if listing.status != ListingStatus.PUBLISHED:
        raise not_found(listing_id)  # a draft or retired listing is invisible to everyone else

    def err(code: str, message: str) -> MarketplaceError:
        return MarketplaceError(code, message)

    names = live_runs.clean_symbols(symbols, err)
    live = engine.account_for_user(db, user.id)
    live_runs.check_symbols(provider, live, names, _market_codes(listing.markets), err)
    capital = live_runs.check_capital(live, capital, err)

    now = clock.now()
    account = live_runs.open_account(db, live, user.id, capital)
    sub = Subscription(
        subscriber_user_id=user.id, listing_id=listing.id, listing_version=listing.version, symbols=names,
        capital=capital, account_id=account.id, fee_percent=listing.fee_percent, high_water_mark=ZERO,
        fees_paid=ZERO, status=SubscriptionStatus.ACTIVE, created_at=now,
    )  # fmt: skip
    db.add(sub)
    db.flush()
    db.add(CashTransfer(subscription_id=sub.id, kind="fund", amount=capital, created_at=now))
    db.commit()
    return sub


def upgrade(db: Session, user: User, sub_id: int) -> Subscription:
    """Move a subscription to the listing's latest version. The subscriber opts in; nothing else
    ever changes the version they run. Only a published listing's newer version is on offer, and
    the strategy is rebuilt from the new code on the next pass of the loop (its memory is lost)."""
    from app.marketplace import live  # imported here: live reads this module

    sub = owned_subscription(db, user, sub_id)
    if sub.status != SubscriptionStatus.ACTIVE:
        raise MarketplaceError("subscription_not_active", "Only a running subscription can be upgraded.", 409)
    listing = _load(db, sub.listing_id)
    if listing.status != ListingStatus.PUBLISHED or listing.version == sub.listing_version:
        raise MarketplaceError("no_upgrade", "You already run the latest published version.", 409)
    sub.listing_version = listing.version
    db.commit()
    live.drop(sub.id)
    return sub


# --- the profit share --------------------------------------------------------------------------


def settle_fees(db: Session, sub: Subscription) -> FeeLedger | None:
    """Pay the creator their share of realized profit above the high-water mark.

    Profit is the sub-account's `realized_pnl` (it already holds charges and financing), so an
    open trade's unrealized gain is never charged. The mark only rises: a loss then a recovery to
    the old level owes nothing, so the same profit is never charged twice.
    """
    with _sub_lock(sub.id):
        return _settle_fees_locked(db, sub)


def _settle_fees_locked(db: Session, sub: Subscription) -> FeeLedger | None:
    db.refresh(sub)  # another thread may have settled while we waited
    account = db.get(Account, sub.account_id, populate_existing=True)
    assert account is not None
    profit, mark = account.realized_pnl, sub.high_water_mark
    if profit <= mark:
        return None
    owed = money((profit - mark) * sub.fee_percent / HUNDRED)
    # Realized profit can sit in open positions, leaving less cash than the fee. The creator gets
    # what is available now and the shortfall is recorded, not carried: the mark still moves to
    # `profit`, because keeping it back would charge the same profit again once cash frees up.
    paid = min(owed, max(ZERO, account.cash - account.margin_used))
    listing = db.get(AlgoListing, sub.listing_id)
    assert listing is not None
    row = None
    if owed > 0:
        account.cash -= paid
        engine.account_for_user(db, listing.owner_user_id).cash += paid
        row = FeeLedger(
            subscription_id=sub.id, creator_user_id=listing.owner_user_id,
            subscriber_user_id=sub.subscriber_user_id, amount=paid, shortfall=owed - paid,
            profit_before=mark,  # no row is written while profit is at or below the mark
            profit_after=profit, hwm_before=mark, hwm_after=profit, fee_percent=sub.fee_percent,
            created_at=clock.now(),
        )  # fmt: skip
        db.add(row)
        sub.fees_paid += paid
    sub.high_water_mark = profit
    db.commit()
    return row


# --- stopping ----------------------------------------------------------------------------------


def advance_stop(db: Session, provider: MarketDataProvider, sub: Subscription) -> bool:
    """Move a stopping subscription forward: exit what is open, settle the final fee, and once the
    account is flat return its cash to the live account. Returns whether it is now stopped."""
    with _sub_lock(sub.id):
        return _advance_stop_locked(db, provider, sub)


def _advance_stop_locked(db: Session, provider: MarketDataProvider, sub: Subscription) -> bool:
    db.refresh(sub)
    if sub.status == SubscriptionStatus.STOPPED:
        return True  # the other thread finished it: the cash is already back
    ctx = sub_context(db, provider, sub)
    db.refresh(ctx.account)
    live_runs.wind_down(ctx)
    settle_fees(db, sub)
    if not live_runs.is_flat(ctx):
        return False
    live_runs.return_cash(db, ctx.account, sub.subscriber_user_id, {"subscription_id": sub.id})
    sub.status = SubscriptionStatus.STOPPED
    sub.stopped_at = clock.now()
    db.commit()
    return True


def stop(db: Session, provider: MarketDataProvider, user: User, sub_id: int) -> Subscription:
    """Stop trading and wind the account down. If an exit has to wait for the market to open the
    subscription stays `stopping` and the background loop finishes it."""
    from app.marketplace import live  # imported here: live reads this module

    sub = owned_subscription(db, user, sub_id)
    if sub.status == SubscriptionStatus.STOPPED:
        return sub
    sub.status = SubscriptionStatus.STOPPING
    db.commit()
    live.drop(sub.id)  # the strategy no longer decides anything; close its sandbox child
    advance_stop(db, provider, sub)
    return sub
