"""Hosted mode (HOSTED_MODE=true): a public server refuses every way of bringing code, keeps library
algorithms and code-free block graphs working, exposes the flag on /api/health and caps sandboxes."""

import pytest
from fastapi.testclient import TestClient

from app.algos import sandbox
from app.algos.sandbox import SandboxedStrategy, SandboxError
from app.algos.validate import validate_source
from app.config import get_settings
from tests.test_blocks import GOOD_CODE, edge, node, rsi_dip_graph
from tests.test_marketplace import SMA_SOURCE

CODE = "disabled_in_hosted_mode"


def go_hosted(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    monkeypatch.setenv("HOSTED_MODE", "true")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def refused(response) -> None:
    assert response.status_code == 403, response.text
    body = response.json()
    assert body["code"] == CODE
    assert "own code" in body["detail"]  # a sentence a person can read, not a trace


BACKTEST = {
    "symbols": ["AAPL"], "interval": "1d", "start_date": "2026-01-02", "end_date": "2026-02-27",
}  # fmt: skip


def code_graph(type_: str) -> dict:
    """A graph that uses the code block `type_`."""
    return {
        "nodes": [node("u", "universe"), node("f", type_, bars=6), node("buy", "buy", percent_of_cash=50)],
        "edges": [edge("f", "buy")],
    }


def test_health_reports_the_flag(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    assert client.get("/api/health").json()["hosted_mode"] is False
    go_hosted(monkeypatch)
    assert client.get("/api/health").json()["hosted_mode"] is True


def test_validate_and_saving_source_are_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    library = client.post("/api/algos/mine", json={"name": "Lib", "strategy": "sma_crossover"})
    assert library.status_code == 200
    go_hosted(monkeypatch)
    refused(client.post("/api/algos/validate", json={"source": SMA_SOURCE}))
    refused(client.post("/api/algos/mine", json={"name": "Code", "source": SMA_SOURCE}))
    refused(
        client.put(f"/api/algos/mine/{library.json()['id']}", json={"name": "Code", "source": SMA_SOURCE})
    )
    # Library algorithms and the public lists still work.
    assert (
        client.post("/api/algos/mine", json={"name": "Lib 2", "strategy": "sma_crossover"}).status_code == 200
    )
    assert client.get("/api/algos/library").status_code == 200


def test_block_graphs_work_unless_they_hold_code(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    made = client.post(
        "/api/blocks/custom", json={"name": "Falling", "kind": "code", "definition": GOOD_CODE}
    )
    assert made.status_code == 200, made.text
    type_ = made.json()["type"]
    group_ok = {"name": "Dip", "description": "d", "graph": rsi_dip_graph()}
    go_hosted(monkeypatch)

    plain = client.post("/api/blocks/compile", json={**group_ok, "graph": rsi_dip_graph()})
    assert plain.status_code == 200 and plain.json()["ok"], plain.text
    saved = client.post("/api/algos/mine", json=group_ok)
    assert saved.status_code == 200 and saved.json()["source"], saved.text

    refused(
        client.post("/api/blocks/compile", json={"graph": code_graph(type_), "name": "C", "description": ""})
    )
    refused(client.post("/api/algos/mine", json={"name": "C", "graph": code_graph(type_)}))
    refused(
        client.post("/api/blocks/custom", json={"name": "Again", "kind": "code", "definition": GOOD_CODE})
    )
    refused(
        client.put(
            f"/api/blocks/custom/{made.json()['id']}",
            json={"name": "F", "kind": "code", "definition": GOOD_CODE},
        )
    )


def test_backtests_of_source_are_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    saved = client.post("/api/algos/mine", json={"name": "Code", "source": SMA_SOURCE}).json()
    graph_algo = client.post("/api/algos/mine", json={"name": "Blocks", "graph": rsi_dip_graph()}).json()
    go_hosted(monkeypatch)
    refused(client.post("/api/backtests", json={**BACKTEST, "source": SMA_SOURCE}))
    refused(client.post("/api/backtests", json={**BACKTEST, "algo_id": saved["id"]}))
    # A graph of built-in blocks is our own generated code: it is not refused (it may fail later on
    # data, but never with the hosted-mode code).
    ok = client.post("/api/backtests", json={**BACKTEST, "algo_id": graph_algo["id"]})
    assert ok.json().get("code") != CODE


def test_sims_of_source_are_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    saved = client.post("/api/algos/mine", json={"name": "Code", "source": SMA_SOURCE}).json()
    go_hosted(monkeypatch)
    body = {"symbols": ["AAPL"], "start_date": "2026-01-02", "end_date": "2026-01-09"}
    refused(
        client.post("/api/sim/sessions", json={**body, "strategy": {"kind": "source", "source": SMA_SOURCE}})
    )
    refused(
        client.post("/api/sim/sessions", json={**body, "strategy": {"kind": "mine", "algo_id": saved["id"]}})
    )


def test_deployments_of_source_are_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    saved = client.post("/api/algos/mine", json={"name": "Code", "source": SMA_SOURCE}).json()
    go_hosted(monkeypatch)
    refused(
        client.post("/api/deployments", json={"algo_id": saved["id"], "symbols": ["AAPL"], "capital": "1000"})
    )


def test_listings_from_source_are_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    saved = client.post("/api/algos/mine", json={"name": "Code", "source": SMA_SOURCE}).json()
    listing = {"name": "Mine", "markets": ["international"], "fee_percent": "10"}
    draft = client.post("/api/marketplace/listings", json={**listing, "source": SMA_SOURCE})
    assert draft.status_code == 200, draft.text
    go_hosted(monkeypatch)
    refused(client.post("/api/marketplace/listings", json={**listing, "source": SMA_SOURCE}))
    refused(client.post("/api/marketplace/listings", json={**listing, "user_algo_id": saved["id"]}))
    refused(
        client.put(
            f"/api/marketplace/listings/{draft.json()['id']}", json={"source": SMA_SOURCE + "\n# v2\n"}
        )
    )
    # A change that carries no code is not a code path.
    assert (
        client.put(f"/api/marketplace/listings/{draft.json()['id']}", json={"tagline": "hello"}).status_code
        == 200
    )


def test_sandbox_children_are_capped_in_hosted_mode(monkeypatch: pytest.MonkeyPatch):
    go_hosted(monkeypatch, MAX_SANDBOXES="1")
    monkeypatch.setattr(sandbox, "_slots", None)  # a pool of the size just set
    monkeypatch.setattr(sandbox, "_SLOT_WAIT_SECONDS", 0.05)
    meta = validate_source(SMA_SOURCE).meta
    first, second = SandboxedStrategy(SMA_SOURCE, meta), SandboxedStrategy(SMA_SOURCE, meta)
    first._take_slot()
    with pytest.raises(SandboxError) as busy:
        second._take_slot()
    assert busy.value.code == "sandbox_busy" and "try again" in busy.value.args[0].lower()
    first.close()  # a closed sandbox gives its slot back
    second._take_slot()
    second.close()
    monkeypatch.setattr(sandbox, "_slots", None)


def test_nothing_is_capped_or_refused_outside_hosted_mode(client: TestClient):
    assert sandbox._slot_pool() is None
    assert client.post("/api/algos/validate", json={"source": SMA_SOURCE}).status_code == 200
