"""Block graphs to strategy source.

A graph is plain JSON::

    {
      "nodes": [{"id": "n1", "type": "rsi_below", "params": {"period": 14}, "position": {"x": 0, "y": 0},
                 "label": "optional name shown on the block"}],
      "edges": [{"source": "n1", "source_port": "signal", "target": "n2", "target_port": "signal"}],
      "custom_blocks": [{"type": "custom:7", "name": "...", "kind": "group" | "code", "definition": {...}}]
    }

Signal and Combine blocks output a `signal` (true or false per symbol per bar). An action takes one
signal on its `signal` input and gives out a `trigger`; Risk blocks take that `trigger` to attach to
the action. Combine blocks take `signals` (All of / Any of) or one `signal` (Not). Custom blocks
live in `custom_blocks` and are explained in `custom.py`. `position` is for the editor only.
Universe nodes may also carry a `symbols` list: the editor's default test symbols, never compiled.

`validate_graph` returns plain-sentence problems, each with the node it is about. `compile_graph`
writes one readable Strategy class and checks it with the site's own validator before returning.
The output depends only on the graph's content (not on node order or positions), so equal graphs
give identical bytes.
"""

import ast
import itertools
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from string import Template
from typing import Any

from app.algos.api import Param, _coerce
from app.algos.blocks import custom
from app.algos.blocks.catalog import (
    CATALOG,
    CATEGORIES,
    ENTRY_ACTIONS,
    MARKETS_FOR,
    SLUG_HINTS,
    TRIGGER,
    WARMUP_MARGIN,
    BlockSpec,
    literal,
    render_param,
)
from app.algos.rules import MAX_WARMUP_BARS
from app.algos.validate import validate_source

MAX_NODES = 200
MAX_EDGES = 600


@dataclass(frozen=True)
class GraphProblem:
    """Something to fix, in a plain sentence. `node_id` is the block it is about (None: the graph)."""

    node_id: str | None
    message: str


class GraphInvalid(ValueError):
    def __init__(self, problems: list[GraphProblem]):
        super().__init__(" ".join(p.message for p in problems))
        self.problems = problems


class CompilerBug(RuntimeError):
    """The compiler wrote code the site's own rules refuse: a bug here, never the user's graph."""


# --- reading a graph ---------------------------------------------------------------------


def _text(value: Any) -> str:
    """Text from the graph on one line with unprintable characters dropped (it ends up in comments)."""
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in " ".join(value.split()) if ch.isprintable())


def _noun_of(param: Param) -> str:
    return param.label.lower() or "setting"


def _bounds(param: Param) -> str:
    lo, hi = param.min, param.max
    if lo is not None and hi is not None:
        return f"between {lo:f} and {hi:f}" if isinstance(lo, Decimal) else f"between {lo} and {hi}"
    return f"at least {lo}" if lo is not None else f"at most {hi}"


def node_values(raw: dict, spec: BlockSpec) -> tuple[dict[str, Any], list[str]]:
    """A node's settings in their own types (missing ones take the default) and one sentence per bad one."""
    given = raw.get("params")
    errors: list[str] = []
    if given is None:
        given = {}
    if not isinstance(given, dict):
        return {}, [f"This {spec.noun} block's settings must be an object."]
    for key in given:
        if key not in spec.params and not (spec.type == "universe" and key == "symbols"):
            errors.append(f"This {spec.noun} block has no setting called '{key}'.")
    values: dict[str, Any] = {}
    for name, param in spec.params.items():
        value = given.get(name)
        value = param.default if value is None else value
        noun = f"This {spec.noun} block's {_noun_of(param)}"
        try:
            value = _coerce(param, value)
        except ValueError as why:
            errors.append(f"{noun} must be {why}.")
            continue
        if param.kind in ("int", "decimal") and (
            (param.min is not None and value < param.min) or (param.max is not None and value > param.max)
        ):
            errors.append(f"{noun} must be {_bounds(param)}.")
            continue
        values[name] = value
    return values, errors


