"""The block editor's backend: the catalog, the graph compiler and custom blocks.

Blocks compile to ordinary strategy source, so what matters most is that the source passes the
site's own validator, behaves like the hand-written algorithm it stands for, and that a person's
graph is theirs alone.
"""

import copy
import math
import multiprocessing
import random
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.algos.backtest import run_backtest
from app.algos.blocks.catalog import CATALOG
from app.algos.blocks.compile import GraphInvalid, compile_graph, validate_custom, validate_graph
from app.algos.validate import validate_and_dry_run, validate_source
from app.market_data.base import Bar
from app.market_data.fake import FakeProvider

D = Decimal
TODAY = date(2026, 3, 2)


def node(node_id: str, type_: str, **params) -> dict:
    return {"id": node_id, "type": type_, "params": params, "position": {"x": 0, "y": 0}}


def edge(source: str, target: str, source_port: str = "signal", target_port: str = "signal") -> dict:
    return {"source": source, "source_port": source_port, "target": target, "target_port": target_port}


def rsi_dip_graph(period=14, oversold=30, exit_level=55, stop=5, cash=50) -> dict:
    """RSI below -> Buy with a stop-loss; RSI above -> Sell all: `rsi_reversion` as blocks."""
    return {
        "nodes": [
            node("u", "universe", interval="1d"),
            node("low", "rsi_below", period=period, level=oversold),
            node("high", "rsi_above", period=period, level=exit_level),
            node("buy", "buy", percent_of_cash=cash),
            node("stop", "stop_loss", percent=stop),
            node("sell", "sell_all"),
        ],
        "edges": [
            edge("low", "buy"),
            edge("buy", "stop", "trigger", "trigger"),
            edge("high", "sell"),
        ],
    }


def problems_of(graph: dict) -> list[tuple[str | None, str]]:
    return [(p.node_id, p.message) for p in validate_graph(graph)]


# --- the equivalence promise -----------------------------------------------------------------


class SeriesProvider(FakeProvider):
    """The fake provider, except AAPL's daily bars swing up and down so an RSI strategy trades."""

    def __init__(self) -> None:
        super().__init__()
        self.bars: list[Bar] = []
        day, i, previous = date(2025, 10, 1), 0, D(100)
        while day <= date(2026, 2, 27):
            if day.weekday() < 5:
                close = D(str(round(100 + 14 * math.sin(i / 3.0) + i * 0.05, 2)))
                self.bars.append(
                    Bar(
                        day.isoformat(),
                        previous,
                        max(previous, close) + 1,
                        min(previous, close) - 1,
                        close,
                        1000,
                    )
                )
                previous, i = close, i + 1
            day += timedelta(days=1)

    def get_history(self, symbol, interval, start, end):
        if symbol == "AAPL" and interval == "1d":
            return [b for b in self.bars if start <= date.fromisoformat(str(b.time)) <= end]
        return super().get_history(symbol, interval, start, end)


def backtest(db: Session, **how):
    return run_backtest(
        db, SeriesProvider(), symbols=["AAPL"], interval="1d", start=date(2026, 1, 12), end=date(2026, 2, 27),
        starting_cash=D(100000), account_currency="USD", today=TODAY, **how,
    )  # fmt: skip


@pytest.mark.usefixtures("zero_costs")
def test_an_rsi_dip_buyer_made_of_blocks_trades_exactly_like_the_library_algo(db: Session):
    # Settings that make the series trade often; the same numbers go to both.
    shared = dict(period=7, oversold=40, exit_level=52, stop=4, cash=60)
    library = backtest(
        db,
        strategy_key="rsi_reversion",
        params={
            "period": 7, "oversold": 40, "exit_level": 52, "stop_loss_percent": 4, "percent_of_cash": 60,
        },
    )  # fmt: skip
    source = compile_graph(rsi_dip_graph(**shared), "RSI dip", "Buys dips.")
    blocks = backtest(db, source=source, params={})

    assert len(library.trades) >= 2  # the comparison means something
    assert blocks.trades == library.trades
    assert blocks.orders == library.orders
    assert blocks.metrics.final_equity == library.metrics.final_equity
    assert multiprocessing.active_children() == []


# --- every catalog block compiles -----------------------------------------------------------


