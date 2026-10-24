"""Custom blocks: what a saved definition means.

A custom block entry is `{"type": "custom:<id>", "name", "kind", "definition"}`; the graph carries
the entries it uses under `custom_blocks`, so a saved graph compiles on its own.

`group` definition: `{"nodes": [...], "edges": [...], "output": "<node id>", "exposed": [...]}`.
  The inner graph holds only Signal and Combine blocks; `output` is the node whose signal the
  group gives out. Each `exposed` item is `{"name", "label", "help", "targets": [{"node","param"}]}`
  and becomes one setting of the group that sets all its targets. When compiled, the group is
  inlined into the graph with its node ids prefixed.

`code` definition: `{"mode": "signal"|"act", "code", "lookback", "params": [...]}`.
  `code` holds imports and one function, `signal(ctx, symbol)` returning true or false, or
  `act(ctx, symbol)` that places orders. Add a third argument, `params`, to read the block's
  settings as `params["name"]`. The code follows the same rules as uploaded strategies: it is
  checked as part of a minimal strategy and its problems carry line numbers of this snippet.
"""

import ast
import re
from decimal import Decimal
from typing import Any

from app.algos.api import PARAM_KINDS, Param, _coerce
from app.algos.blocks.catalog import CATALOG, SIGNAL, BlockSpec, Port, literal
from app.algos.rules import MAX_WARMUP_BARS
from app.algos.validate import Problem, dry_run, validate_source

MAX_CODE_CHARS = 20_000
MAX_CODE_PARAMS = 12
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

_LINE_PREFIX = re.compile(r"^Line \d+: ")


def _bad(message: str) -> Problem:
    return Problem(0, 0, "bad_block", message)


# --- settings declared by a definition ---------------------------------------------------


def param_from_definition(item: Any) -> tuple[str, Param]:
    """One declared setting as a `Param`; raises ValueError in a plain sentence."""
    if not isinstance(item, dict):
        raise ValueError("Each setting must be an object with a name, kind and default.")
    name = item.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ValueError(
            "A setting's name must be lower-case letters, digits and underscores, starting with a letter."
        )
    kind = item.get("kind")
    if kind not in PARAM_KINDS:
        raise ValueError(f"Setting '{name}': kind must be one of {', '.join(PARAM_KINDS)}.")
    choices = tuple(str(c) for c in item.get("choices") or ())
    if kind == "choice" and not choices:
        raise ValueError(f"Setting '{name}': a choice needs a list of choices.")
    shell = Param(
        kind,
        choices[0] if kind == "choice" else {"int": 0, "decimal": Decimal(0), "bool": False}[kind],
        choices=choices if kind == "choice" else (),
    )
    try:
        default = _coerce(shell, item.get("default", shell.default))
        lo = hi = None
        if kind in ("int", "decimal"):
            lo = None if item.get("min") is None else _coerce(shell, item["min"])
            hi = None if item.get("max") is None else _coerce(shell, item["max"])
    except ValueError as why:
        raise ValueError(f"Setting '{name}': the default, min and max must be {why}.") from None
    try:
        param = Param(
            kind,
            default,
            min=lo,
            max=hi,
            choices=choices,
            help=str(item.get("help") or ""),
            label=str(item.get("label") or name.replace("_", " ").capitalize()),
        )
    except ValueError as why:
        raise ValueError(f"Setting '{name}': {why}") from None
    return name, param


def code_params(definition: dict) -> dict[str, Param]:
    items = definition.get("params") or []
    if not isinstance(items, list) or len(items) > MAX_CODE_PARAMS:
        raise ValueError(f"A code block takes at most {MAX_CODE_PARAMS} settings.")
    out: dict[str, Param] = {}
    for item in items:
        name, param = param_from_definition(item)
        if name in out:
            raise ValueError(f"Setting '{name}' is declared twice.")
        out[name] = param
    return out


# --- group blocks ------------------------------------------------------------------------