def _spec_table(graph: dict) -> tuple[dict[str, BlockSpec], dict[str, dict], dict[str, str]]:
    """Catalog plus the graph's custom blocks: specs by type, entries by type, and the sentence for
    each damaged entry."""
    specs, entries, damaged = dict(CATALOG), {}, {}
    raw_entries = graph.get("custom_blocks") or []
    for entry in raw_entries if isinstance(raw_entries, list) else []:
        kind = entry.get("type") if isinstance(entry, dict) else None
        if not isinstance(kind, str):
            continue
        try:
            specs[kind] = custom.custom_spec(entry, node_values)
            entries[kind] = {**entry, "name": custom.entry_name(entry)}
        except ValueError as why:
            damaged[kind] = f"The custom block '{_text(entry.get('name')) or kind}' is damaged: {why}"
    return specs, entries, damaged


def _label(raw: dict, spec: BlockSpec) -> str:
    return _text(raw.get("label"))[:60] or spec.label


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:30].strip("_")
    if not slug:
        return "block"
    return slug if slug[0].isalpha() else "b" + slug


# --- validation --------------------------------------------------------------------------


def validate_graph(graph: Any, *, fragment_output: str | None = None) -> list[GraphProblem]:
    """Every problem with `graph`, in plain sentences. `fragment_output` checks a group block's
    inner graph instead of a whole algorithm: no Universe or actions, and that node's signal is
    what the group gives out."""
    problems: list[GraphProblem] = []

    def add(node_id: str | None, message: str) -> None:
        problems.append(GraphProblem(node_id, message))

    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return [GraphProblem(None, "The graph needs a list of blocks (`nodes`).")]
    raw_edges = graph.get("edges") or []
    if not isinstance(raw_edges, list):
        return [GraphProblem(None, "The graph's connections (`edges`) must be a list.")]
    if len(graph["nodes"]) > MAX_NODES or len(raw_edges) > MAX_EDGES:
        return [
            GraphProblem(None, f"A graph can have at most {MAX_NODES} blocks and {MAX_EDGES} connections.")
        ]
    specs, entries, damaged = _spec_table(graph)

    nodes: dict[str, tuple[dict, BlockSpec, dict[str, Any]]] = {}
    for raw in graph["nodes"]:
        node_id = raw.get("id") if isinstance(raw, dict) else None
        if not isinstance(node_id, str) or not node_id:
            add(None, "Every block needs an id.")
            continue
        if node_id in nodes:
            add(node_id, "Two blocks share the same id.")
            continue
        spec = specs.get(raw.get("type"))
        if spec is None:
            add(
                node_id,
                damaged.get(raw.get("type")) or f"This block has an unknown type ({raw.get('type')!r}).",
            )
            continue
        if fragment_output is not None and spec.category not in ("signal", "combine"):
            add(node_id, f"A group can only hold Signal and Combine blocks, not {spec.noun}.")
        values, errors = node_values(raw, spec)
        for sentence in errors:
            add(node_id, sentence)
        nodes[node_id] = (raw, spec, values)

    checked: set[str] = set()
    for node_id, (_, spec, _) in sorted(nodes.items()):
        if spec.custom_kind and spec.type not in checked:
            checked.add(spec.type)
            entry = entries[spec.type]
            for found in validate_custom(entry["kind"], entry["name"], entry["definition"]):
                add(node_id, f"The custom block '{entry['name']}' has a problem: {found.message}")

    universes = [i for i, (_, s, _) in nodes.items() if s.type == "universe"]
    if fragment_output is None and len(universes) != 1:
        if universes:
            for extra in sorted(universes)[1:]:
                add(extra, "Add exactly one Universe block.")
        else:
            add(None, "Add exactly one Universe block.")
    if fragment_output is not None and fragment_output not in nodes:
        add(None, "The group's output must be one of its blocks.")

    # Connections.
    incoming: dict[tuple[str, str], list[str]] = defaultdict(list)
    edges: list[tuple[str, str, str, str]] = []
    for e in raw_edges:
        fields = [
            e.get(k) if isinstance(e, dict) else None
            for k in ("source", "source_port", "target", "target_port")
        ]
        if not all(isinstance(f, str) for f in fields):
            add(None, "A connection is missing its source, target or port names.")
            continue
        src, sport, dst, dport = fields
        if src not in nodes or dst not in nodes:
            add(
                src if src in nodes else dst if dst in nodes else None,
                "A connection points at a block that isn't there.",
            )
            continue
        sspec, tspec = nodes[src][1], nodes[dst][1]
        out = next((p for p in sspec.outputs if p.name == sport), None)
        inp = next((p for p in tspec.inputs if p.name == dport), None)
        if out is None:
            add(src, f"This {sspec.noun} block has no '{sport}' output.")
        elif inp is None:
            add(dst, f"This {tspec.noun} block has no '{dport}' input.")
        elif out.type != inp.type:
            add(dst, f"A {sspec.noun} block can't connect to this {tspec.noun} block's {dport} input.")
        else:
            incoming[(dst, dport)].append(src)
            edges.append((src, sport, dst, dport))

    # What each block needs plugged in.
    for node_id, (_, spec, _) in nodes.items():
        for port in spec.inputs:
            n = len(incoming[(node_id, port.name)])
            if port.type == TRIGGER:
                if n == 0:
                    add(node_id, f"This {spec.noun} block isn't attached to an action.")
            elif n == 0 and port.min <= 1:
                add(node_id, f"This {spec.noun} block has no signal connected.")
            elif n < port.min:
                add(
                    node_id,
                    f"This {spec.noun} block needs at least {port.min} signals connected, but has {n}.",
                )
            if not port.multi and n > 1:
                add(node_id, f"This {spec.noun} block takes only one {port.type}, but {n} are connected.")

    # Loops: whatever a topological order can't reach feeds itself.
    order = _topological(nodes, edges)
    for node_id in sorted(set(nodes) - set(order)):
        add(node_id, "This block is part of a loop: blocks can't feed into each other in a circle.")

    # Risk blocks.
    attached: dict[str, list[str]] = defaultdict(list)  # action id -> risk block types
    for node_id, (_, spec, _) in nodes.items():
        if spec.category != "risk":
            continue
        for action_id in incoming[(node_id, "trigger")]:
            action_type = nodes[action_id][1].type
            if action_type not in ENTRY_ACTIONS:
                add(
                    node_id,
                    f"A {spec.noun} block attaches only to Buy or Short, not {nodes[action_id][1].noun}.",
                )
            else:
                attached[action_id].append(spec.type)
    for action_id, kinds in attached.items():
        noun = nodes[action_id][1].noun
        for kind in sorted({k for k in kinds if kinds.count(k) > 1}):
            add(
                action_id,
                f"This {noun} block has more than one {CATALOG[kind].noun} block attached; keep one.",
            )
    for action_type in ENTRY_ACTIONS:
        protected = sorted(
            i
            for i, k in attached.items()
            if nodes[i][1].type == action_type and {"stop_loss", "target"} & set(k)
        )
        for extra in protected[1:]:
            add(
                extra,
                f"Only one {nodes[extra][1].noun} block can carry a Stop-loss or Target: "
                "protection belongs to the position, not to the block that opened it.",
            )

    # Everything must lead somewhere.
    used = {s for s, _, _, _ in edges}
    if fragment_output is None:
        if not any(
            s.category == "action" or (s.custom_kind == "code" and s.inputs) for _, s, _ in nodes.values()
        ):
            add(None, "Add at least one action block: Buy, Sell all, Short or Exit all.")
        for node_id, (_, spec, _) in nodes.items():
            if spec.outputs and spec.category != "action" and node_id not in used:
                add(node_id, f"This {spec.noun} block isn't connected to anything.")
    elif fragment_output in nodes:
        reaches, todo = {fragment_output}, [fragment_output]
        while todo:
            current = todo.pop()
            for s, _, d, _ in edges:
                if d == current and s not in reaches:
                    reaches.add(s)
                    todo.append(s)
        for node_id, (_, spec, _) in nodes.items():
            if node_id not in reaches:
                add(node_id, f"This {spec.noun} block doesn't lead to the group's output.")

    # Rules across settings, and the bar size.
    interval = next((nodes[u][2].get("interval") for u in universes[:1]), None)
    for node_id, (_, spec, values) in nodes.items():
        for left, _, right, clause in spec.rules:
            if left in values and right in values and not values[left] < values[right]:
                add(node_id, f"This {spec.noun} block's {clause}.")
        if spec.type == "trading_hours" and interval in ("1d", "1wk"):
            add(
                node_id,
                "This Trading-hours block needs bars shorter than a day; change the bar size.",
            )

    if not problems and fragment_output is None:
        bars = warmup_for(graph)
        if bars > MAX_WARMUP_BARS:
            add(
                None,
                f"These blocks need {bars} bars of history; the limit is {MAX_WARMUP_BARS}.",
            )
    return problems