def minimal_graph(type_: str) -> dict:
    """The smallest valid graph that holds one block of `type_`."""
    nodes = [node("u", "universe", interval="1h" if type_ == "trading_hours" else "1d")]
    edges: list[dict] = []
    if type_ in ("all_of", "any_of"):
        nodes += [node("a", "rsi_below"), node("b", "rsi_above"), node("x", type_), node("act", "sell_all")]
        edges += [
            edge("a", "x", target_port="signals"),
            edge("b", "x", target_port="signals"),
            edge("x", "act"),
        ]
    elif type_ == "not":
        nodes += [node("a", "rsi_below"), node("x", "not"), node("act", "sell_all")]
        edges += [edge("a", "x"), edge("x", "act")]
    elif CATALOG[type_].category == "risk":
        nodes += [node("a", "rsi_below"), node("act", "buy"), node("x", type_)]
        edges += [edge("a", "act"), edge("act", "x", "trigger", "trigger")]
    elif CATALOG[type_].category == "action":
        nodes += [node("a", "rsi_below"), node("x", type_)]
        edges += [edge("a", "x")]
    elif type_ == "universe":
        nodes += [node("a", "rsi_below"), node("act", "sell_all")]
        edges += [edge("a", "act")]
    else:  # a signal
        nodes += [node("x", type_), node("act", "sell_all")]
        edges += [edge("x", "act")]
    return {"nodes": nodes, "edges": edges}


@pytest.mark.parametrize("type_", sorted(CATALOG))
def test_the_compiled_source_of_every_block_passes_the_validator_and_runs(type_: str):
    graph = minimal_graph(type_)
    assert validate_graph(graph) == []
    source = compile_graph(graph, "One block", "")
    report = validate_and_dry_run(source)  # the site's checks, then a run over made-up prices
    assert report.ok, report.problems
    assert report.meta is not None and report.meta.warmup_bars >= 5


def test_every_block_has_help_bounds_and_ports_of_a_known_kind():
    for spec in CATALOG.values():
        assert spec.help.endswith(".") and spec.label
        for port in (*spec.inputs, *spec.outputs):
            assert port.type in ("signal", "trigger")
        for param in spec.params.values():
            assert param.label and param.help
    assert {s.category for s in CATALOG.values()} == {"universe", "signal", "combine", "action", "risk"}
    # Only the Combine blocks carry logic: nothing in the palette is an if/else.
    assert {s.type for s in CATALOG.values() if s.category == "combine"} == {"all_of", "any_of", "not"}


def test_the_declared_warmup_is_the_longest_lookback_plus_a_margin():
    graph = rsi_dip_graph(period=20)
    graph["nodes"].append(node("sma", "price_vs_sma", period=60))
    graph["nodes"].append(node("sell2", "sell_all"))
    graph["edges"].append(edge("sma", "sell2"))
    meta = validate_source(compile_graph(graph, "W", "")).meta
    assert meta is not None and meta.warmup_bars == 60 + 5  # the 60-bar average is the longest


# --- plain-sentence graph problems ------------------------------------------------------------


def broken(change) -> dict:
    graph = copy.deepcopy(rsi_dip_graph())
    change(graph)
    return graph


