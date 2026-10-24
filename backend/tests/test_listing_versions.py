"""Listing versions: each version's code is kept on the server, a subscriber stays on the version
they subscribed to until they upgrade, and no route shows a version's code to anyone else."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app import clock
from app.algos import hq, jobs
from app.algos.library import LIBRARY
from app.main import app
from app.market_data.fake import FakeProvider
from app.marketplace import listings, live
from app.migrate import upgrade_database
from app.models import ListingPerformance, ListingVersion, Subscription, UserAlgo
from tests.test_marketplace import BANNED_NAMES, SMA_SOURCE, _property_names
from tests.test_migrations import _upgrade_to

D = Decimal
SYMBOL = "AAPL"
NOW = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
CALLS: list[str] = []
V1_SENTINEL = "SENTINEL_V1_5c1e88d0"
V2_SENTINEL = "SENTINEL_V2_a7704be3"


class Tagged(hq.Strategy):
    """Logs the text it was configured with, so a test can tell which version's settings ran."""

    name = "Tagged"
    description = "Test strategy."
    markets = ("international",)
    interval = "1d"
    warmup_bars = 0
    PARAMETERS = {"text": hq.Param("choice", "alpha", choices=("alpha", "beta"))}

    def on_bar(self, ctx):
        CALLS.append(ctx.params["text"])


