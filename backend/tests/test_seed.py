"""The demo marketplace: five persona creators with uploaded-code listings. Seeding only queues
performance (the worker measures it), so no backtest runs here."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.algos.validate import validate_and_dry_run
from app.market_data.fake import FakeProvider
from app.marketplace.seed import SEED_CREATORS, SEED_DIR, seed_marketplace
from app.models import Account, AlgoListing, ListingStatus, User

# A line of code that appears only in that file, so finding it in a response means code leaked.
DISTINCT_LINES = {
    "zangoose.py": "channel_high = max(highs[-p[",
    "slowking.py": "fast = statistics.fmean(closes[-p[",
    "shuckle.py": "pulled_back = all(recent[i + 1] < recent[i]",
    "sharpedo.py": "rsi = ctx.indicators.rsi(closes, p[",
    "electrode.py": "if close > previous + atr * p[",
}
INTERVALS = {"zangoose.py": "1h", "slowking.py": "1wk", "shuckle.py": "1d"}
INTERVALS |= {"sharpedo.py": "1d", "electrode.py": "1h"}
DEX = {"zangoose": 335, "slowking": 199, "shuckle": 213, "sharpedo": 319, "electrode": 101}


def source_of(file: str) -> str:
    return (SEED_DIR / file).read_text(encoding="utf-8")


@pytest.mark.parametrize("spec", SEED_CREATORS, ids=lambda s: s.file)
def test_every_seed_file_passes_the_upload_checks(spec):
    report = validate_and_dry_run(source_of(spec.file))
    assert report.ok, report.problems
    assert report.meta.interval == INTERVALS[spec.file]
    assert DISTINCT_LINES[spec.file] in source_of(spec.file)


def test_seeding_twice_makes_five_users_and_five_published_listings(db: Session, fake_provider: FakeProvider):
    first = seed_marketplace(db, fake_provider)
    second = seed_marketplace(db, fake_provider)
    assert [x.id for x in first] == [x.id for x in second]
    creators = db.scalars(select(User).where(User.is_creator.is_(True))).all()
    assert sorted(u.username for u in creators) == sorted(DEX)
    listings = db.scalars(select(AlgoListing)).all()
    assert len(listings) == 5 and all(x.status == ListingStatus.PUBLISHED for x in listings)
    for user in creators:  # one live account each
        assert db.scalar(select(func.count()).select_from(Account).where(Account.user_id == user.id)) == 1


def test_avatars_and_bios(db: Session, fake_provider: FakeProvider):
    seed_marketplace(db, fake_provider)
    for user in db.scalars(select(User)):
        assert user.avatar_url == (
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/"
            f"official-artwork/{DEX[user.username]}.png"
        )
        assert user.bio and user.display_name == user.username.capitalize()


def test_creators_cannot_log_in(client: TestClient, db: Session, fake_provider: FakeProvider):
    seed_marketplace(db, fake_provider)
    for name in DEX:
        r = client.post("/api/auth/login", json={"username": name, "password": "!"})
        assert r.status_code == 401


def test_listings_are_public_and_never_show_the_code(
    client: TestClient, second_client: TestClient, db: Session, fake_provider: FakeProvider
):
    seed_marketplace(db, fake_provider)
    r = second_client.get("/api/marketplace/listings")
    assert r.status_code == 200
    rows = r.json()
    assert sorted(x["creator"]["username"] for x in rows) == sorted(DEX)
    text = json.dumps(rows)
    for line in DISTINCT_LINES.values():
        assert line not in text
    for row in rows:
        detail = second_client.get(f"/api/marketplace/listings/{row['id']}")
        assert detail.status_code == 200
        for line in DISTINCT_LINES.values():
            assert line not in detail.text
        assert not {"source", "params", "strategy_key"} & detail.json().keys()