CASES = [
    ("no universe", lambda g: g["nodes"].pop(0), None, "Add exactly one Universe block."),
    (
        "two universes",
        lambda g: g["nodes"].append(node("u2", "universe")),
        "u2",
        "Add exactly one Universe block.",
    ),
    ("buy without a signal", lambda g: g["edges"].pop(0), "buy", "This Buy block has no signal connected."),
    (
        "period out of bounds",
        lambda g: g["nodes"][1]["params"].update(period=1),
        "low",
        "This RSI block's period must be between 2 and 400.",
    ),
    (
        "level not a number",
        lambda g: g["nodes"][1]["params"].update(level="high"),
        "low",
        "This RSI block's level must be a whole number.",
    ),
    (
        "a setting that doesn't exist",
        lambda g: g["nodes"][1]["params"].update(colour=3),
        "low",
        "This RSI block has no setting called 'colour'.",
    ),
    (
        "dangling edge",
        lambda g: g["edges"].append(edge("low", "ghost")),
        "low",
        "A connection points at a block that isn't there.",
    ),
    (
        "wrong port",
        lambda g: g["edges"].append(edge("low", "sell", target_port="nope")),
        "sell",
        "This Sell all block has no 'nope' input.",
    ),
    (
        "signal into a risk block",
        lambda g: g["edges"].append(edge("low", "stop", target_port="trigger")),
        "stop",
        "can't connect to this Stop-loss block",
    ),
    (
        "unattached risk block",
        lambda g: g["edges"].pop(1),
        "stop",
        "This Stop-loss block isn't attached to an action.",
    ),
    (
        "risk on a sell",
        lambda g: g["edges"].append(edge("sell", "stop", "trigger", "trigger")),
        "stop",
        "attaches only to Buy or Short",
    ),
    (
        "unused signal",
        lambda g: g["nodes"].append(node("spare", "volume_spike")),
        "spare",
        "This Volume spike block isn't connected to anything.",
    ),
    (
        "no action",
        lambda g: (
            g["nodes"].__delitem__(slice(3, 6)),
            g["edges"].clear(),
            g["edges"].append(edge("low", "high")),
        ),
        None,
        "Add at least one action block",
    ),
    (
        "fast not below slow",
        lambda g: (
            g["nodes"].extend(
                [node("x", "sma_cross", fast_period=30, slow_period=30), node("s2", "sell_all")]
            )
            or g["edges"].append(edge("x", "s2"))
        ),
        "x",
        "This SMA crossover block's fast period must be below the slow period",
    ),
    (
        "trading hours on daily bars",
        lambda g: (
            g["nodes"].append(node("h", "trading_hours"))
            or g["edges"].append(edge("buy", "h", "trigger", "trigger"))
        ),
        "h",
        "needs bars shorter than a day",
    ),
    (
        "two stops on one buy",
        lambda g: (
            g["nodes"].append(node("stop2", "stop_loss"))
            or g["edges"].append(edge("buy", "stop2", "trigger", "trigger"))
        ),
        "buy",
        "more than one Stop-loss block attached",
    ),
    ("unknown type", lambda g: g["nodes"].append(node("z", "teleport")), "z", "unknown type"),
]


@pytest.mark.parametrize(("label", "change", "node_id", "text"), CASES, ids=[c[0] for c in CASES])
def test_graph_problems_are_plain_sentences_naming_the_block(label, change, node_id, text):
    found = problems_of(broken(change))
    assert any(i == node_id and text in m for i, m in found), found


def test_a_combine_block_needs_two_signals_and_a_loop_is_refused():
    graph = {
        "nodes": [
            node("u", "universe"),
            node("a", "rsi_below"),
            node("all", "all_of"),
            node("any", "any_of"),
            node("sell", "sell_all"),
        ],
        "edges": [edge("a", "all", target_port="signals"), edge("all", "sell")],
    }
    assert ("all", "This All of block needs at least 2 signals connected, but has 1.") in problems_of(graph)
    graph["edges"] = [
        edge("all", "any", target_port="signals"),
        edge("any", "all", target_port="signals"),
        edge("any", "sell"),
    ]
    messages = dict(problems_of(graph))
    assert "loop" in messages["all"] and "loop" in messages["any"]


def test_compiling_a_bad_graph_raises_with_the_same_problems():
    with pytest.raises(GraphInvalid) as why:
        compile_graph(broken(lambda g: g["edges"].pop(0)), "x", "")
    assert ("buy", "This Buy block has no signal connected.") in [
        (p.node_id, p.message) for p in why.value.problems
    ]


def test_a_graph_that_is_not_a_graph_is_a_problem_not_a_crash():
    assert problems_of(None) and problems_of({"nodes": "no"}) and problems_of({"nodes": [3], "edges": [4]})


# --- determinism ------------------------------------------------------------------------------


def test_the_same_graph_compiles_to_the_same_bytes_whatever_its_order_or_positions():
    graph = rsi_dip_graph()
    first = compile_graph(graph, "Same", "Same graph.")
    assert compile_graph(copy.deepcopy(graph), "Same", "Same graph.") == first
    shuffled = copy.deepcopy(graph)
    random.Random(4).shuffle(shuffled["nodes"])
    random.Random(5).shuffle(shuffled["edges"])
    for n in shuffled["nodes"]:
        n["position"] = {"x": 999, "y": -3}
    assert compile_graph(shuffled, "Same", "Same graph.") == first
    changed = rsi_dip_graph(period=15)
    assert compile_graph(changed, "Same", "Same graph.") != first