def group_spec(entry: dict, node_values) -> BlockSpec:
    """The spec of a group block: its exposed settings and one signal output. `node_values(raw,
    spec)` is the caller's way to read an inner node's settings (and report their problems)."""
    definition = entry["definition"]
    inner = {n.get("id"): n for n in definition.get("nodes") or [] if isinstance(n, dict)}
    params: dict[str, Param] = {}
    for exposed in definition.get("exposed") or []:
        name = exposed.get("name") if isinstance(exposed, dict) else None
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ValueError("An exposed setting needs a name of lower-case letters, digits and underscores.")
        targets = exposed.get("targets")
        if name in params or not isinstance(targets, list) or not targets:
            raise ValueError(f"Exposed setting '{name}' must be unique and point at a block setting.")
        first: Param | None = None
        default: Any = None
        for target in targets:
            node = inner.get(target.get("node")) if isinstance(target, dict) else None
            spec = CATALOG.get(node.get("type")) if node else None
            if spec is None or target.get("param") not in spec.params:
                raise ValueError(f"Exposed setting '{name}' points at a setting that doesn't exist.")
            if first is None:
                first = spec.params[target["param"]]
                values, _ = node_values(node, spec)
                default = values.get(target["param"], first.default)
        assert first is not None
        params[name] = Param(
            first.kind,
            default,
            min=first.min,
            max=first.max,
            choices=first.choices,
            help=str(exposed.get("help") or first.help),
            label=str(exposed.get("label") or first.label),
        )
    return BlockSpec(
        type=entry["type"],
        category="custom",
        label=entry["name"],
        help=str(definition.get("help") or f"Your group block: {entry['name']}."),
        params=params,
        outputs=(Port("signal", SIGNAL),),
        custom_kind="group",
    )


# --- code blocks -------------------------------------------------------------------------


def code_spec(entry: dict) -> BlockSpec:
    definition = entry["definition"]
    mode = definition.get("mode")
    if mode not in ("signal", "act"):
        raise ValueError("A code block's mode must be 'signal' or 'act'.")
    lookback = definition.get("lookback")
    if isinstance(lookback, bool) or not isinstance(lookback, int) or not 0 <= lookback <= MAX_WARMUP_BARS:
        raise ValueError(
            f"A code block must declare its lookback, a whole number from 0 to {MAX_WARMUP_BARS}."
        )
    return BlockSpec(
        type=entry["type"],
        category="custom",
        label=entry["name"],
        help=str(definition.get("help") or f"Your code block: {entry['name']}."),
        params=code_params(definition),
        inputs=(Port("signal", SIGNAL),) if mode == "act" else (),
        outputs=(Port("signal", SIGNAL),) if mode == "signal" else (),
        lookback=str(lookback),
        custom_kind="code",
    )