def _topological(nodes: dict, edges: list[tuple[str, str, str, str]]) -> list[str]:
    """Node ids in an order where every block comes after the blocks feeding it (ties by id); a
    block inside a loop is left out."""
    waiting = {i: 0 for i in nodes}
    feeds: dict[str, list[str]] = defaultdict(list)
    for s, _, d, _ in edges:
        waiting[d] += 1
        feeds[s].append(d)
    ready = sorted(i for i, n in waiting.items() if n == 0)
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for d in sorted(feeds[current]):
            waiting[d] -= 1
            if waiting[d] == 0:
                ready.append(d)
                ready.sort()
    return order


# --- flattening: custom groups are inlined -------------------------------------------------


@dataclass
class RNode:
    """One block of the flattened graph. Group blocks are gone, replaced by their inner blocks."""

    id: str
    spec: BlockSpec
    values: dict[str, Any]
    label: str
    owner: str  # id of the top-level block this came from
    exposed: dict[str, str] = field(default_factory=dict)  # setting -> group setting name
    code: dict | None = None  # a code block's definition
    owner_label: str = ""  # label of the top-level block, which names a group's inner blocks
    slug: str = ""
    names: dict[str, str] = field(default_factory=dict)  # setting -> strategy parameter name

    @property
    def role(self) -> str:
        if self.spec.type == "universe":
            return "universe"
        if self.spec.category == "risk":
            return "risk"
        if self.spec.category == "action" or (self.code is not None and self.spec.inputs):
            return "action"
        return "signal"