def test_blocks_of_one_kind_get_their_own_named_parameters():
    graph = rsi_dip_graph()
    graph["nodes"].append(node("low2", "rsi_below", level=20))
    graph["nodes"].append(node("sell2", "sell_all"))
    graph["edges"].append(edge("low2", "sell2"))
    meta = validate_source(compile_graph(graph, "Twice", "")).meta
    assert meta is not None
    assert {"rsi_below_period", "rsi_below_2_period", "rsi_below_2_level", "stop_loss_percent"} <= set(
        meta.parameters
    )


# --- custom blocks: groups ------------------------------------------------------------------


GROUP = {
    "nodes": [
        node("dip", "rsi_below", period=14, level=35),
        node("trend", "price_vs_sma", period=50, side="above"),
        node("both", "all_of"),
    ],
    "edges": [edge("dip", "both", target_port="signals"), edge("trend", "both", target_port="signals")],
    "output": "both",
    "exposed": [
        {"name": "rsi_period", "label": "RSI period", "targets": [{"node": "dip", "param": "period"}]},
        {"name": "level", "targets": [{"node": "dip", "param": "level"}]},
    ],
}


def group_graph(**instance_params) -> dict:
    return {
        "nodes": [node("u", "universe"), node("g", "custom:3", **instance_params), node("act", "sell_all")],
        "edges": [edge("g", "act")],
        "custom_blocks": [
            {"type": "custom:3", "name": "Dip in uptrend", "kind": "group", "definition": GROUP}
        ],
    }


def test_a_group_block_is_inlined_with_its_inner_blocks_and_exposed_settings():
    graph = group_graph(rsi_period=10)
    assert validate_graph(graph) == []
    source = compile_graph(graph, "Grouped", "")
    report = validate_and_dry_run(source)
    assert report.ok, report.problems
    meta = report.meta
    assert meta is not None
    # The exposed settings are named for the group; the inner blocks' other settings keep their own.
    assert meta.parameters["dip_in_uptrend_rsi_period"].default == 10
    assert meta.parameters["dip_in_uptrend_level"].default == 35  # the inner block's own value
    assert meta.parameters["dip_in_uptrend_price_vs_sma_period"].default == 50
    assert "def signal_dip_in_uptrend_rsi_below" in source and "sig_dip_in_uptrend_all_of" in source
    assert meta.warmup_bars == 50 + 5  # the inlined 50-bar average
    assert validate_custom("group", "Dip", GROUP) == []


def test_a_group_with_a_damaged_definition_is_refused_in_a_sentence():
    bad = copy.deepcopy(GROUP)
    bad["output"] = "missing"
    assert validate_custom("group", "Bad", bad)
    loose = copy.deepcopy(GROUP)
    loose["nodes"].append(node("spare", "volume_spike"))
    assert any(
        "doesn't lead to the group's output" in p.message for p in validate_custom("group", "Loose", loose)
    )
    action = copy.deepcopy(GROUP)
    action["nodes"].append(node("a", "sell_all"))
    assert any("only hold Signal and Combine" in p.message for p in validate_custom("group", "Act", action))
    graph = group_graph()
    graph["custom_blocks"][0]["definition"] = bad
    assert any("custom block 'Dip in uptrend'" in m for _, m in problems_of(graph))


# --- custom blocks: code --------------------------------------------------------------------


GOOD_CODE = {
    "mode": "signal",
    "lookback": 12,
    "params": [{"name": "bars", "kind": "int", "default": 10, "min": 2, "max": 100, "label": "Bars"}],
    "code": (
        "def signal(ctx, symbol, params):\n"
        "    closes = ctx.close_series(symbol, params['bars'] + 1)\n"
        "    return len(closes) > params['bars'] and closes[-1] < closes[0]\n"
    ),
}


