"""Algorithm listings: create, edit, publish, retire and who may see what.

A listing's code reference (`source`, or `strategy_key` + `params`) never leaves this layer
except to its owner: every public view is built field by field in `api/marketplace.py`.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.algos.api import validate_params
from app.algos.library import LIBRARY
from app.algos.validate import Problem, validate_source
from app.market_data.base import MarketDataError, MarketDataProvider
from app.market_data.history import LIMITS
from app.models import AlgoListing, ListingPerformance, ListingStatus, ListingVersion, User, UserAlgo
from app.sim.runner import MAX_SYMBOLS, _instrument
from app.trading.markets import MARKETS, market_for

MAX_FEE_PERCENT = Decimal(50)
MAX_CHANGELOG = 500
SEGMENTS = ("india", "international", "crypto")


class MarketplaceError(Exception):
    """A listing request that can't be honoured. `code` is what clients branch on; `problems`
    carries the line-numbered findings when the code is refused."""

    def __init__(
        self, code: str, message: str, status_code: int = 400, problems: list[Problem] | None = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.problems = problems or []


def not_found(listing_id: int) -> MarketplaceError:
    return MarketplaceError("listing_not_found", f"There is no listing {listing_id}.", 404)


def _plain(value):
    return f"{value:f}" if isinstance(value, Decimal) else value


# --- checks ------------------------------------------------------------------------------------


def check_source(source: str):
    """The strategy's meta when `source` passes the code rules; otherwise raises with every
    problem, each worded with its line."""
    report = validate_source(source)
    if not report.ok or report.meta is None:
        text = " ".join(p.message for p in report.problems)
        raise MarketplaceError("invalid_source", f"The code breaks the rules: {text}", 400, report.problems)
    return report.meta


def _check_fee(fee: Decimal) -> Decimal:
    if not fee.is_finite() or fee < 0 or fee > MAX_FEE_PERCENT:
        raise MarketplaceError(
            "fee_out_of_range", f"The fee must be between 0 and {MAX_FEE_PERCENT}% of net profit."
        )
    return fee


def _check_markets(markets: list[str]) -> list[str]:
    out: list[str] = []
    for raw in markets:
        text = raw.strip()
        if text.lower() in SEGMENTS:
            code = text.lower()
        elif text.upper() in MARKETS:
            code = text.upper()
        else:
            raise MarketplaceError(
                "unknown_market",
                f"'{raw}' is not a market. Use a segment ({', '.join(SEGMENTS)}) or a market code.",
            )
        if code not in out:
            out.append(code)
    if not out:
        raise MarketplaceError("unknown_market", "Pick at least one market the algorithm supports.")
    return out


def _check_symbols(symbols: list[str]) -> list[str]:
    out = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    if len(out) > MAX_SYMBOLS:
        raise MarketplaceError("too_many_symbols", f"Pick at most {MAX_SYMBOLS} test symbols.")
    return out


def _check_interval(interval: str) -> str:
    if interval not in LIMITS:
        raise MarketplaceError(
            "invalid_interval", f"Interval '{interval}' isn't available. Choose one of: {', '.join(LIMITS)}."
        )
    return interval


def _market_codes(markets: list[str]) -> set[str]:
    """Market codes behind a mix of segments and codes."""
    codes: set[str] = set()
    for m in markets:
        codes |= {c for c, mk in MARKETS.items() if mk.segment == m} if m in SEGMENTS else {m}
    return codes


def check_test_markets(provider: MarketDataProvider, listing: AlgoListing) -> None:
    """Each test symbol must trade on one of the listing's markets."""
    allowed = _market_codes(listing.markets)
    for symbol in listing.test_symbols:
        try:
            inst = _instrument(provider, symbol)
            market = market_for(inst.symbol, inst.type)
        except MarketDataError as why:
            raise MarketplaceError("test_symbol_unknown", f"Test symbol {symbol}: {why.message}") from why
        if market.code not in allowed:
            raise MarketplaceError(
                "test_symbol_market",
                f"Test symbol {symbol} trades on {market.name}, which the listing doesn't support.",
            )


def _interval_sentence(built_for: str, asked: str) -> str:
    return f"The algorithm is built for {built_for} bars, so it can't be listed on {asked} bars."


def _algo_class(strategy_key: str):
    algo = LIBRARY.get(strategy_key)
    if algo is None:
        raise MarketplaceError("unknown_algorithm", f"There is no algorithm '{strategy_key}'.")
    return algo


# --- reading -----------------------------------------------------------------------------------


def _load(db: Session, listing_id: int) -> AlgoListing:
    found = db.get(AlgoListing, listing_id)
    if found is None:
        raise not_found(listing_id)
    return found


def owned_listing(db: Session, owner: User, listing_id: int) -> AlgoListing:
    """The owner's listing; anyone else's is "not found"."""
    found = _load(db, listing_id)
    if found.owner_user_id != owner.id:
        raise not_found(listing_id)
    return found