def _flatten(graph: dict) -> tuple[dict[str, RNode], list[tuple[str, str, str, str]]]:
    """The graph with every group replaced by its inner blocks (ids `<group id>/<inner id>`) and
    its connections rewired. Needs a graph that passed `validate_graph`."""
    specs, entries, _ = _spec_table(graph)
    nodes: dict[str, RNode] = {}
    outputs: dict[str, str] = {}  # group instance id -> the inner node that gives its signal
    edges: list[tuple[str, str, str, str]] = []
    for raw in sorted(graph["nodes"], key=lambda n: n["id"]):
        spec = specs[raw["type"]]
        values, _ = node_values(raw, spec)
        label = _label(raw, spec)
        if spec.custom_kind != "group":
            code = entries[spec.type]["definition"] if spec.custom_kind == "code" else None
            nodes[raw["id"]] = RNode(raw["id"], spec, values, label, raw["id"], owner_label=label, code=code)
            continue
        definition = entries[spec.type]["definition"]
        inner = {n["id"]: n for n in definition["nodes"]}
        inner_values = {i: node_values(n, CATALOG[n["type"]])[0] for i, n in inner.items()}
        exposed: dict[str, dict[str, str]] = defaultdict(dict)
        for item in definition.get("exposed") or []:
            for target in item["targets"]:
                inner_values[target["node"]][target["param"]] = values[item["name"]]
                exposed[target["node"]][target["param"]] = item["name"]
        for inner_id in sorted(inner):
            inner_spec = CATALOG[inner[inner_id]["type"]]
            rid = f"{raw['id']}/{inner_id}"
            nodes[rid] = RNode(
                rid, inner_spec, inner_values[inner_id], _label(inner[inner_id], inner_spec),
                raw["id"], exposed[inner_id], owner_label=label,
            )  # fmt: skip
        outputs[raw["id"]] = f"{raw['id']}/{definition['output']}"
        for e in definition.get("edges") or []:
            edges.append(
                (
                    f"{raw['id']}/{e['source']}",
                    e["source_port"],
                    f"{raw['id']}/{e['target']}",
                    e["target_port"],
                )
            )
    for e in graph.get("edges") or []:
        edges.append((outputs.get(e["source"], e["source"]), e["source_port"], e["target"], e["target_port"]))
    return nodes, sorted(set(edges))