def test_code_with_a_forbidden_import_is_refused_with_the_snippets_own_line_number():
    code = dict(GOOD_CODE, code="import os\n\ndef signal(ctx, symbol, params):\n    return True\n")
    found = validate_custom("code", "Bad", code)
    assert (
        found and found[0].line == 1 and found[0].message.startswith("Line 1:") and "os" in found[0].message
    )
    later = dict(GOOD_CODE, code="def signal(ctx, symbol, params):\n    x = 1\n    return eval('1')\n")
    (p,) = validate_custom("code", "Bad", later)
    assert p.line == 3 and p.message.startswith("Line 3:")
    syntax = dict(GOOD_CODE, code="def signal(ctx, symbol, params):\n    return (\n")
    assert validate_custom("code", "Bad", syntax)[0].line >= 1


def test_code_must_be_one_function_with_the_right_name_and_arguments():
    for code, text in [
        (
            "x = 1\ndef signal(ctx, symbol, params):\n    return True\n",
            "only imports and the `signal` function",
        ),
        ("def act(ctx, symbol):\n    pass\n", "needs a function named `signal(ctx, symbol)`"),
        ("def signal(ctx):\n    return True\n", "write `def signal(ctx, symbol):`"),
    ]:
        found = validate_custom("code", "Bad", dict(GOOD_CODE, code=code))
        assert any(text in p.message for p in found), (code, found)
    assert validate_custom("code", "Bad", dict(GOOD_CODE, lookback=None))


def test_a_code_block_compiles_into_the_strategy_and_trades(client: TestClient, db: Session):
    made = client.post(
        "/api/blocks/custom", json={"name": "Falling", "kind": "code", "definition": GOOD_CODE}
    )
    assert made.status_code == 200, made.text
    type_ = made.json()["type"]
    graph = {
        "nodes": [
            node("u", "universe"),
            node("f", type_, bars=6),
            node("buy", "buy", percent_of_cash=50),
            node("exit", "rsi_above", period=7, level=55),
            node("sell", "sell_all"),
        ],
        "edges": [edge("f", "buy"), edge("exit", "sell")],
    }
    r = client.post("/api/blocks/compile", json={"graph": graph, "name": "Code", "description": ""})
    body = r.json()
    assert r.status_code == 200 and body["ok"], body
    assert "def code_falling(self, ctx, symbol, params):" in body["source"]
    assert 'p["falling_bars"]' in body["source"] and body["warmup_bars"] == 12 + 5
    assert validate_source(body["source"]).ok

    results = backtest(db, source=body["source"], params={})
    assert results.errors == [] and len(results.trades) >= 1
    # The setting is on the strategy, so the lab's parameter form reaches the block's code.
    wide = backtest(db, source=body["source"], params={"falling_bars": 40})
    assert wide.errors == []


def test_a_code_block_with_a_runtime_error_is_caught_when_it_is_saved(client: TestClient):
    crash = dict(GOOD_CODE, code="def signal(ctx, symbol, params):\n    return 1 / 0\n")
    r = client.post("/api/blocks/custom", json={"name": "Crash", "kind": "code", "definition": crash})
    assert r.status_code == 400 and "Line" in r.json()["detail"]


def test_refusing_a_code_block_over_http_carries_the_line(client: TestClient):
    code = dict(GOOD_CODE, code="import os\n\ndef signal(ctx, symbol, params):\n    return True\n")
    r = client.post("/api/blocks/custom", json={"name": "Bad", "kind": "code", "definition": code})
    assert r.status_code == 400 and "Line 1:" in r.json()["detail"]


# --- the routes -------------------------------------------------------------------------------


def test_the_catalog_lists_every_block_and_the_users_own(client: TestClient, second_client: TestClient):
    blocks = client.get("/api/blocks/catalog").json()["blocks"]
    assert {b["type"] for b in blocks} == set(CATALOG)
    rsi = next(b for b in blocks if b["type"] == "rsi_below")
    assert rsi["category"] == "signal" and rsi["lookback"] == "$period + 1"
    assert {p["name"] for p in rsi["params"]} == {"period", "level"}
    assert rsi["outputs"] == [{"name": "signal", "type": "signal", "multi": False, "min": 1}]

    made = client.post(
        "/api/blocks/custom", json={"name": "Dip in uptrend", "kind": "group", "definition": GROUP}
    )
    assert made.status_code == 200, made.text
    mine = client.get("/api/blocks/catalog").json()["blocks"]
    custom_block = next(b for b in mine if b["type"] == made.json()["type"])
    assert custom_block["custom_kind"] == "group" and custom_block["custom_id"] == made.json()["id"]
    assert [p["name"] for p in custom_block["params"]] == ["rsi_period", "level"]
    assert custom_block["params"][0]["default"] == 14 and custom_block["outputs"][0]["name"] == "signal"
    assert {b["type"] for b in second_client.get("/api/blocks/catalog").json()["blocks"]} == set(CATALOG)