def get_listing_for(db: Session, viewer: User, listing_id: int) -> AlgoListing:
    """A published listing, or one's own in any state; a draft or retired one of someone else's is
    "not found"."""
    found = _load(db, listing_id)
    if found.owner_user_id != viewer.id and found.status != ListingStatus.PUBLISHED:
        raise not_found(listing_id)
    return found


def list_published(
    db: Session, market: str | None = None, creator: str | None = None
) -> list[AlgoListing]:
    query = select(AlgoListing).where(AlgoListing.status == ListingStatus.PUBLISHED)
    if creator is not None:
        # Usernames are stored lower-cased; an unknown one simply matches nothing.
        query = query.join(User, User.id == AlgoListing.owner_user_id).where(
            User.username == creator.strip().lower()
        )
    rows = db.scalars(query.order_by(AlgoListing.id.desc()))
    if market is None:
        return list(rows)
    text = market.strip()
    wanted = _market_codes([text.lower() if text.lower() in SEGMENTS else text.upper()])
    return [r for r in rows if _market_codes(r.markets) & wanted]


def list_mine(db: Session, owner: User) -> list[AlgoListing]:
    return list(
        db.scalars(
            select(AlgoListing).where(AlgoListing.owner_user_id == owner.id).order_by(AlgoListing.id.desc())
        )
    )


def versions_of(db: Session, listing: AlgoListing) -> list[ListingVersion]:
    """Every version, oldest first. Callers publish only the number, date and changelog."""
    return list(
        db.scalars(
            select(ListingVersion)
            .where(ListingVersion.listing_id == listing.id)
            .order_by(ListingVersion.version)
        )
    )


def code_for(db: Session, listing_id: int, version: int) -> tuple[str | tuple[str, dict], str]:
    """What to run for one version of a listing: `(source, interval)` for uploaded code, or
    `((strategy_key, params), interval)` for a library algorithm. Server-side only; a subscriber
    runs the version they are pinned to, whatever the listing's current one is."""
    row = db.scalar(
        select(ListingVersion).where(
            ListingVersion.listing_id == listing_id, ListingVersion.version == version
        )
    )
    if row is None:
        raise MarketplaceError("version_not_found", f"Listing {listing_id} has no version {version}.", 404)
    if row.source is not None:
        return row.source, row.interval
    assert row.strategy_key is not None
    return (row.strategy_key, dict(row.params or {})), row.interval


def performance_rows(db: Session, listing: AlgoListing) -> list[ListingPerformance]:
    """The windows of the latest version (the one a new subscriber gets), oldest row first."""
    return list(
        db.scalars(
            select(ListingPerformance)
            .where(ListingPerformance.listing_id == listing.id, ListingPerformance.version == listing.version)
            .order_by(ListingPerformance.id)
        )
    )


# --- writing -----------------------------------------------------------------------------------


def _record_version(db: Session, listing: AlgoListing, changelog: str | None) -> None:
    """Keep this version's code; every subscriber pins to one of these rows."""
    db.add(
        ListingVersion(
            listing_id=listing.id, version=listing.version, source=listing.source,
            strategy_key=listing.strategy_key, params=listing.params, interval=listing.interval,
            changelog=changelog, created_at=clock.now(),
        )  # fmt: skip
    )


def create_listing(
    db: Session,
    owner: User,
    *,
    name: str,
    markets: list[str],
    fee_percent: Decimal,
    tagline: str = "",
    description: str = "",
    test_symbols: list[str] | None = None,
    interval: str | None = None,
    from_source: str | None = None,
    from_user_algo_id: int | None = None,
) -> AlgoListing:
    """A draft listing, from uploaded code or from one of the owner's saved algorithms (whose
    library key and settings are copied, so later edits to the saved algorithm don't change it)."""
    if (from_source is None) == (from_user_algo_id is None):
        raise MarketplaceError(
            "invalid_form", "Give either code or a saved algorithm, not both and not neither."
        )
    source = strategy_key = params = None
    if from_source is not None:
        default_interval = check_source(from_source).interval
        source = from_source
    else:
        saved = db.get(UserAlgo, from_user_algo_id)
        if saved is None or saved.owner_user_id != owner.id:
            raise MarketplaceError("algo_not_found", f"There is no saved algorithm {from_user_algo_id}.", 404)
        if saved.source is not None:  # editor code is listed as uploaded code
            default_interval = check_source(saved.source).interval
            source = saved.source
        else:
            default_interval = _algo_class(saved.strategy_key).interval
            strategy_key, params = saved.strategy_key, dict(saved.params)
    if interval is not None and interval != default_interval:
        raise MarketplaceError("interval_mismatch", _interval_sentence(default_interval, interval))
    now = clock.now()
    listing = AlgoListing(
        owner_user_id=owner.id,
        name=name.strip(),
        tagline=tagline,
        description=description,
        markets=_check_markets(markets),
        test_symbols=_check_symbols(test_symbols or []),
        interval=_check_interval(default_interval),
        fee_percent=_check_fee(fee_percent),
        status=ListingStatus.DRAFT,
        source=source,
        strategy_key=strategy_key,
        params=params,
        version=1,
        created_at=now,
        updated_at=now,
    )
    owner.is_creator = True
    db.add(listing)
    db.flush()
    _record_version(db, listing, None)
    db.commit()
    return listing