def _arith(expr: str) -> int:
    """Whole-number arithmetic over + - * and numbers, for lookback templates."""

    def walk(node: ast.AST) -> int:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            a, b = walk(node.left), walk(node.right)
            return a + b if isinstance(node.op, ast.Add) else a - b if isinstance(node.op, ast.Sub) else a * b
        raise ValueError(f"Can't read the lookback {expr!r}.")

    return walk(ast.parse(expr, mode="eval").body)


def lookback_of(rnode: RNode) -> int:
    """Bars of history this block needs with its current settings."""
    return _arith(Template(rnode.spec.lookback).substitute({k: str(v) for k, v in rnode.values.items()}))


def warmup_for(graph: dict) -> int:
    """The literal `warmup_bars` the compiled strategy declares: the longest lookback plus a margin."""
    nodes, _ = _flatten(graph)
    return max([lookback_of(n) for n in nodes.values()] + [0]) + WARMUP_MARGIN


# --- naming ------------------------------------------------------------------------------


def _base_slug(rnode: RNode) -> str:
    """The word a block's names start with: its label, or a short one for the long catalog labels."""
    if rnode.label == rnode.spec.label and rnode.spec.type in SLUG_HINTS:
        return SLUG_HINTS[rnode.spec.type]
    return _slug(rnode.label)


def _name_everything(nodes: dict[str, RNode]) -> None:
    """Give every block a unique slug and every setting a unique strategy parameter name,
    `<block label>_<setting>`, walking blocks in id order so equal graphs get equal names."""
    used_slugs: set[str] = set()
    used_params: set[str] = set()
    by_owner: dict[str, list[RNode]] = defaultdict(list)
    for rid in sorted(nodes):
        by_owner[nodes[rid].owner].append(nodes[rid])
    for owner in sorted(by_owner):
        group = by_owner[owner]
        top = next((n for n in group if n.id == owner), None)
        label = top.label if top else group[0].owner_label
        base = _base_slug(top) if top else _slug(label)
        for n in itertools.count(1):
            owner_slug = base if n == 1 else f"{base}_{n}"
            slugs: dict[str, str] = {}
            local: dict[str, int] = {}
            for rnode in group:
                if rnode.id == owner:
                    slugs[rnode.id] = owner_slug
                    continue
                inner = _base_slug(rnode)
                local[inner] = local.get(inner, 0) + 1
                slugs[rnode.id] = f"{owner_slug}_{inner}" + (f"_{local[inner]}" if local[inner] > 1 else "")
            params: dict[str, dict[str, str]] = {}
            for rnode in group:
                params[rnode.id] = {
                    p: (
                        f"{owner_slug}_{rnode.exposed[p]}" if p in rnode.exposed else f"{slugs[rnode.id]}_{p}"
                    )
                    for p in rnode.spec.params
                }
            names = {name for per in params.values() for name in per.values()}
            if not (set(slugs.values()) & used_slugs) and not (names & used_params):
                break
        used_slugs |= set(slugs.values())
        used_params |= names
        for rnode in group:
            rnode.slug, rnode.names = slugs[rnode.id], params[rnode.id]