def entry_name(entry: Any) -> str:
    name = entry.get("name") if isinstance(entry, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A custom block needs a name.")
    return " ".join(name.split())[:60]


def custom_spec(entry: Any, node_values) -> BlockSpec:
    """The spec for one custom-block entry; raises ValueError with a plain sentence if it is damaged."""
    if not isinstance(entry, dict) or not isinstance(entry.get("type"), str):
        raise ValueError("A custom block entry is missing its type.")
    if not isinstance(entry.get("definition"), dict):
        raise ValueError("A custom block entry is missing its definition.")
    entry = {**entry, "name": entry_name(entry)}
    if entry.get("kind") == "group":
        return group_spec(entry, node_values)
    if entry.get("kind") == "code":
        return code_spec(entry)
    raise ValueError("A custom block's kind must be 'group' or 'code'.")


# --- checking and unpacking a code block's snippet ---------------------------------------


def _snippet_shape(definition: dict) -> tuple[ast.Module | None, ast.FunctionDef | None, list[Problem]]:
    """Parse the snippet and find its one function; problems carry the snippet's own line numbers."""
    code = definition.get("code")
    if not isinstance(code, str) or not code.strip():
        return None, None, [_bad("The code block has no code.")]
    if len(code) > MAX_CODE_CHARS:
        return None, None, [_bad(f"The code is {len(code):,} characters; the limit is {MAX_CODE_CHARS:,}.")]
    try:
        tree = ast.parse(code)
    except SyntaxError as why:
        line = why.lineno or 1
        return (
            None,
            None,
            [
                Problem(
                    line,
                    why.offset or 1,
                    "syntax_error",
                    f"Line {line}: this isn't valid Python — {why.msg}.",
                )
            ],
        )
    except ValueError, RecursionError:
        return None, None, [_bad("The code can't be read.")]
    mode = definition.get("mode")
    entry_name_ = "signal" if mode == "signal" else "act"
    problems: list[Problem] = []
    entry: ast.FunctionDef | None = None
    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(stmt, ast.FunctionDef) and stmt.name == entry_name_ and entry is None:
            entry = stmt
            if stmt.decorator_list:
                problems.append(
                    Problem(
                        stmt.lineno,
                        1,
                        "bad_block",
                        f"Line {stmt.lineno}: `{entry_name_}` can't have a decorator.",
                    )
                )
            names = [a.arg for a in stmt.args.args]
            plain = not (stmt.args.vararg or stmt.args.kwarg or stmt.args.kwonlyargs or stmt.args.defaults)
            if not plain or names not in (["ctx", "symbol"], ["ctx", "symbol", "params"]):
                problems.append(
                    Problem(
                        stmt.lineno, 1, "bad_block",
                        f"Line {stmt.lineno}: write `def {entry_name_}(ctx, symbol):`, "
                        "or add `params` as a third argument to read the settings.",
                    )
                )  # fmt: skip
            continue
        line = getattr(stmt, "lineno", 1)
        problems.append(
            Problem(
                line, 1, "bad_block",
                f"Line {line}: only imports and the `{entry_name_}` function go at the top; "
                f"put helper code inside `{entry_name_}`.",
            )
        )  # fmt: skip
    if entry is None:
        problems.append(_bad(f"The code needs a function named `{entry_name_}(ctx, symbol)`."))
    return tree, entry, problems


def _wrapper(definition: dict, params: dict[str, Param]) -> tuple[str, int]:
    """The snippet inside a minimal strategy, and the number of lines before the snippet."""
    entry_name_ = "signal" if definition["mode"] == "signal" else "act"
    header = "import hq\n\n\n"
    shown = "{" + ", ".join(f"{literal(n)}: {_default_literal(p)}" for n, p in params.items()) + "}"
    footer = (
        "\n\n\nclass Snippet(hq.Strategy):\n"
        '    name = "Code block"\n'
        '    description = "Checks the code of a custom block."\n'
        '    markets = ("india", "international", "crypto")\n'
        '    interval = "1d"\n'
        f"    warmup_bars = {int(definition['lookback'])}\n"
        "    PARAMETERS = {}\n\n"
        "    def on_bar(self, ctx):\n"
        "        for symbol in ctx.symbols:\n"
        f"            {entry_name_}(ctx, symbol{', ' + shown if _takes_params(definition) else ''})\n"
    )
    return header + definition["code"].rstrip("\n") + footer, header.count("\n")


def _default_literal(param: Param) -> str:
    if param.kind == "decimal":
        return f'Decimal("{param.default:f}")'
    return literal(param.default)


def _takes_params(definition: dict) -> bool:
    try:
        tree = ast.parse(definition.get("code") or "")
    except SyntaxError, ValueError, RecursionError:
        return False
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef):
            return [a.arg for a in stmt.args.args][2:] == ["params"]
    return False


def _relative(problems: list[Problem], offset: int, snippet_lines: int) -> list[Problem]:
    out: list[Problem] = []
    for p in problems:
        if offset < p.line <= offset + snippet_lines:
            line = p.line - offset
            out.append(Problem(line, p.col, p.code, _LINE_PREFIX.sub(f"Line {line}: ", p.message, count=1)))
        else:  # raised by the wrapper, not by a line of the snippet
            out.append(Problem(0, 0, p.code, _LINE_PREFIX.sub("", p.message, count=1)))
    return out


def check_code_block(definition: dict, *, runner=None) -> list[Problem]:
    """Every problem with a code block's snippet, numbered by the snippet's own lines. With a
    `runner` the snippet is also played over made-up prices (the site's usual dry run)."""
    try:
        params = code_params(definition)
        code_spec({"type": "custom:0", "name": "x", "definition": definition})
    except ValueError as why:
        return [_bad(str(why))]
    _, _, problems = _snippet_shape(definition)
    if problems:
        return problems
    source, offset = _wrapper(definition, params)
    snippet_lines = definition["code"].rstrip("\n").count("\n") + 1
    report = validate_source(source)
    if not report.ok:
        return _relative(report.problems, offset, snippet_lines)
    if runner is not None:
        return _relative(dry_run(source, runner=runner), offset, snippet_lines)
    return []


def unpack_code_block(definition: dict) -> tuple[list[str], str, bool, list[str]]:
    """(imports, entry function name, takes `params`, body lines) of a checked snippet. The body
    is dedented, ready to be indented again inside a method."""
    tree, entry, _ = _snippet_shape(definition)
    assert tree is not None and entry is not None
    imports = [ast.unparse(s) for s in tree.body if isinstance(s, (ast.Import, ast.ImportFrom))]
    # Re-printed from the syntax tree, so the body can be indented anywhere (comments don't survive).
    body = "\n".join(ast.unparse(stmt) for stmt in entry.body).splitlines()
    return imports, entry.name, [a.arg for a in entry.args.args][2:] == ["params"], body
