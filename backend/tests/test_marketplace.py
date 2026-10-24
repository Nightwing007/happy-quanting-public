"""Marketplace listings: creating, publishing, the server-measured performance, and the promise
that nobody but the owner can get a listing's code or settings out of the API."""

import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.market_data.fake import FakeProvider
from app.marketplace import performance
from app.models import AlgoListing, ListingPerformance

D = Decimal
LIBRARY_DIR = Path(__file__).parents[1] / "app" / "algos" / "library"
SMA_SOURCE = (LIBRARY_DIR / "sma_crossover.py").read_text(encoding="utf-8")
SYMBOL = "AAPL"

# Hourly code for AAPL: only its interval matters (3 years of hourly bars don't exist).
HOURLY_SOURCE = """from app.algos import hq


class Hourly(hq.Strategy):
    name = "Hourly"
    description = "Does nothing on hourly bars."
    markets = ("international",)
    interval = "1h"
    warmup_bars = 0
    PARAMETERS = {}

    def on_bar(self, ctx):
        pass
"""

REAL_WINDOWS = dict(performance.WINDOWS)
# Three years of daily bars take ~20 s through the engine; the windows keep their names and
# shrink (but stay longer than the SMA warmup), except in the test about which windows an interval can reach.
SHORT_WINDOWS = {"3mo": (50, "3-month"), "1y": (60, "1-year"), "3y": (70, "3-year")}