# --- writing the source ------------------------------------------------------------------

_ACTION_ORDER = {"sell_all": 0, "exit_all": 1}  # leave first, then enter; other actions after


def _comment(text: str) -> str:
    return " ".join(text.split())


def _p(name: str) -> str:
    return f'p["{name}"]'


def compile_graph(graph: dict, name: str = "", description: str = "") -> str:
    """The strategy source for `graph`. Raises `GraphInvalid` when the graph has problems, and
    `CompilerBug` if the result would not pass the site's code rules."""
    problems = validate_graph(graph)
    if problems:
        raise GraphInvalid(problems)
    nodes, edges = _flatten(graph)
    _name_everything(nodes)

    incoming: dict[tuple[str, str], list[str]] = defaultdict(list)
    attached: dict[str, list[RNode]] = defaultdict(list)  # action id -> risk blocks
    for src, _, dst, dport in edges:
        incoming[(dst, dport)].append(src)
        if nodes[dst].role == "risk":
            attached[src].append(nodes[dst])

    universe = next(n for n in nodes.values() if n.role == "universe")
    order = [nodes[i] for i in _topological(nodes, [e for e in edges if nodes[e[2]].role != "risk"])]
    signals = [n for n in order if n.role == "signal"]
    actions = sorted(
        (n for n in nodes.values() if n.role == "action"),
        key=lambda n: (_ACTION_ORDER.get(n.spec.type, 2), n.id),
    )
    leaves = [
        n
        for n in sorted(nodes.values(), key=lambda n: (CATEGORIES.index(n.spec.category), n.id))
        if n.role != "universe"
    ]

    # Parameters.
    parameters: dict[str, str] = {}
    for n in leaves:
        for pname, param in n.spec.params.items():
            final = n.names[pname]
            if final in parameters:
                continue  # a group setting shared by several inner blocks
            bound = Param(
                param.kind, n.values[pname], min=param.min, max=param.max,
                choices=param.choices, help=param.help, label=param.label,
            )  # fmt: skip
            shown = param.label if pname in n.exposed else f"{n.label}: {param.label}"
            parameters[final] = render_param(bound, shown)

    def expressions(n: RNode) -> dict[str, str]:
        return {pname: _p(final) for pname, final in n.names.items()}

    lookbacks = [
        Template(n.spec.lookback).substitute(expressions(n)) for n in leaves if n.spec.lookback != "0"
    ] or ["0"]
    warmup = max([lookback_of(n) for n in leaves] + [0]) + WARMUP_MARGIN

    longest = lookbacks[0] if len(lookbacks) == 1 else f"max({', '.join(lookbacks)})"
    extra_imports: set[str] = set()
    methods: list[str] = []
    variables: dict[str, str] = {}  # signal block id -> variable in on_bar
    calc: list[str] = []

    for n in signals:
        var = variables[n.id] = f"sig_{n.slug}"
        sources = sorted(incoming[(n.id, "signals")] + incoming[(n.id, "signal")])
        if n.spec.category == "combine":
            ins = [variables[s] for s in sources]
            joined = (
                f"not {ins[0]}"
                if n.spec.snippet == "not"
                else (" and " if n.spec.snippet == "all" else " or ").join(ins)
            )
            calc.append(f"            {var} = {joined}")
            continue
        method = f"signal_{n.slug}" if n.code is None else f"code_{n.slug}"
        if n.code is None:
            body = Template(n.spec.snippet).substitute(expressions(n)).splitlines()
            methods += [
                f"    # {_comment(n.label)}: {_comment(n.spec.help)}",
                f"    def {method}(self, ctx, symbol):",
                "        p = ctx.params",
                *[f"        {line}" if line else "" for line in body],
                "",
            ]
            calc.append(f"            {var} = self.{method}(ctx, symbol)")
        else:
            methods += _code_method(n, method, extra_imports)
            calc.append(f"            {var} = bool(self.{method}(ctx, symbol{_code_args(n)}))")

    hours_lines: list[str] = []
    protect: list[str] = []
    action_lines: list[str] = []
    for a in actions:
        sig = variables[incoming[(a.id, "signal")][0]]
        gates: list[str] = []
        stop = target = None
        for risk in sorted(attached[a.id], key=lambda r: r.id):
            ex = expressions(risk)
            if risk.spec.type == "stop_loss":
                stop = ex["percent"]
            elif risk.spec.type == "target":
                target = ex["percent"]
            elif risk.spec.type == "max_open_trades":
                gates.append(f"len(ctx.open_trades()) < {ex['count']}")
            elif risk.spec.type == "trading_hours":
                s = risk.slug
                hours_lines += [
                    f"        minute_{s} = (ctx.now.hour * 60 + ctx.now.minute + {ex['utc_offset_minutes']}) % 1440",  # noqa: E501
                    f"        start_{s} = {ex['start_hour']} * 60 + {ex['start_minute']}",
                    f"        end_{s} = {ex['end_hour']} * 60 + {ex['end_minute']}",
                    f"        in_hours_{s} = (start_{s} <= minute_{s} < end_{s}) if start_{s} <= end_{s} "
                    f"else (minute_{s} >= start_{s} or minute_{s} < end_{s})",
                ]
                gates.append(f"in_hours_{s}")
        if stop or target:
            direction = "long" if a.spec.type == "buy" else "short"
            sign_stop, sign_target = ("-", "+") if direction == "long" else ("+", "-")
            unset = " and ".join(
                f"trade.{k}_price is None" for k, v in (("stop", stop), ("target", target)) if v
            )
            args = []
            if stop:
                args.append(f"stop=ctx.price(symbol) * (1 {sign_stop} {stop} / 100)")
            if target:
                args.append(f"target=ctx.price(symbol) * (1 {sign_target} {target} / 100)")
            protect += [
                f"            # {_comment(a.label)}: protect the trades it opened",
                "            for trade in ctx.open_trades(symbol):",
                f'                if trade.direction == "{direction}" and {unset}:',
                f"                    ctx.set_protection(trade.id, {', '.join(args)})",
            ]
        action_lines.append(f"            # {_comment(a.label)}")
        action_lines.append(f"            if {sig}:")
        if a.code is not None:
            method = f"code_{a.slug}"
            methods += _code_method(a, method, extra_imports)
            action_lines.append(f"                self.{method}(ctx, symbol{_code_args(a)})")
            continue
        mapping = expressions(a) | {"gate": "".join(f" and {g}" for g in gates)}
        action_lines += [
            f"                {line}" for line in Template(a.spec.snippet).substitute(mapping).splitlines()
        ]

    checks = []
    for n in leaves:
        for left, _, right, clause in n.spec.rules:
            checks.append(
                f"        if params[{literal(n.names[left])}] >= params[{literal(n.names[right])}]:\n"
                f"            problems.append({literal(f'{n.label}: the {clause}.')})"
            )

    uses_decimal = any("Decimal(" in v for v in parameters.values())
    imports = sorted(extra_imports | ({"from decimal import Decimal"} if uses_decimal else set()))
    chosen = MARKETS_FOR[universe.values["markets"]]
    markets = ", ".join(literal(m) for m in chosen) + ("," if len(chosen) == 1 else "")
    title = _text(name) or "Block algorithm"
    summary = (
        _text(description) or "Built from blocks: " + ", ".join(sorted({n.spec.label for n in leaves})) + "."
    )
    out = [*imports, "import hq", "", "", "class BlockStrategy(hq.Strategy):"]
    out += [
        f"    name = {literal(title)}",
        f"    description = {literal(summary)}",
        f"    markets = ({markets})",
        f"    interval = {literal(universe.values['interval'])}",
        f"    warmup_bars = {warmup}",
        "    PARAMETERS = {" + ("" if parameters else "}"),
    ]
    if parameters:
        out += [f"        {literal(k)}: {v}," for k, v in parameters.items()] + ["    }"]
    out += [
        "",
        "    def on_start(self, ctx):",
        "        p = ctx.params",
        "        # Longest history any block needs, plus a margin.",
    ]
    out += [f"        self.warmup_bars = {longest} + {WARMUP_MARGIN}", ""]
    if checks:
        out += [
            "    @classmethod",
            "    def check_params(cls, params):",
            "        problems = []",
            *checks,
            "        return problems",
            "",
        ]
    out += ["    def on_bar(self, ctx):", "        p = ctx.params", *hours_lines]
    out += ["        for symbol in ctx.symbols:", *calc, *protect, *action_lines, ""]
    out += methods
    source = "\n".join(out).rstrip("\n") + "\n"

    report = validate_source(source)
    if not report.ok:
        raise CompilerBug(
            "The block compiler wrote code the site's rules refuse. This is a bug in the compiler, "
            "not in your graph: " + " ".join(p.message for p in report.problems)
        )
    return source