def test_blocks_routes_need_a_login(anon_client: TestClient):
    for method, url in [
        ("get", "/api/blocks/catalog"),
        ("post", "/api/blocks/compile"),
        ("get", "/api/blocks/custom"),
        ("post", "/api/blocks/custom"),
        ("get", "/api/blocks/custom/1"),
    ]:
        assert getattr(anon_client, method)(url).status_code == 401, url


def test_compile_returns_problems_with_node_ids_or_the_source(client: TestClient):
    bad = client.post("/api/blocks/compile", json={"graph": broken(lambda g: g["edges"].pop(0))}).json()
    assert bad["ok"] is False and bad["source"] == ""
    sentence = "This Buy block has no signal connected."
    assert {"node_id": "buy", "line": 0, "col": 0, "code": "", "message": sentence} in bad["problems"]
    good = client.post(
        "/api/blocks/compile", json={"graph": rsi_dip_graph(), "name": "RSI dip", "description": "Buys dips."}
    ).json()
    assert good["ok"] and good["problems"] == [] and good["warmup_bars"] == 20
    assert good["source"] == compile_graph(rsi_dip_graph(), "RSI dip", "Buys dips.")


def test_custom_blocks_are_created_read_changed_and_deleted_by_their_owner(client: TestClient):
    made = client.post(
        "/api/blocks/custom", json={"name": "  Dip   in uptrend ", "kind": "group", "definition": GROUP}
    )
    assert made.status_code == 200, made.text
    row = made.json()
    assert row["name"] == "Dip in uptrend" and row["type"] == f"custom:{row['id']}" and row["kind"] == "group"
    url = f"/api/blocks/custom/{row['id']}"
    assert client.get(url).json()["definition"] == GROUP
    assert [r["id"] for r in client.get("/api/blocks/custom").json()] == [row["id"]]
    renamed = client.put(url, json={"name": "Renamed", "kind": "group", "definition": GROUP})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Renamed"
    bad = client.put(
        url, json={"name": "Renamed", "kind": "group", "definition": {**GROUP, "output": "nope"}}
    )
    assert bad.status_code == 400 and client.get(url).json()["definition"]["output"] == "both"
    assert client.delete(url).status_code == 204 and client.get(url).status_code == 404


def test_one_users_custom_blocks_are_invisible_to_another(client: TestClient, second_client: TestClient):
    made = client.post(
        "/api/blocks/custom", json={"name": "Mine", "kind": "group", "definition": GROUP}
    ).json()
    url = f"/api/blocks/custom/{made['id']}"
    assert second_client.get(url).status_code == 404
    assert (
        second_client.put(url, json={"name": "Stolen", "kind": "group", "definition": GROUP}).status_code
        == 404
    )
    assert second_client.delete(url).status_code == 404
    assert second_client.get("/api/blocks/custom").json() == []
    assert client.get(url).json()["name"] == "Mine"  # untouched

    # A graph of the other user's using that type doesn't pick the block up: it is an unknown type.
    graph = group_graph()
    graph["nodes"][1]["type"] = made["type"]
    graph.pop("custom_blocks")
    refused = second_client.post("/api/blocks/compile", json={"graph": graph}).json()
    assert refused["ok"] is False and "unknown type" in refused["problems"][0]["message"]
    assert (
        client.post("/api/blocks/compile", json={"graph": graph}).json()["ok"] is True
    )  # the owner's picks it up


# --- saved block algorithms -------------------------------------------------------------------