@pytest.fixture(scope="module")
def canned_results():
    """One real, tiny backtest, made once, that stands in for the engine in tests that are not
    about how performance is computed."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.algos.backtest import run_backtest
    from app.db import Base
    from app.market_data.history import today_utc

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)() as session:
        today = today_utc()
        results = run_backtest(
            session, FakeProvider(), strategy_key="sma_crossover", params={}, symbols=[SYMBOL],
            interval="1d", start=today - timedelta(days=45), end=today, starting_cash=D(100000),
            account_currency="USD",
        )  # fmt: skip
    engine.dispose()
    return results


@pytest.fixture
def canned_backtest(monkeypatch: pytest.MonkeyPatch, canned_results):
    """`run_backtest` returns the canned results at once (the real one is exercised by
    `test_publish_measures_every_window_on_the_test_symbols`)."""
    monkeypatch.setattr(performance, "run_backtest", lambda *a, **kw: canned_results)


@pytest.fixture(autouse=True)
def short_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(performance, "WINDOWS", SHORT_WINDOWS)


BANNED_NAMES = {"source", "params", "parameters", "strategy_key", "code", "trades", "graph"}


def body(**over):
    base = dict(
        name="Trend rider", tagline="Follows trends", description="Daily trend follower",
        markets=["international"], test_symbols=[SYMBOL], fee_percent="10", source=SMA_SOURCE,
    )  # fmt: skip
    base.update(over)
    return base


def create(client: TestClient, **over) -> dict:
    r = client.post("/api/marketplace/listings", json=body(**over))
    assert r.status_code == 200, r.text
    return r.json()


def save_algo(client: TestClient, **params) -> int:
    r = client.post(
        "/api/algos/mine",
        json={"name": "Mine", "description": "", "strategy": "sma_crossover", "params": params},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def measure(db: Session, provider: FakeProvider, listing_id: int) -> AlgoListing:
    listing = db.get(AlgoListing, listing_id)
    performance.compute_performance(db, provider, listing)
    return listing


# --- creating ---------------------------------------------------------------------------------


def test_create_from_source_makes_a_draft_and_a_creator(client: TestClient):
    assert client.get("/api/me").json()["is_creator"] is False
    listing = create(client)
    assert listing["status"] == "draft" and listing["version"] == 1
    assert listing["interval"] == "1d" and listing["fee_percent"] == "10"
    assert listing["creator"]["username"] == "tester"
    assert client.get("/api/me").json()["is_creator"] is True
    (mine,) = client.get("/api/marketplace/mine").json()
    assert mine["source"] == SMA_SOURCE and mine["strategy_key"] is None and mine["params"] is None


def test_create_from_a_saved_algo_copies_its_key_and_settings(client: TestClient):
    algo_id = save_algo(client, fast_period=5, slow_period=20)
    r = client.post("/api/marketplace/listings", json=body(source=None, user_algo_id=algo_id))
    assert r.status_code == 200, r.text
    (mine,) = client.get("/api/marketplace/mine").json()
    assert mine["source"] is None and mine["strategy_key"] == "sma_crossover"
    assert mine["params"]["fast_period"] == 5 and mine["params"]["slow_period"] == 20
    # Changing the saved algorithm later does not change the listing.
    client.put(
        f"/api/algos/mine/{algo_id}",
        json={"name": "Mine", "description": "", "strategy": "sma_crossover", "params": {"fast_period": 7}},
    )
    assert client.get("/api/marketplace/mine").json()[0]["params"]["fast_period"] == 5


def test_a_saved_algo_of_someone_else_is_not_found(client: TestClient, second_client: TestClient):
    algo_id = save_algo(client)
    r = second_client.post("/api/marketplace/listings", json=body(source=None, user_algo_id=algo_id))
    assert r.status_code == 404 and r.json()["code"] == "algo_not_found"
    assert second_client.get("/api/me").json()["is_creator"] is False


def test_exactly_one_form_is_required(client: TestClient):
    both = client.post("/api/marketplace/listings", json=body(user_algo_id=1))
    neither = client.post("/api/marketplace/listings", json=body(source=None))
    assert both.status_code == neither.status_code == 400
    assert both.json()["code"] == neither.json()["code"] == "invalid_form"


def test_invalid_source_is_refused_with_line_numbered_problems(client: TestClient, db: Session):
    bad = "import os\n" + SMA_SOURCE
    r = client.post("/api/marketplace/listings", json=body(source=bad))
    assert r.status_code == 400 and r.json()["code"] == "invalid_source"
    problems = r.json()["problems"]
    assert problems and problems[0]["line"] == 1 and problems[0]["message"].startswith("Line 1")
    assert "Line 1" in r.json()["detail"]
    assert db.scalars(select(AlgoListing)).all() == []
    assert client.get("/api/me").json()["is_creator"] is False


@pytest.mark.parametrize("fee", ["-1", "50.01", "100"])
def test_fee_outside_0_to_50_is_refused(client: TestClient, fee: str):
    r = client.post("/api/marketplace/listings", json=body(fee_percent=fee))
    assert r.status_code == 400 and r.json()["code"] == "fee_out_of_range"


def test_fee_bounds_are_allowed(client: TestClient):
    assert create(client, fee_percent="0")["fee_percent"] == "0"
    assert create(client, fee_percent="50")["fee_percent"] == "50"


# --- publishing -------------------------------------------------------------------------------


def test_publish_needs_a_test_symbol_on_a_supported_market(client: TestClient):
    empty = create(client, test_symbols=[])
    r = client.post(f"/api/marketplace/listings/{empty['id']}/publish")
    assert r.status_code == 400 and r.json()["code"] == "no_test_symbols"

    wrong = create(client, markets=["crypto"])  # AAPL is not a crypto symbol
    r = client.post(f"/api/marketplace/listings/{wrong['id']}/publish")
    assert r.status_code == 400 and r.json()["code"] == "test_symbol_market"
    assert client.get(f"/api/marketplace/listings/{wrong['id']}").json()["status"] == "draft"


def test_publish_measures_every_window_on_the_test_symbols(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    listing = create(client)
    r = client.post(f"/api/marketplace/listings/{listing['id']}/publish")
    assert r.status_code == 200 and r.json()["status"] == "published"
    assert {w["window"]: w["status"] for w in r.json()["performance"]} == {
        "3mo": "queued", "1y": "queued", "3y": "queued",
    }  # fmt: skip
    assert r.json()["headline"] is None

    measure(db, fake_provider, listing["id"])
    detail = client.get(f"/api/marketplace/listings/{listing['id']}").json()
    assert {w["window"]: w["status"] for w in detail["performance"]} == {
        "3mo": "done", "1y": "done", "3y": "done",
    }  # fmt: skip
    one_year = next(w for w in detail["performance"] if w["window"] == "1y")
    assert detail["headline"]["window"] == "1y"
    results = one_year["results"]
    assert set(results["metrics"]) >= {
        "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "win_rate_pct", "profit_factor",
        "trade_count", "total_charges", "exposure_pct",
    }  # fmt: skip
    assert results["equity_curve"] and results["drawdown"] and results["buy_and_hold"]
    # Only totals and curves are kept: not a trade, order, log or setting.
    stored = db.scalars(select(ListingPerformance)).all()
    assert len(stored) == 3 and all(set(row.results) == set(results) for row in stored)
    for key in ("trades", "orders", "logs", "params", "strategy_key", "purchases"):
        assert key not in str(stored[0].results.keys()) and f'"{key}"' not in str(stored[0].results)


def test_a_window_the_history_cannot_cover_is_unavailable_with_a_sentence(
    client: TestClient,
    db: Session,
    fake_provider: FakeProvider,
    monkeypatch: pytest.MonkeyPatch,
    canned_results,
):
    # Hourly bars reach back about two years. Every window gets a canned daily result of the same
    # shape; what is under test is which windows get measured.
    monkeypatch.setattr(performance, "WINDOWS", REAL_WINDOWS)
    daily = canned_results
    asked: list[str] = []
    monkeypatch.setattr(performance, "run_backtest", lambda *a, **kw: asked.append(kw["interval"]) or daily)

    listing = create(client, source=HOURLY_SOURCE)
    assert listing["interval"] == "1h"
    client.post(f"/api/marketplace/listings/{listing['id']}/publish")
    measure(db, fake_provider, listing["id"])

    windows = {
        w["window"]: w for w in client.get(f"/api/marketplace/listings/{listing['id']}").json()["performance"]
    }
    assert [windows[w]["status"] for w in ("3mo", "1y", "3y")] == ["done", "done", "unavailable"]
    assert windows["3y"]["results"] is None
    assert re.search(
        r"1h data only goes back about \d+ days, so a 3-year result can't be measured", windows["3y"]["note"]
    )
    assert asked == ["1h", "1h"]  # the unavailable window was never run


def test_a_failing_run_marks_its_window_failed_and_the_others_go_on(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    listing = create(client, test_symbols=["NOPE-XYZ"], markets=["international"])
    row = db.get(AlgoListing, listing["id"])
    row.status = "published"
    db.commit()
    performance.queue_performance(db, row)
    performance.compute_performance(db, fake_provider, row)
    windows = db.scalars(select(ListingPerformance).order_by(ListingPerformance.id)).all()
    assert [w.status for w in windows] == ["failed"] * 3 and all(w.note for w in windows)


def test_the_worker_hook_measures_a_queued_listing(
    client: TestClient, db: Session, fake_provider: FakeProvider, canned_backtest
):
    listing = create(client)
    client.post(f"/api/marketplace/listings/{listing['id']}/publish")
    assert performance.run_next_queued(db, fake_provider) is True
    assert performance.run_next_queued(db, fake_provider) is False
    assert {w.status for w in db.scalars(select(ListingPerformance))} == {"done"}


# --- versions and state -----------------------------------------------------------------------


def test_new_code_or_settings_bump_the_version_and_other_edits_do_not(client: TestClient):
    code = create(client)
    url = f"/api/marketplace/listings/{code['id']}"
    assert client.put(url, json={"name": "Renamed", "fee_percent": "12.5"}).json()["version"] == 1
    assert client.put(url, json={"source": SMA_SOURCE}).json()["version"] == 1  # same code
    assert client.put(url, json={"source": SMA_SOURCE + "\n# tweak\n"}).json()["version"] == 2
    r = client.put(url, json={"params": {"fast_period": 3}})
    assert r.status_code == 400 and r.json()["code"] == "invalid_form"  # code has no settings
    r = client.put(url, json={"source": "import os\n" + SMA_SOURCE})
    assert r.status_code == 400 and r.json()["problems"]

    algo_id = save_algo(client)
    lib = client.post("/api/marketplace/listings", json=body(source=None, user_algo_id=algo_id)).json()
    lib_url = f"/api/marketplace/listings/{lib['id']}"
    assert client.put(lib_url, json={"params": {"fast_period": 4}}).json()["version"] == 2
    assert client.put(lib_url, json={"params": {"fast_period": 4}}).json()["version"] == 2  # unchanged
    assert client.put(lib_url, json={"source": SMA_SOURCE}).json()["code"] == "invalid_form"


def test_editing_a_published_listing_measures_the_new_version(
    client: TestClient, db: Session, fake_provider: FakeProvider, canned_backtest
):
    algo_id = save_algo(client)
    lib = client.post("/api/marketplace/listings", json=body(source=None, user_algo_id=algo_id)).json()
    client.post(f"/api/marketplace/listings/{lib['id']}/publish")
    measure(db, fake_provider, lib["id"])
    r = client.put(f"/api/marketplace/listings/{lib['id']}", json={"params": {"fast_period": 4}})
    assert r.json()["version"] == 2
    assert {w["status"] for w in r.json()["performance"]} == {"queued"}  # v1's figures are gone
    assert r.json()["headline"] is None
    versions = {row.version for row in db.scalars(select(ListingPerformance))}
    assert versions == {2}


def test_retire_hides_the_listing_and_freezes_it(client: TestClient, second_client: TestClient):
    listing = create(client)
    url = f"/api/marketplace/listings/{listing['id']}"
    client.post(f"{url}/publish")
    assert [x["id"] for x in second_client.get("/api/marketplace/listings").json()] == [listing["id"]]
    assert client.post(f"{url}/retire").json()["status"] == "retired"
    assert second_client.get("/api/marketplace/listings").json() == []
    assert second_client.get(url).status_code == 404
    assert client.get(url).json()["status"] == "retired"  # the owner still sees it
    for call in (client.post(f"{url}/publish"), client.put(url, json={"name": "x"})):
        assert call.status_code == 409 and call.json()["code"] == "listing_retired"


def test_market_filter_matches_segments_and_codes(client: TestClient, db: Session):
    ids = {}
    for name, markets in (("India", ["india"]), ("Nse", ["NSE"]), ("Crypto", ["crypto"])):
        ids[name] = create(client, markets=markets, test_symbols=[], name=name)["id"]
    for row in db.scalars(select(AlgoListing)):
        row.status = "published"
    db.commit()

    def names(market: str) -> set[str]:
        return {x["name"] for x in client.get("/api/marketplace/listings", params={"market": market}).json()}

    assert names("india") == {"India", "Nse"}  # NSE is an Indian market
    assert names("NSE") == {"India", "Nse"}  # an Indian segment listing covers NSE
    assert names("crypto") == {"Crypto"}
    assert len(client.get("/api/marketplace/listings").json()) == 3


def test_creator_filter_and_profile(client: TestClient, second_client: TestClient, db: Session):
    published = create(client, name="Pub")
    create(client, name="Draft")  # stays a draft
    client.post(f"/api/marketplace/listings/{published['id']}/publish")
    listings = lambda **p: second_client.get("/api/marketplace/listings", params=p).json()  # noqa: E731
    assert [x["name"] for x in listings(creator="tester")] == ["Pub"]
    assert [x["name"] for x in listings(creator="TESTER")] == ["Pub"]
    assert listings(creator="nobody") == []

    profile = second_client.get("/api/marketplace/creators/tester").json()
    assert profile == {
        "username": "tester", "display_name": profile["display_name"], "avatar_url": None,
        "bio": "", "listing_count": 1,
    }  # fmt: skip
    for secret in ("password", "hash", "session", "token", "email"):
        assert secret not in str(profile).lower()
    missing = second_client.get("/api/marketplace/creators/nobody")
    assert missing.status_code == 404 and missing.json()["code"] == "creator_not_found"


# --- who can see what ---------------------------------------------------------------------------


def test_a_non_owner_gets_404_on_a_draft_everywhere(client: TestClient, second_client: TestClient):
    listing = create(client)
    url = f"/api/marketplace/listings/{listing['id']}"
    assert second_client.get(url).status_code == 404
    assert second_client.get("/api/marketplace/listings").json() == []
    assert second_client.get("/api/marketplace/mine").json() == []
    for r in (
        second_client.put(url, json={"name": "mine now"}),
        second_client.post(f"{url}/publish"),
        second_client.post(f"{url}/retire"),
        second_client.post(f"{url}/refresh-performance"),
    ):
        assert r.status_code == 404 and r.json()["code"] == "listing_not_found"
    assert client.get(url).json()["name"] == "Trend rider"  # untouched


def test_marketplace_needs_a_login(anon_client: TestClient):
    assert anon_client.get("/api/marketplace/listings").status_code == 401
    assert anon_client.get("/api/marketplace/mine").status_code == 401
    assert anon_client.post("/api/marketplace/listings", json=body()).status_code == 401


def test_refresh_performance_requeues_for_the_owner(
    client: TestClient, db: Session, fake_provider: FakeProvider, canned_backtest
):
    listing = create(client)
    url = f"/api/marketplace/listings/{listing['id']}"
    client.post(f"{url}/publish")
    measure(db, fake_provider, listing["id"])
    r = client.post(f"{url}/refresh-performance")
    assert r.status_code == 200 and {w["status"] for w in r.json()["performance"]} == {"queued"}


# --- IP protection ------------------------------------------------------------------------------


def _property_names(schema, spec, seen=()) -> set[str]:
    """Every property name reachable from `schema`, following $ref, arrays, unions and maps."""
    names: set[str] = set()
    if isinstance(schema, list):
        for item in schema:
            names |= _property_names(item, spec, seen)
        return names
    if not isinstance(schema, dict):
        return names
    ref = schema.get("$ref")
    if ref:
        if ref in seen:
            return names
        target = spec
        for part in ref.removeprefix("#/").split("/"):
            target = target[part]
        return _property_names(target, spec, (*seen, ref))
    for name, sub in schema.get("properties", {}).items():
        names.add(name)
        names |= _property_names(sub, spec, seen)
    for key in ("items", "additionalProperties", "anyOf", "oneOf", "allOf", "prefixItems"):
        names |= _property_names(schema.get(key), spec, seen)
    return names


def test_public_marketplace_schemas_have_no_code_settings_or_trades():
    spec = app.openapi()
    paths = [p for p in spec["paths"] if p.startswith("/api/marketplace") and p != "/api/marketplace/mine"]
    assert len(paths) >= 5
    for path in paths:
        for method, op in spec["paths"][path].items():
            for status, response in op["responses"].items():
                schema = response.get("content", {}).get("application/json", {}).get("schema")
                found = _property_names(schema, spec) & BANNED_NAMES
                assert not found, f"{method.upper()} {path} {status} can return {found}"
    # The check can see: the owner's view does carry them.
    mine = spec["paths"]["/api/marketplace/mine"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert {"source", "params", "strategy_key"} <= _property_names(mine, spec)


SOURCE_SENTINEL = "SENTINEL_SRC_9f3a71c2"
PARAM_SENTINEL = "47.3159265"


def test_no_route_leaks_a_listings_code_or_settings_to_another_user(
    client: TestClient, second_client: TestClient, db: Session, fake_provider: FakeProvider, canned_backtest
):
    secret_code = SMA_SOURCE + f"\n# {SOURCE_SENTINEL}\n"
    algo_id = save_algo(client, percent_of_cash=PARAM_SENTINEL)
    from_code = create(client, source=secret_code, name="Code listing")
    from_algo = client.post(
        "/api/marketplace/listings", json=body(source=None, user_algo_id=algo_id, name="Algo listing")
    ).json()
    draft = create(client, source=secret_code, name="Hidden draft")
    for listing in (from_code, from_algo):
        client.post(f"/api/marketplace/listings/{listing['id']}/publish")
        measure(db, fake_provider, listing["id"])
    ids = [from_code["id"], from_algo["id"], draft["id"]]

    # The owner's own view does hold both secrets, so the checks below can fail.
    mine = client.get("/api/marketplace/mine").text
    assert SOURCE_SENTINEL in mine and PARAM_SENTINEL in mine

    def clean(response, label: str) -> None:
        assert SOURCE_SENTINEL not in response.text, f"{label} leaked the code"
        assert PARAM_SENTINEL not in response.text, f"{label} leaked the settings"

    # Every marketplace route, as user B.
    clean(second_client.get("/api/marketplace/listings"), "GET listings")
    clean(
        second_client.get("/api/marketplace/listings", params={"market": "international"}),
        "GET listings?market",
    )
    clean(second_client.get("/api/marketplace/mine"), "GET mine")
    visible = second_client.get("/api/marketplace/listings").json()
    assert {x["id"] for x in visible} == {from_code["id"], from_algo["id"]}
    for listing_id in ids:
        url = f"/api/marketplace/listings/{listing_id}"
        clean(second_client.get(url), f"GET {url}")
        clean(second_client.put(url, json={"name": "x", "source": "x", "params": {"a": 1}}), f"PUT {url}")
        for action in ("publish", "retire", "refresh-performance"):
            clean(second_client.post(f"{url}/{action}"), f"POST {url}/{action}")
    clean(
        second_client.post("/api/marketplace/listings", json=body(source=None, user_algo_id=algo_id)),
        "POST listings",
    )
    # The owner's public detail never carries them either.
    for listing_id in ids:
        clean(client.get(f"/api/marketplace/listings/{listing_id}"), "owner GET detail")

    # Subscribing to a listing and every subscription route, as user B, reveal neither.
    for listing in (from_code, from_algo):
        sub = second_client.post(
            f"/api/marketplace/listings/{listing['id']}/subscribe",
            json={"symbols": [SYMBOL], "capital": "1000"},
        )
        clean(sub, "POST subscribe")
        assert sub.status_code == 200, sub.text
        clean(second_client.post(f"/api/marketplace/subscriptions/{sub.json()['id']}/stop"), "POST stop")
    clean(second_client.get("/api/marketplace/subscriptions"), "GET subscriptions")
    clean(second_client.get("/api/marketplace/earnings"), "GET earnings (subscriber)")
    clean(client.get("/api/marketplace/earnings"), "GET earnings (creator)")

    # Every other GET route that takes an id, tried with the ids that exist.
    tried = 0
    for path, operations in app.openapi()["paths"].items():
        if "get" not in operations or "{" not in path or path.startswith("/api/marketplace"):
            continue
        for value in {*map(str, ids), str(algo_id), "1", "2", "3"}:
            url = re.sub(r"\{[^}]+\}", value, path)
            clean(second_client.get(url), f"GET {url}")
            tried += 1
    assert tried > 10