def _code_args(n: RNode) -> str:
    assert n.code is not None
    if not custom.unpack_code_block(n.code)[2]:
        return ""
    declared = custom.code_params(n.code)
    return ", {" + ", ".join(f"{literal(k)}: {_p(n.names[k])}" for k in declared) + "}"


def _code_method(n: RNode, method: str, imports: set[str]) -> list[str]:
    """A custom code block as a method of the compiled class, under a name of its own."""
    assert n.code is not None
    found, _, takes_params, body = custom.unpack_code_block(n.code)
    imports.update(found)
    return [
        f"    # {_comment(n.label)}: your code block",
        f"    def {method}(self, ctx, symbol{', params' if takes_params else ''}):",
        *[f"        {line}" if line else "" for line in body],
        "",
    ]


# --- custom block definitions -------------------------------------------------------------


def validate_custom(kind: str, name: str, definition: Any, *, runner=None) -> list[custom.Problem]:
    """Problems with a custom block someone is saving, as line-numbered problems (line 0: not
    about a line). A group is checked as a graph; code is checked against the site's code rules."""
    if not isinstance(definition, dict):
        return [custom.Problem(0, 0, "bad_block", "The block's definition must be an object.")]
    if kind == "code":
        return custom.check_code_block(definition, runner=runner)
    if kind != "group":
        return [custom.Problem(0, 0, "bad_block", "A custom block's kind must be 'group' or 'code'.")]
    output = definition.get("output")
    inner = {"nodes": definition.get("nodes"), "edges": definition.get("edges") or []}
    problems = [
        custom.Problem(
            0, 0, "bad_block", p.message if p.node_id is None else f"{p.message} (block {p.node_id})"
        )
        for p in validate_graph(inner, fragment_output=output if isinstance(output, str) else "")
    ]
    if problems:
        return problems
    try:
        custom.custom_spec(
            {"type": "custom:0", "name": name or "x", "kind": "group", "definition": definition}, node_values
        )
    except ValueError as why:
        return [custom.Problem(0, 0, "bad_block", str(why))]
    outputs = next((n for n in inner["nodes"] if n["id"] == output), None)
    if outputs is None or CATALOG[outputs["type"]].category not in ("signal", "combine"):
        return [custom.Problem(0, 0, "bad_block", "The group's output must be a Signal or Combine block.")]
    return []


def graph_has_code_blocks(graph: dict) -> bool:
    return any(isinstance(e, dict) and e.get("kind") == "code" for e in (graph.get("custom_blocks") or []))