def update_listing(db: Session, owner: User, listing_id: int, changes: dict[str, Any]) -> AlgoListing:
    """Apply the fields in `changes`. New code or new settings bump `version` and keep the new
    code as a `ListingVersion` (with `changelog`, if given); a published listing then has its
    performance measured again for that version. Subscribers stay on their version until they upgrade."""
    from app.marketplace import performance  # imported here: performance reads this module

    listing = owned_listing(db, owner, listing_id)
    if listing.status == ListingStatus.RETIRED:
        raise MarketplaceError("listing_retired", "A retired listing can't be changed.", 409)
    changelog = changes.get("changelog")
    if changelog is not None and len(changelog) > MAX_CHANGELOG:
        raise MarketplaceError("changelog_too_long", f"A changelog is at most {MAX_CHANGELOG} characters.")
    bumped = False
    if changes.get("source") is not None:
        if listing.source is None:
            raise MarketplaceError(
                "invalid_form", "This listing is built from a saved algorithm; it has no code to replace."
            )
        meta = check_source(changes["source"])
        if changes["source"] != listing.source:
            listing.source, bumped = changes["source"], True
            listing.interval = meta.interval  # the code decides which bars it reads
    if changes.get("params") is not None:
        if listing.strategy_key is None:
            raise MarketplaceError(
                "invalid_form", "This listing is built from code; it has no settings to change."
            )
        values = validate_params(_algo_class(listing.strategy_key), changes["params"])
        new = {k: _plain(v) for k, v in values.items()}
        if new != listing.params:
            listing.params, bumped = new, True
    if changes.get("name") is not None:
        listing.name = changes["name"].strip()
    for field in ("tagline", "description"):
        if changes.get(field) is not None:
            setattr(listing, field, changes[field])
    if changes.get("markets") is not None:
        listing.markets = _check_markets(changes["markets"])
    if changes.get("test_symbols") is not None:
        listing.test_symbols = _check_symbols(changes["test_symbols"])
    if changes.get("interval") is not None:
        built_for = (
            check_source(listing.source).interval
            if listing.source is not None
            else _algo_class(listing.strategy_key).interval
        )
        if changes["interval"] != built_for:
            raise MarketplaceError("interval_mismatch", _interval_sentence(built_for, changes["interval"]))
    if changes.get("fee_percent") is not None:
        listing.fee_percent = _check_fee(changes["fee_percent"])
    if bumped:
        listing.version += 1
        _record_version(db, listing, changelog or None)
    listing.updated_at = clock.now()
    db.commit()
    measured_inputs = bumped or any(changes.get(k) is not None for k in ("test_symbols", "interval"))
    if listing.status == ListingStatus.PUBLISHED and measured_inputs:
        performance.queue_performance(db, listing)
    return listing


def _ready(listing: AlgoListing) -> None:
    """Whether the listing could be measured and sold; raises with the first thing missing."""
    if listing.source is not None:
        check_source(listing.source)
    elif listing.strategy_key is None or listing.params is None:
        raise MarketplaceError("invalid_form", "The listing has no code.")
    if not listing.test_symbols:
        raise MarketplaceError(
            "no_test_symbols", "Pick at least one test symbol to measure the performance on."
        )
    _check_fee(listing.fee_percent)


def publish_listing(db: Session, provider: MarketDataProvider, owner: User, listing_id: int) -> AlgoListing:
    from app.marketplace import performance

    listing = owned_listing(db, owner, listing_id)
    if listing.status == ListingStatus.RETIRED:
        raise MarketplaceError("listing_retired", "A retired listing can't be published again.", 409)
    _ready(listing)
    check_test_markets(provider, listing)
    listing.status = ListingStatus.PUBLISHED
    listing.updated_at = clock.now()
    db.commit()
    performance.queue_performance(db, listing)
    return listing


def retire_listing(db: Session, owner: User, listing_id: int) -> AlgoListing:
    listing = owned_listing(db, owner, listing_id)
    listing.status = ListingStatus.RETIRED
    listing.updated_at = clock.now()
    db.commit()
    return listing


def refresh_performance(
    db: Session, provider: MarketDataProvider, owner: User, listing_id: int
) -> AlgoListing:
    from app.marketplace import performance

    listing = owned_listing(db, owner, listing_id)
    if listing.status == ListingStatus.RETIRED:
        raise MarketplaceError("listing_retired", "A retired listing has no performance to refresh.", 409)
    _ready(listing)
    check_test_markets(provider, listing)
    performance.queue_performance(db, listing)
    return listing
