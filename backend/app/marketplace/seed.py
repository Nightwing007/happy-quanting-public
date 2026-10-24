"""The five demo creators and their listings, so the marketplace is never empty. Each strategy is
written as uploaded code (`backend/seed/algos/`) and goes through the same checks as anyone's.
Safe to run again: users and listings are matched by username and listing name."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.algos.validate import validate_source
from app.market_data.base import MarketDataProvider
from app.marketplace import listings
from app.models import Account, AccountKind, AlgoListing, User
from app.trading.engine import create_live_account

SEED_DIR = Path(__file__).resolve().parents[2] / "seed" / "algos"
# Loaded by the browser at runtime, never stored in the repo (see DECISIONS).
AVATAR_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{dex}.png"


@dataclass(frozen=True)
class SeedCreator:
    file: str
    display_name: str
    dex: int
    bio: str
    listing_name: str
    tagline: str
    markets: tuple[str, ...]
    test_symbols: tuple[str, ...]
    fee_percent: str

    @property
    def username(self) -> str:
        return self.display_name.lower()


SEED_CREATORS = (
    SeedCreator(
        "zangoose.py", "Zangoose", 335,
        "I hunt fast breakouts and cut losers quickly; ten small stops beat missing one big run.",
        "Hourly momentum breakout", "Breakouts on hourly bars, long and short, tight stops.",
        ("india", "international"), ("RELIANCE.NS", "AAPL"), "25",
    ),
    SeedCreator(
        "slowking.py", "Slowking", 199,
        "I check the chart once a week and trade a handful of times a year; patience is my edge.",
        "Weekly trend follower", "Long-only weekly trends, a few trades a year.",
        ("india", "international"), ("AAPL", "MSFT", "SPY"), "10",
    ),
    SeedCreator(
        "shuckle.py", "Shuckle", 213,
        "I protect capital first: small positions, a hard stop on every trade, and only in rising markets.",
        "Uptrend dip buyer", "Small dips in uptrends, small positions, a stop on each.",
        ("india",), ("TCS.NS", "HDFCBANK.NS", "RELIANCE.NS"), "12",
    ),
    SeedCreator(
        "sharpedo.py", "Sharpedo", 319,
        "I wait for the crowd to panic, buy the washout and sell when price returns to its average.",
        "Oversold ambush", "Buys deep oversold drops and sells at the average.",
        ("india", "international"), ("AAPL", "RELIANCE.NS"), "20",
    ),
    SeedCreator(
        "electrode.py", "Electrode", 101,
        "I trade crypto's sudden bursts in both directions, around the clock, with a fixed stop and target.",
        "Crypto ATR breakout", "Volatility breakouts in crypto, both directions, 24/7.",
        ("crypto",), ("BTC-USD", "ETH-USD"), "30",
    ),
)  # fmt: skip


def _creator(db: Session, spec: SeedCreator) -> User:
    user = db.scalar(select(User).where(User.username == spec.username))
    if user is None:
        user = User(
            username=spec.username,
            display_name=spec.display_name,
            avatar_url=AVATAR_URL.format(dex=spec.dex),
            bio=spec.bio,
            # "!" is never a valid hash, so nobody can log in as a demo persona.
            password_hash="!",
            is_creator=True,
            created_at=clock.now(),
        )
        db.add(user)
        db.commit()
    has_live = select(Account.id).where(Account.user_id == user.id, Account.kind == AccountKind.LIVE)
    if db.scalar(has_live) is None:
        create_live_account(db, user_id=user.id)
    return user


def seed_marketplace(db: Session, provider: MarketDataProvider) -> list[AlgoListing]:
    """Make whatever is missing and return the five listings. A new listing is published, which
    queues its performance for the background worker."""
    out = []
    for spec in SEED_CREATORS:
        user = _creator(db, spec)
        listing = db.scalar(
            select(AlgoListing).where(
                AlgoListing.owner_user_id == user.id, AlgoListing.name == spec.listing_name
            )
        )
        if listing is None:
            source = (SEED_DIR / spec.file).read_text(encoding="utf-8")
            listing = listings.create_listing(
                db, user,
                name=spec.listing_name, tagline=spec.tagline, description=_description(source),
                markets=list(spec.markets), test_symbols=list(spec.test_symbols),
                fee_percent=Decimal(spec.fee_percent), from_source=source,
            )  # fmt: skip
            listings.publish_listing(db, provider, user, listing.id)
        out.append(listing)
    return out


def _description(source: str) -> str:
    """The strategy's own `description` text, so the listing says what the code is documented to do."""
    report = validate_source(source)
    assert report.meta is not None
    return report.meta.description
