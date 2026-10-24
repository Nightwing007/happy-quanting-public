"""Users never see or change each other's data: another user's id is a 404, not a 403, and every
route that is not on the public list refuses a visitor who is not logged in."""

import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.algos import jobs
from app.config import get_settings
from app.main import app
from app.market_data.fake import FakeProvider
from app.models import Account, User
from app.trading import engine
from tests.test_backtest import BODY as BACKTEST_BODY
from tests.test_backtest import TODAY
from tests.test_sim import SYMBOL, make_sim

D = Decimal


@pytest.fixture
def rupee_world(offline_market_data, monkeypatch: pytest.MonkeyPatch, fixed_clock) -> None:
    # What test_sim's autouse fixture sets up: a replayed day inside Yahoo's 1-minute history.
    monkeypatch.setenv("BASE_CURRENCY", "INR")
    monkeypatch.setenv("STARTING_CASH", "1000000")
    get_settings.cache_clear()


def test_another_users_data_is_a_404_or_empty(
    client: TestClient, second_client: TestClient, db: Session, fake_provider: FakeProvider
) -> None:
    # --- user A (tester) makes one of everything -------------------------------------------
    # A limit buy below the market stays open, so there is an order to cancel and no trade yet.
    resting = client.post(
        "/api/orders",
        json={"symbol": "AAPL", "side": "buy", "type": "limit", "quantity": "1", "limit_price": "1"},
    )
    assert resting.status_code == 200, resting.text
    order_id = resting.json()["id"]
    bought = client.post("/api/orders", json={"symbol": "AAPL", "side": "buy", "quantity": "2"})
    assert bought.status_code == 200, bought.text
    [trade] = client.get("/api/trades").json()

    queued = client.post("/api/backtests", json=BACKTEST_BODY)
    assert queued.status_code == 200, queued.text
    backtest_id = queued.json()["id"]
    jobs.run_backtest_job(db, backtest_id, fake_provider, today=TODAY)
    assert client.get(f"/api/backtests/{backtest_id}").json()["status"] == "done"

    algo = client.post("/api/algos/mine", json={"name": "Mine", "strategy": "sma_crossover", "params": {}})
    assert algo.status_code == 200, algo.text
    algo_id = algo.json()["id"]

    # --- user B (other) sees none of it ----------------------------------------------------
    b = second_client
    assert b.get("/api/orders").json() == []
    assert b.get("/api/trades").json() == []
    portfolio = b.get("/api/portfolio").json()
    assert portfolio["holdings"] == [] and portfolio["cash"] == "100000"
    assert b.delete(f"/api/orders/{order_id}").status_code == 404
    assert b.post(f"/api/trades/{trade['id']}/exit", json={}).status_code == 404

    assert b.get("/api/backtests").json() == []
    assert b.get(f"/api/backtests/{backtest_id}").status_code == 404
    assert b.delete(f"/api/backtests/{backtest_id}").status_code == 404

    assert b.get("/api/algos/mine").json() == []
    assert b.get(f"/api/algos/mine/{algo_id}").status_code == 404
    body = {"name": "x", "strategy": "sma_crossover", "params": {}}
    assert b.put(f"/api/algos/mine/{algo_id}", json=body).status_code == 404
    assert b.delete(f"/api/algos/mine/{algo_id}").status_code == 404
    # Nor can B start a backtest from A's saved algorithm.
    no_algo = {k: v for k, v in BACKTEST_BODY.items() if k not in ("strategy", "params")}
    assert b.post("/api/backtests", json={**no_algo, "algo_id": algo_id}).status_code == 404

    # --- ...and none of B's attempts changed A's things ------------------------------------
    assert len(client.get("/api/orders").json()) == 2
    assert client.get(f"/api/backtests/{backtest_id}").status_code == 200
    assert len(client.get("/api/algos/mine").json()) == 1


@pytest.mark.real_calendar  # the sim replays a real past day
@pytest.mark.usefixtures("rupee_world")
def test_another_users_sim_session_is_a_404(
    client: TestClient, second_client: TestClient, db: Session, fake_provider: FakeProvider
) -> None:
    sim = make_sim(db, fake_provider)  # owned by tester: the first live account's owner
    base = f"/api/sim/sessions/{sim.id}"
    b = second_client
    assert b.get("/api/sim/sessions").json() == []
    assert b.get(base).status_code == 404
    assert b.post(f"{base}/control", json={"action": "start"}).status_code == 404
    assert b.delete(base).status_code == 404
    assert b.get(f"{base}/orders").status_code == 404  # the sim's own trading routes too
    assert (
        b.post(
            f"{base}/orders", json={"symbol": SYMBOL, "side": "buy", "type": "market", "quantity": "1"}
        ).status_code
        == 404
    )
    # A's session is untouched, and A can still play it.
    assert [x["id"] for x in client.get("/api/sim/sessions").json()] == [sim.id]
    assert client.post(f"{base}/control", json={"action": "pause"}).status_code == 200


# Routes a visitor may call. Logout is here because it only clears a cookie.
PUBLIC_EXACT = {
    "/api/health",
    "/api/algos/library",
    "/api/brokers",  # static reference data, no user rows
    "/api/auth/signup",
    "/api/auth/login",
    "/api/auth/logout",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
}


def _is_public(path: str) -> bool:
    return path in PUBLIC_EXACT or path.startswith("/api/market/")


def test_every_other_api_route_refuses_a_visitor(anon_client: TestClient) -> None:
    # The OpenAPI document lists every route the app serves (FastAPI nests included routers, so
    # walking `app.routes` would find only the includes).
    checked = 0
    for template, operations in app.openapi()["paths"].items():
        if not template.startswith("/api") or _is_public(template):
            continue
        path = re.sub(r"\{[^}]+\}", "1", template)
        for method in operations:
            r = anon_client.request(method.upper(), path)
            assert r.status_code == 401, f"{method.upper()} {template} answered {r.status_code}"
            assert r.json()["code"] == "not_authenticated"
            checked += 1
    assert checked > 25  # the walk really covered the trading, sim, backtest, algo and profile routes


def test_the_first_account_on_a_fresh_database_belongs_to_demo(db: Session) -> None:
    engine.first_run_setup(db)
    engine.first_run_setup(db)  # idempotent
    [account] = db.query(Account).all()
    demo = db.query(User).filter(User.username == "demo").one()
    assert account.user_id == demo.id
    assert engine.account_for_user(db, demo.id).id == account.id


def test_account_for_user_makes_one_account_per_user(db: Session) -> None:
    from datetime import UTC, datetime

    user = User(username="zed", display_name="Zed", password_hash="!", created_at=datetime.now(UTC))
    db.add(user)
    db.commit()
    first = engine.account_for_user(db, user.id)
    assert first.user_id == user.id
    assert engine.account_for_user(db, user.id).id == first.id
