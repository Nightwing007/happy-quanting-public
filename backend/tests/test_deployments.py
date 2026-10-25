"""Deployments: the user's own algorithms running live on a paper sub-account. Uses the fake
provider and the same loop pass the app runs (`run_deployments_once`)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.algos import deployments, hq
from app.algos.library import LIBRARY
from app.badges.evaluate import evaluate_user
from app.market_data.fake import FakeProvider
from app.models import Account, AccountKind, CashTransfer, Deployment, Order, Trade, UserAlgo
from app.trading import engine
from tests.test_blocks import node
from tests.test_marketplace import SMA_SOURCE
from tests.test_subscriptions import force_market

D = Decimal
SYMBOL = "AAPL"
NOW = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)


class Buyer(hq.Strategy):
    """Buys `shares` of each symbol it holds none of, on every bar it sees."""

    name = "Buyer"
    description = "Test strategy."
    markets = ("international",)
    interval = "1d"
    warmup_bars = 0
    PARAMETERS = {"shares": hq.Param("int", 10, min=1, max=100)}

    def on_bar(self, ctx):
        for symbol in ctx.symbols:
            if ctx.position(symbol).quantity == 0:
                ctx.log(f"buying {ctx.params['shares']} {symbol}")
                ctx.buy(symbol, quantity=ctx.params["shares"])


# The same strategy as uploaded code: it runs in a sandbox child process.
BUYER_SOURCE = """from app.algos import hq


class SourceBuyer(hq.Strategy):
    name = "Source buyer"
    description = "Buys a fixed number of shares."
    markets = ("international",)
    interval = "1d"
    warmup_bars = 0
    PARAMETERS = {"shares": hq.Param("int", 10, min=1, max=100)}

    def on_bar(self, ctx):
        for symbol in ctx.symbols:
            if ctx.position(symbol).quantity == 0:
                ctx.buy(symbol, quantity=ctx.params["shares"])