@pytest.fixture(autouse=True)
def tagged(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(LIBRARY, "tagged", Tagged)
    monkeypatch.setattr(clock, "now", lambda: NOW)
    CALLS.clear()
    yield
    live.drop_all()


def user_id(client: TestClient) -> int:
    return client.get("/api/me").json()["id"]


def new_listing(client: TestClient, db: Session, **over) -> dict:
    """A published listing of the creator `client`: library stub `tagged` (text=alpha) unless
    `source` is given."""
    body = dict(
        name="Versioned", markets=["international"], test_symbols=[SYMBOL], fee_percent="10", tagline="t",
        description="d",
    )  # fmt: skip
    if "source" not in over:
        saved = UserAlgo(
            owner_user_id=user_id(client), name="s", strategy_key="tagged", params={"text": "alpha"},
            created_at=NOW,
        )  # fmt: skip
        db.add(saved)
        db.commit()
        body["user_algo_id"] = saved.id
    r = client.post("/api/marketplace/listings", json={**body, **over})
    assert r.status_code == 200, r.text
    listing = r.json()
    assert client.post(f"/api/marketplace/listings/{listing['id']}/publish").status_code == 200
    return listing


def subscribe(client: TestClient, listing_id: int):
    return client.post(
        f"/api/marketplace/listings/{listing_id}/subscribe", json={"symbols": [SYMBOL], "capital": "1000"}
    )


def edit(client: TestClient, listing_id: int, **fields):
    r = client.put(f"/api/marketplace/listings/{listing_id}", json=fields)
    assert r.status_code == 200, r.text
    return r.json()


def rows(db: Session, listing_id: int) -> list[ListingVersion]:
    return list(
        db.scalars(
            select(ListingVersion)
            .where(ListingVersion.listing_id == listing_id)
            .order_by(ListingVersion.version)
        )
    )


# --- keeping each version ------------------------------------------------------------------------


def test_create_then_update_keeps_two_version_rows(client: TestClient, db: Session):
    listing = new_listing(client, db)
    (v1,) = rows(db, listing["id"])
    assert (v1.version, v1.strategy_key, v1.params, v1.interval) == (1, "tagged", {"text": "alpha"}, "1d")
    assert v1.changelog is None

    out = edit(client, listing["id"], params={"text": "beta"}, changelog="Switch to beta")
    assert out["version"] == 2
    v1, v2 = rows(db, listing["id"])
    assert (v1.params, v2.version, v2.params, v2.changelog) == (
        {"text": "alpha"}, 2, {"text": "beta"}, "Switch to beta",
    )  # fmt: skip
    assert listings.code_for(db, listing["id"], 1) == (("tagged", {"text": "alpha"}), "1d")
    assert listings.code_for(db, listing["id"], 2) == (("tagged", {"text": "beta"}), "1d")

    # An edit that changes no code is not a version, and a changelog alone is ignored.
    edit(client, listing["id"], name="Renamed", changelog="nothing new")
    assert len(rows(db, listing["id"])) == 2
    too_long = client.put(f"/api/marketplace/listings/{listing['id']}", json={"changelog": "x" * 501})
    assert too_long.status_code == 422


def test_code_versions_keep_their_own_source(client: TestClient, db: Session):
    listing = new_listing(client, db, source=SMA_SOURCE + f"\n# {V1_SENTINEL}\n")
    edit(client, listing["id"], source=SMA_SOURCE + f"\n# {V2_SENTINEL}\n")
    assert V1_SENTINEL in listings.code_for(db, listing["id"], 1)[0]
    assert V2_SENTINEL in listings.code_for(db, listing["id"], 2)[0]
    with pytest.raises(listings.MarketplaceError) as why:
        listings.code_for(db, listing["id"], 3)
    assert why.value.code == "version_not_found"


def test_public_detail_lists_versions_without_code(
    client: TestClient, second_client: TestClient, db: Session
):
    listing = new_listing(client, db)
    edit(client, listing["id"], params={"text": "beta"}, changelog="Second")
    detail = second_client.get(f"/api/marketplace/listings/{listing['id']}").json()
    assert [(v["version"], v["changelog"]) for v in detail["versions"]] == [(1, None), (2, "Second")]
    assert all(set(v) == {"version", "created_at", "changelog"} for v in detail["versions"])
    assert detail["version"] == 2


def test_public_performance_is_the_latest_versions(client: TestClient, db: Session):
    listing = new_listing(client, db)
    versions = {r.version for r in db.scalars(select(ListingPerformance))}
    assert versions == {1}
    edit(client, listing["id"], params={"text": "beta"})
    assert {r.version for r in db.scalars(select(ListingPerformance))} == {2}
    assert len(client.get(f"/api/marketplace/listings/{listing['id']}").json()["performance"]) == 3


# --- subscribers stay put until they upgrade -----------------------------------------------------


def test_a_subscriber_keeps_running_their_version_until_they_upgrade(
    client: TestClient, second_client: TestClient, db: Session, fake_provider: FakeProvider
):
    listing = new_listing(second_client, db)  # creator: other; subscriber: tester
    sub = subscribe(client, listing["id"]).json()
    assert (sub["listing_version"], sub["latest_version"], sub["upgrade_available"]) == (1, 1, False)
    live.run_subscriptions_once(db, fake_provider)
    assert CALLS == ["alpha"]
    first_run = live._runs[sub["id"]]

    edit(second_client, listing["id"], params={"text": "beta"})  # version 2 is published
    now = client.get("/api/marketplace/subscriptions").json()[0]
    assert (now["listing_version"], now["latest_version"], now["upgrade_available"]) == (1, 2, True)
    live.run_subscriptions_once(db, fake_provider)
    assert live._runs[sub["id"]] is first_run and first_run.version == 1  # not rebuilt, not followed
    assert db.get(Subscription, sub["id"]).listing_version == 1

    # Even a rebuild (a restart) builds version 1's code, not the listing's current settings.
    live.drop(sub["id"])
    live.run_subscriptions_once(db, fake_provider)
    assert CALLS == ["alpha", "alpha"]

    r = client.post(f"/api/marketplace/subscriptions/{sub['id']}/upgrade")
    assert r.status_code == 200, r.text
    assert (r.json()["listing_version"], r.json()["upgrade_available"]) == (2, False)
    assert sub["id"] not in live._runs  # the run is rebuilt on the next pass
    live.run_subscriptions_once(db, fake_provider)
    assert CALLS == ["alpha", "alpha", "beta"]
    assert live._runs[sub["id"]].version == 2


def test_a_run_in_progress_is_rebuilt_when_the_version_changes(
    client: TestClient, second_client: TestClient, db: Session, fake_provider: FakeProvider
):
    listing = new_listing(second_client, db)
    sub = subscribe(client, listing["id"]).json()
    live.run_subscriptions_once(db, fake_provider)
    edit(second_client, listing["id"], params={"text": "beta"})
    db.get(Subscription, sub["id"]).listing_version = 2  # as `upgrade` leaves it, before the pass
    db.commit()
    live.run_subscriptions_once(db, fake_provider)
    assert CALLS == ["alpha", "beta"] and live._runs[sub["id"]].version == 2


def test_upgrade_is_refused_when_there_is_nothing_newer(
    client: TestClient, second_client: TestClient, db: Session
):
    listing = new_listing(second_client, db)
    sub = subscribe(client, listing["id"]).json()
    url = f"/api/marketplace/subscriptions/{sub['id']}/upgrade"
    r = client.post(url)
    assert r.status_code == 409 and r.json()["code"] == "no_upgrade"

    edit(second_client, listing["id"], params={"text": "beta"})
    assert second_client.post(url).status_code == 404  # not their subscription
    assert client.post(url).status_code == 200
    assert client.post(url).json()["code"] == "no_upgrade"  # now on the latest

    # A retired listing offers nothing to move to.
    edit(second_client, listing["id"], params={"text": "alpha"})
    second_client.post(f"/api/marketplace/listings/{listing['id']}/retire")
    assert client.get("/api/marketplace/subscriptions").json()[0]["upgrade_available"] is False
    assert client.post(url).json()["code"] == "no_upgrade"


def test_a_stopped_subscription_cannot_be_upgraded(
    client: TestClient, second_client: TestClient, db: Session
):
    listing = new_listing(second_client, db)
    sub = subscribe(client, listing["id"]).json()
    edit(second_client, listing["id"], params={"text": "beta"})
    client.post(f"/api/marketplace/subscriptions/{sub['id']}/stop")
    r = client.post(f"/api/marketplace/subscriptions/{sub['id']}/upgrade")
    assert r.status_code == 409 and r.json()["code"] == "subscription_not_active"


# --- no version's code reaches anyone else -------------------------------------------------------


def test_no_route_shows_either_versions_code_to_a_non_owner(
    client: TestClient, second_client: TestClient, db: Session
):
    listing = new_listing(second_client, db, source=SMA_SOURCE + f"\n# {V1_SENTINEL}\n")
    sub = subscribe(client, listing["id"]).json()  # pinned to version 1
    edit(second_client, listing["id"], source=SMA_SOURCE + f"\n# {V2_SENTINEL}\n", changelog="v2")
    assert V1_SENTINEL in listings.code_for(db, listing["id"], 1)[0]  # the sentinels are really stored
    assert V2_SENTINEL in second_client.get("/api/marketplace/mine").text  # the owner sees the current code

    url = f"/api/marketplace/listings/{listing['id']}"
    sub_url = f"/api/marketplace/subscriptions/{sub['id']}"
    responses = [
        client.get("/api/marketplace/listings"),
        client.get(url),
        client.get("/api/marketplace/mine"),
        client.get("/api/marketplace/subscriptions"),
        client.get("/api/marketplace/earnings"),
        client.put(url, json={"source": "x", "changelog": "x"}),
        client.post(f"{sub_url}/upgrade"),
        client.post(f"{sub_url}/upgrade"),  # refused the second time
        second_client.get(url),
        second_client.get("/api/marketplace/earnings"),
        second_client.post(f"{sub_url}/upgrade"),
        client.get("/api/backtests"),
    ]
    for response in responses:
        for sentinel in (V1_SENTINEL, V2_SENTINEL):
            assert sentinel not in response.text, f"{response.request.method} {response.request.url} leaked"
    # The owner's public-shaped detail shows version numbers and notes only.
    assert [v["changelog"] for v in second_client.get(url).json()["versions"]] == [None, "v2"]


def test_the_ip_schema_walk_covers_the_upgrade_route_and_the_versions_list():
    spec = app.openapi()
    path = "/api/marketplace/subscriptions/{subscription_id}/upgrade"
    assert path in spec["paths"]  # the walk in test_marketplace takes every /api/marketplace path but /mine
    schema = spec["paths"][path]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert not _property_names(schema, spec) & BANNED_NAMES
    detail = spec["paths"]["/api/marketplace/listings/{listing_id}"]["get"]["responses"]["200"]
    names = _property_names(detail["content"]["application/json"]["schema"], spec)
    assert "versions" in names and not names & BANNED_NAMES


# --- backtesting uploaded code before publishing -------------------------------------------------

TODAY = date(2026, 3, 2)
SOURCE_BODY = {
    "source": SMA_SOURCE,
    "symbols": ["AAPL"],
    "interval": "1d",
    "start_date": "2026-01-05",
    "end_date": "2026-02-27",
}


def test_a_source_backtest_runs_and_only_its_requester_sees_it(
    client: TestClient, second_client: TestClient, db: Session, fake_provider: FakeProvider
):
    created = client.post("/api/backtests", json=SOURCE_BODY)
    assert created.status_code == 200, created.text
    assert "source" not in created.json() and "def on_bar" not in created.text
    backtest_id = created.json()["id"]
    jobs.run_backtest_job(db, backtest_id, fake_provider, today=TODAY)
    detail = client.get(f"/api/backtests/{backtest_id}").json()
    assert detail["status"] == "done", detail["error"]
    assert detail["results"]["bars"] == 40 and "def on_bar" not in json.dumps(detail)
    assert second_client.get(f"/api/backtests/{backtest_id}").status_code == 404
    assert second_client.get("/api/backtests").json() == []


def test_invalid_source_is_refused_with_the_validators_problems(client: TestClient):
    r = client.post("/api/backtests", json={**SOURCE_BODY, "source": "import os\n"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_source"
    assert r.json()["problems"] and all(p["line"] >= 0 and p["message"] for p in r.json()["problems"])
    assert client.get("/api/backtests").json() == []
    both = client.post("/api/backtests", json={**SOURCE_BODY, "strategy": "sma_crossover"})
    assert both.status_code == 400


# --- the migration -------------------------------------------------------------------------------


def test_migration_backfills_one_version_per_listing_and_pins_subscribers(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    _upgrade_to(engine, "0013")
    listing = (
        "INSERT INTO algo_listings (id, owner_user_id, name, tagline, description, markets, test_symbols, "
        "interval, fee_percent, status, source, strategy_key, params, version, created_at, updated_at) "
        "VALUES (:id, 1, 'n', '', '', '[\"international\"]', '[\"AAPL\"]', '1d', '10', 'published', "
        ":source, :key, :params, :version, '2026-03-01 10:00:00', '2026-03-02 11:00:00')"
    )
    sub = (
        "INSERT INTO subscriptions (id, subscriber_user_id, listing_id, listing_version, symbols, capital, "
        "account_id, fee_percent, high_water_mark, fees_paid, status, created_at) "
        "VALUES (1, 2, 11, 1, '[\"AAPL\"]', '1000', 5, '10', '0', '0', 'active', '2026-03-01 10:00:00')"
    )
    with engine.begin() as conn:
        conn.execute(text(listing), dict(id=11, source="CODE", key=None, params=None, version=3))
        conn.execute(
            text(listing), dict(id=12, source=None, key="sma_crossover", params='{"a": "1"}', version=1)
        )
        conn.execute(text(sub))
    upgrade_database(engine)
    with engine.connect() as conn:
        got = conn.execute(
            text(
                "SELECT listing_id, version, source, strategy_key, params, interval, changelog "
                "FROM listing_versions ORDER BY listing_id"
            )
        ).all()
        pinned = conn.execute(text("SELECT listing_version FROM subscriptions")).scalar_one()
    assert [tuple(r) for r in got] == [
        (11, 3, "CODE", None, None, "1d", None),
        (12, 1, None, "sma_crossover", '{"a": "1"}', "1d", None),
    ]
    assert pinned == 3  # subscribers used to follow the current version
    engine.dispose()