def test_a_saved_block_algorithm_keeps_its_graph_and_its_compiled_source(
    client: TestClient, second_client: TestClient
):
    made = client.post(
        "/api/algos/mine", json={"name": "Dip buyer", "description": "d", "graph": rsi_dip_graph()}
    )
    assert made.status_code == 200, made.text
    saved = made.json()
    assert saved["source"] == compile_graph(saved["graph"], "Dip buyer", "d")
    assert saved["graph"]["nodes"][1]["params"]["period"] == 14 and saved["strategy"] == ""
    assert saved["interval"] == "1d" and saved["params"]["stop_loss_percent"] == "5"

    owner = client.get(f"/api/algos/mine/{saved['id']}").json()
    assert owner["graph"] == saved["graph"] and owner["source"] == saved["source"]
    assert second_client.get(f"/api/algos/mine/{saved['id']}").status_code == 404
    assert second_client.get("/api/algos/mine").json() == []

    changed = rsi_dip_graph(period=10)
    put = client.put(f"/api/algos/mine/{saved['id']}", json={"name": "Dip buyer", "graph": changed})
    assert put.status_code == 200 and put.json()["graph"]["nodes"][1]["params"]["period"] == 10
    code = client.put(
        f"/api/algos/mine/{saved['id']}", json={"name": "Dip buyer", "source": put.json()["source"]}
    )
    assert code.json()["graph"] is None  # saved as plain code, the graph is gone


def test_saving_a_bad_graph_or_a_mixed_request_is_refused(client: TestClient):
    r = client.post("/api/algos/mine", json={"name": "x", "graph": broken(lambda g: g["edges"].pop(0))})
    assert r.status_code == 400 and "This Buy block has no signal connected." in r.json()["detail"]
    both = client.post(
        "/api/algos/mine", json={"name": "x", "graph": rsi_dip_graph(), "strategy": "rsi_reversion"}
    )
    assert both.status_code == 400


def test_a_saved_block_algorithm_backtests_through_the_saved_source(client: TestClient, db_session: Session):
    saved = client.post(
        "/api/algos/mine", json={"name": "Dip buyer", "graph": rsi_dip_graph(7, 40, 52, 4, 60)}
    ).json()
    row_source = saved["source"]
    results = backtest(db_session, source=row_source, params={})
    assert results.errors == [] and results.trades


# --- keeping graphs private ----------------------------------------------------------------------

LABEL_SENTINEL = "SENTINEL_LABEL_5b2e91"
PARAM_SENTINEL = "47.3159265"


def test_a_block_algorithms_graph_never_reaches_another_user_through_a_listing(
    client: TestClient, second_client: TestClient
):
    graph = rsi_dip_graph(cash=PARAM_SENTINEL)
    graph["nodes"][1]["label"] = LABEL_SENTINEL
    saved = client.post("/api/algos/mine", json={"name": "Secret dip", "graph": graph}).json()
    mine = client.get(f"/api/algos/mine/{saved['id']}").text
    assert (
        LABEL_SENTINEL in mine and PARAM_SENTINEL in mine
    )  # the owner sees it, so the checks below can fail

    from_algo = client.post(
        "/api/marketplace/listings",
        json={
            "name": "Public dip", "tagline": "t", "description": "d", "markets": ["international"],
            "test_symbols": ["AAPL"], "fee_percent": "10", "user_algo_id": saved["id"],
        },
    )  # fmt: skip
    assert from_algo.status_code == 200, from_algo.text
    listing_id = from_algo.json()["id"]
    assert client.post(f"/api/marketplace/listings/{listing_id}/publish").status_code == 200
    from_source = client.post(
        "/api/marketplace/listings",
        json={
            "name": "Public dip 2", "tagline": "t", "description": "d", "markets": ["international"],
            "test_symbols": ["AAPL"], "fee_percent": "10", "source": saved["source"],
        },
    )  # fmt: skip
    assert from_source.status_code == 200, from_source.text
    client.post(f"/api/marketplace/listings/{from_source.json()['id']}/publish")

    for url in [
        "/api/marketplace/listings",
        f"/api/marketplace/listings/{listing_id}",
        f"/api/marketplace/listings/{from_source.json()['id']}",
        "/api/marketplace/mine",
        "/api/algos/mine",
        f"/api/algos/mine/{saved['id']}",
        "/api/blocks/custom",
        "/api/blocks/catalog",
    ]:
        text = second_client.get(url).text
        assert LABEL_SENTINEL not in text and PARAM_SENTINEL not in text, f"{url} leaked the graph"
    assert (
        second_client.get(f"/api/marketplace/listings/{listing_id}").status_code == 200
    )  # the listing is public