"""


@pytest.fixture(autouse=True)
def library_and_clock(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(LIBRARY, "buyer", Buyer)
    state = {"at": NOW}
    monkeypatch.setattr(clock, "now", lambda: state["at"])
    deployments._logs.clear()
    yield state
    deployments.drop_all()  # no test leaves a sandbox child behind


@pytest.fixture
def ticking(library_and_clock):
    class Clock:
        def advance(self, minutes: int = 1) -> None:
            library_and_clock["at"] += timedelta(minutes=minutes)

    return Clock()


def user_id(client: TestClient) -> int:
    return client.get("/api/me").json()["id"]


def deploy(client: TestClient, capital="30000", symbols=(SYMBOL,), **body):
    return client.post("/api/deployments", json={"symbols": list(symbols), "capital": capital, **body})


def save_algo(client: TestClient, **body) -> int:
    r = client.post("/api/algos/mine", json={"name": "Mine", **body})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def run_twice(db: Session, provider: FakeProvider, ticking) -> None:
    """The first pass decides and queues; the second meets a newer quote and fills."""
    deployments.run_deployments_once(db, provider)
    ticking.advance()
    deployments.run_deployments_once(db, provider)


def orders_of(db: Session, dep_id: int) -> list[Order]:
    dep = db.get(Deployment, dep_id)
    return list(db.scalars(select(Order).where(Order.account_id == dep.account_id).order_by(Order.id)))


def live_account(db: Session, uid: int) -> Account:
    return engine.account_for_user(db, uid)


# --- deploying and running -----------------------------------------------------------------------


def test_a_library_algo_with_tweaked_params_trades_its_own_account(
    client: TestClient, db: Session, fake_provider, ticking
):
    uid = user_id(client)
    r = deploy(client, library_key="buyer", params={"shares": 7})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "active" and out["name"] == "Buyer" and out["strategy_kind"] == "library"
    assert out["params"] == {"shares": 7} and out["runs_code"] is False
    assert D(out["capital"]) == D(out["equity"]) == D(30000)

    dep = db.get(Deployment, out["id"])
    account = db.get(Account, dep.account_id)
    assert account.kind == AccountKind.ALGO and account.user_id == uid
    assert account.cash == account.starting_cash == D(30000)
    assert live_account(db, uid).cash == D(70000)

    run_twice(db, fake_provider, ticking)
    assert [(o.symbol, o.side, o.quantity, o.status) for o in orders_of(db, dep.id)] == [
        (SYMBOL, "buy", D(7), "filled")
    ]
    mine = live_account(db, uid)
    assert db.scalars(select(Order).where(Order.account_id == mine.id)).all() == []
    assert db.scalars(select(Trade).where(Trade.account_id == mine.id)).all() == []
    kinds = [(t.deployment_id, t.subscription_id, t.kind, t.amount) for t in db.scalars(select(CashTransfer))]
    assert kinds == [(dep.id, None, "fund", D(30000))]


GRAPH = {
    "nodes": [
        node("u", "universe", interval="1d"),
        node("low", "rsi_below", period=14, level=99),
        node("buy", "buy", percent_of_cash=10),
    ],
    "edges": [{"source": "low", "source_port": "signal", "target": "buy", "target_port": "signal"}],
}


@pytest.mark.parametrize(
    "saved, expected_params, runs_code",
    [
        (dict(strategy="buyer", params={"shares": 5}), {"shares": 5}, False),
        (dict(source=BUYER_SOURCE, params={"shares": 3}), {"shares": 3}, True),
        (dict(graph=GRAPH), None, True),
    ],
    ids=["library-based", "source", "block-graph"],
)
def test_each_kind_of_saved_algo_trades_its_own_account(
    client: TestClient, db: Session, fake_provider, ticking, saved, expected_params, runs_code
):
    uid = user_id(client)
    algo_id = save_algo(client, **saved)
    out = deploy(client, algo_id=algo_id).json()
    assert out["strategy_kind"] == "mine" and out["user_algo_id"] == algo_id and out["name"] == "Mine"
    assert out["runs_code"] is runs_code
    if expected_params is not None:
        assert out["params"] == expected_params
    run_twice(db, fake_provider, ticking)
    orders = orders_of(db, out["id"])
    assert orders and all(o.side == "buy" and o.status == "filled" for o in orders)
    if "params" in saved and "shares" in saved["params"]:
        assert orders[0].quantity == D(saved["params"]["shares"])
    assert db.scalars(select(Order).where(Order.account_id == live_account(db, uid).id)).all() == []


def test_the_snapshot_is_pinned_when_the_saved_algo_changes_or_goes(
    client: TestClient, db: Session, fake_provider, ticking
):
    algo_id = save_algo(client, strategy="buyer", params={"shares": 5})
    out = deploy(client, algo_id=algo_id, params={"shares": 4}).json()  # a tweak at deploy time wins
    assert out["params"] == {"shares": 4}

    changed = client.put(
        f"/api/algos/mine/{algo_id}", json={"name": "Mine", "strategy": "buyer", "params": {"shares": 50}}
    )
    assert changed.status_code == 200, changed.text
    run_twice(db, fake_provider, ticking)
    assert [o.quantity for o in orders_of(db, out["id"])] == [D(4)]  # not 50

    assert client.delete(f"/api/algos/mine/{algo_id}").status_code in (200, 204)
    db.expire_all()
    assert client.get(f"/api/deployments/{out['id']}").json()["status"] == "active"
    deployments.drop(out["id"])  # rebuilt from the snapshot alone
    ticking.advance()
    deployments.run_deployments_once(db, fake_provider)
    assert out["id"] in deployments._runs


def test_the_source_snapshot_is_the_code_at_deploy_time(client: TestClient, db: Session):
    algo_id = save_algo(client, source=BUYER_SOURCE)
    out = deploy(client, algo_id=algo_id).json()
    client.put(f"/api/algos/mine/{algo_id}", json={"name": "Mine", "source": SMA_SOURCE})
    dep = db.get(Deployment, out["id"])
    assert dep.source == BUYER_SOURCE and db.get(UserAlgo, algo_id).source == SMA_SOURCE


def test_the_log_keeps_the_last_200_lines_and_the_detail_shows_everything(
    client: TestClient, db: Session, fake_provider, ticking
):
    out = deploy(client, library_key="buyer").json()
    run_twice(db, fake_provider, ticking)
    detail = client.get(f"/api/deployments/{out['id']}").json()
    assert [line["text"] for line in detail["log"]] == [f"buying 10 {SYMBOL}"]
    assert len(detail["open_trades"]) == 1 and detail["open_trades"][0]["symbol"] == SYMBOL
    assert [o["status"] for o in detail["orders"]] == ["filled"]
    assert D(detail["total_charges"]) > 0 and D(detail["realized_pnl"]) == D(
        detail["portfolio"]["realized_pnl"]
    )
    assert D(detail["total_pnl"]) == D(detail["realized_pnl"]) + D(detail["unrealized_pnl"])
    assert D(detail["equity"]) == D(detail["portfolio"]["total_value"])

    for i in range(500):
        deployments._note(out["id"], NOW, f"line {i}")
    lines = deployments.logs(out["id"])
    assert len(lines) == 200 and lines[-1].text == "line 499" and lines[0].text == "line 300"


def test_a_failing_deployment_does_not_stop_the_others_and_says_why(
    client: TestClient, db: Session, fake_provider, ticking, monkeypatch
):
    first = deploy(client, library_key="buyer", capital="10000").json()["id"]
    second = deploy(client, library_key="buyer", capital="10000").json()["id"]
    real = deployments._step_active

    def flaky(db_, provider, dep):
        if dep.id == first:
            raise RuntimeError("boom")
        real(db_, provider, dep)

    monkeypatch.setattr(deployments, "_step_active", flaky)
    deployments.run_deployments_once(db, fake_provider)
    assert second in deployments._runs and first not in deployments._runs

    monkeypatch.setattr(deployments, "_step_active", real)
    monkeypatch.setitem(LIBRARY, "buyer", None)  # now the first can't even be built
    deployments.drop_all()
    deployments.run_deployments_once(db, fake_provider)
    assert any("could not run" in line.text for line in deployments.logs(first))


# --- refusals --------------------------------------------------------------------------------------


def test_deploy_refusals(client: TestClient, second_client: TestClient, db: Session):
    def refused(status, code, **body):
        r = deploy(client, **body)
        assert (r.status_code, r.json().get("code")) == (status, code), r.text

    refused(400, "invalid_params", library_key="buyer", params={"shares": 0})
    refused(400, "invalid_params", library_key="buyer", params={"nope": 1})
    refused(400, "unknown_algorithm", library_key="not_there")
    refused(400, "one_algorithm", params={})
    refused(400, "one_algorithm", library_key="buyer", algo_id=1)
    refused(400, "symbol_market", library_key="buyer", symbols=["RELIANCE.NS"])  # a crypto/India-only gap
    refused(400, "symbol_unknown", library_key="buyer", symbols=["NOPE_NOT_A_SYMBOL"])
    refused(400, "insufficient_cash", library_key="buyer", capital="100001")
    refused(400, "invalid_capital", library_key="buyer", capital="0")

    other_algo = save_algo(second_client, strategy="buyer", params={})
    refused(404, "algo_not_found", algo_id=other_algo)  # someone else's saved algorithm
    refused(404, "algo_not_found", algo_id=99999)

    bad = save_algo(client, strategy="buyer", params={})
    row = db.get(UserAlgo, bad)
    row.source, row.strategy_key = "import os\n", ""  # saved before the code rules tightened, say
    db.commit()
    r = deploy(client, algo_id=bad)
    assert r.status_code == 400 and r.json()["code"] == "invalid_source" and r.json()["problems"]

    assert live_account(db, user_id(client)).cash == D(100000)  # nothing moved
    assert client.get("/api/deployments").json() == []


def test_another_users_deployment_is_a_404(client: TestClient, second_client: TestClient, db: Session):
    dep_id = deploy(client, library_key="buyer").json()["id"]
    b = second_client
    assert b.get("/api/deployments").json() == []
    assert b.get(f"/api/deployments/{dep_id}").status_code == 404
    for action in ("pause", "resume", "stop"):
        assert b.post(f"/api/deployments/{dep_id}/{action}").status_code == 404
    assert client.get(f"/api/deployments/{dep_id}").json()["status"] == "active"
    assert live_account(db, user_id(b)).cash == D(100000)


# --- pause, resume, stop ---------------------------------------------------------------------------


def test_pause_stops_new_orders_but_protection_still_fires_then_resume(
    client: TestClient, db: Session, fake_provider: FakeProvider, ticking
):
    fake_provider.set_price(SYMBOL, D("100"))
    out = deploy(client, library_key="buyer").json()
    dep = db.get(Deployment, out["id"])
    run_twice(db, fake_provider, ticking)
    (trade,) = db.scalars(select(Trade).where(Trade.account_id == dep.account_id)).all()
    ctx = deployments.dep_context(db, fake_provider, dep)
    engine.set_protection(ctx, trade.id, D("95"), None)

    paused = client.post(f"/api/deployments/{out['id']}/pause").json()
    assert paused["status"] == "paused" and out["id"] not in deployments._runs
    assert client.post(f"/api/deployments/{out['id']}/pause").status_code == 409

    fake_provider.set_price(SYMBOL, D("90"))  # through the stop
    ticking.advance()
    deployments.run_deployments_once(db, fake_provider)
    db.refresh(trade)
    assert trade.status == "closed"  # the stop-loss on a real position still fired
    ticking.advance()
    deployments.run_deployments_once(db, fake_provider)
    ticking.advance()
    deployments.run_deployments_once(db, fake_provider)
    # Flat, and a Buyer would buy at once if it were running: it placed nothing.
    assert [(o.side, o.origin) for o in orders_of(db, dep.id)].count(("buy", "user")) == 1
    assert len(orders_of(db, dep.id)) == 2 and out["id"] not in deployments._runs

    assert client.post(f"/api/deployments/{out['id']}/resume").json()["status"] == "active"
    assert client.post(f"/api/deployments/{out['id']}/resume").status_code == 409
    run_twice(db, fake_provider, ticking)
    assert [o.side for o in orders_of(db, dep.id)].count("buy") == 2  # trading again


def test_stop_with_the_market_closed_waits_then_returns_the_cash(
    client: TestClient, db: Session, fake_provider, ticking, monkeypatch
):
    uid = user_id(client)
    market = force_market(monkeypatch, True)
    algo_id = save_algo(client, source=BUYER_SOURCE)
    out = deploy(client, algo_id=algo_id).json()
    dep_id = out["id"]
    for _ in range(3):
        deployments.run_deployments_once(db, fake_provider)
        ticking.advance()
    sandbox = deployments._runs[dep_id].sandbox
    assert sandbox is not None and sandbox.process is not None and sandbox.process.is_alive()
    dep = db.get(Deployment, dep_id)
    account = db.get(Account, dep.account_id)
    (trade,) = db.scalars(select(Trade).where(Trade.account_id == account.id)).all()
    assert trade.status == "open"

    market["open"] = False
    stopping = client.post(f"/api/deployments/{dep_id}/stop").json()
    assert stopping["status"] == "stopping" and dep_id not in deployments._runs
    sandbox.process.join(5)
    assert not sandbox.process.is_alive()  # the sandbox child is closed
    waiting = db.scalars(select(Order).where(Order.account_id == account.id, Order.status == "open")).all()
    assert len(waiting) == 1 and waiting[0].trade_id == trade.id and waiting[0].side == "sell"
    deployments.run_deployments_once(db, fake_provider)  # still closed: nothing changes
    assert db.get(Deployment, dep_id).status == "stopping" and live_account(db, uid).cash == D(70000)

    market["open"] = True
    ticking.advance()
    deployments.run_deployments_once(db, fake_provider)  # the exit fills, the account is flat
    db.refresh(dep)
    db.refresh(account)
    assert dep.status == "stopped" and dep.stopped_at is not None
    assert account.cash == 0 and account.margin_used == 0
    returned = D(30000) + account.realized_pnl
    assert live_account(db, uid).cash == D(70000) + returned
    transfers = [(t.kind, t.amount) for t in db.scalars(select(CashTransfer).order_by(CashTransfer.id))]
    assert transfers == [("fund", D(30000)), ("return", returned)]
    final = client.get(f"/api/deployments/{dep_id}").json()
    assert final["status"] == "stopped" and D(final["equity"]) == returned and D(final["unrealized_pnl"]) == 0
    assert client.post(f"/api/deployments/{dep_id}/stop").json()["status"] == "stopped"  # repeat is fine
    assert client.post(f"/api/deployments/{dep_id}/resume").status_code == 409


def test_stop_when_the_market_is_open_finishes_at_once(
    client: TestClient, db: Session, fake_provider, ticking
):
    out = deploy(client, library_key="buyer").json()
    run_twice(db, fake_provider, ticking)
    assert client.post(f"/api/deployments/{out['id']}/stop").json()["status"] == "stopped"
    assert db.scalars(select(Trade).where(Trade.status == "open")).all() == []


# --- the money -------------------------------------------------------------------------------------


def test_capital_out_plus_cash_back_plus_pnl_reconciles_to_the_paisa(
    client: TestClient, db: Session, fake_provider: FakeProvider, ticking, zero_costs
):
    """By hand, with no charges: the live account holds 100000.
    Deploy 30000 -> live 70000, algo account 30000.
    Buy 10 at 100.00 -> algo cash 30000 - 1000 = 29000.
    Price 103.50, stop -> sell 10 -> algo cash 29000 + 1035 = 30035, realized = 1035 - 1000 = 35.
    The 30035 goes home: live 70000 + 30035 = 100035 = 100000 + 35 of profit, and the algo account
    is left at 0, so no money was created or lost."""
    uid = user_id(client)
    fake_provider.set_price(SYMBOL, D("100"))
    out = deploy(client, library_key="buyer").json()
    dep = db.get(Deployment, out["id"])
    assert live_account(db, uid).cash == D(70000)
    run_twice(db, fake_provider, ticking)
    account = db.get(Account, dep.account_id)
    assert account.cash == D(29000)

    fake_provider.set_price(SYMBOL, D("103.50"))
    stopped = client.post(f"/api/deployments/{dep.id}/stop").json()
    assert stopped["status"] == "stopped"
    db.refresh(account)
    assert account.cash == 0 and account.realized_pnl == D(35)
    assert live_account(db, uid).cash == D(100035)
    assert D(stopped["equity"]) == D(30035) and D(stopped["realized_pnl"]) == D(35)
    funded = sum(t.amount for t in db.scalars(select(CashTransfer).where(CashTransfer.kind == "fund")))
    back = sum(t.amount for t in db.scalars(select(CashTransfer).where(CashTransfer.kind == "return")))
    assert (funded, back, back - funded) == (D(30000), D(30035), D(35))


# --- badges ----------------------------------------------------------------------------------------


def test_deployment_trades_do_not_earn_live_trading_badges(
    client: TestClient, db: Session, fake_provider, ticking
):
    uid = user_id(client)
    out = deploy(client, library_key="buyer").json()
    run_twice(db, fake_provider, ticking)
    assert orders_of(db, out["id"])
    client.post(f"/api/deployments/{out['id']}/stop")
    assert evaluate_user(db, uid, clock.now()) == set()  # filled, closed trades on an algo account

    assert (
        client.post("/api/orders", json={"symbol": SYMBOL, "side": "buy", "quantity": "1"}).status_code == 200
    )
    assert evaluate_user(db, uid, clock.now())  # the same trade on the live account does earn one
