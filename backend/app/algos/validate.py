"""Check uploaded strategy code before the site accepts it.

Three layers, cheapest first:

1. `validate_source` parses the text with `ast` and checks every node against an allow-list (a
   deny-list always misses something), plus the name, attribute and import rules of `rules.py`.
   Nothing is executed. Every problem is reported, not just the first.
2. `extract_meta` reads the strategy's name, markets, interval and parameters from the *literals*
   in the class body. The code is never run to learn them.
3. `dry_run` plays the strategy over a small made-up price series and reports an exception with
   the line that raised it. Who runs the code is pluggable (`Runner`): `sandbox.run_in_subprocess`
   is the real one, `run_in_process` below is for fast unit tests.

SECURITY: the in-process runner below is NOT a security boundary. Restricted builtins are easy to
get around for a determined attacker. The AST check is the first line of defence and the
subprocess with OS limits (`sandbox.py`) is the second; this runner only exists so a plain mistake
shows up in the editor with a line number and for fast tests.
"""

import ast
import builtins
import dataclasses
import importlib
import math
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any

from app.algos import hq
from app.algos.api import (
    MAX_LOG_LINES,
    Bar,
    OrderIntent,
    OrderResult,
    Param,
    ParameterError,
    Position,
    StrategyContext,
    TradeInfo,
    validate_params,
)
from app.algos.rules import (
    ALLOWED_DECORATORS,
    ALLOWED_IMPORTS,
    FORBIDDEN_ATTRIBUTES,
    FORBIDDEN_NAMES,
    INTERVALS,
    MAX_SOURCE_BYTES,
    MAX_WARMUP_BARS,
)

# --- results ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Problem:
    """One thing to fix. `line` and `col` are 1-based; line 0 means the file as a whole. `message`
    is a plain sentence that already starts with "Line N: " when there is a line."""

    line: int
    col: int
    code: str
    message: str


@dataclass(frozen=True)
class StrategyMeta:
    name: str
    description: str
    markets: tuple[str, ...]
    interval: str
    parameters: dict[str, Param]
    warmup_bars: int = 0


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    problems: list[Problem] = field(default_factory=list)
    meta: StrategyMeta | None = None


def _problem(node: ast.AST | None, code: str, sentence: str) -> Problem:
    line = getattr(node, "lineno", 0) or 0
    col = (getattr(node, "col_offset", 0) or 0) + 1 if line else 0
    return Problem(line, col, code, f"Line {line}: {sentence}" if line else sentence)


# --- the allow-list ----------------------------------------------------------------------

_ALLOWED_NODE_NAMES = """
Module FunctionDef ClassDef Return Assign AugAssign AnnAssign For While If Raise Try Assert
Import ImportFrom Expr Pass Break Continue ExceptHandler
BoolOp BinOp UnaryOp Lambda IfExp Dict Set ListComp SetComp DictComp GeneratorExp Compare Call
FormattedValue JoinedStr Constant Attribute Subscript Starred Name List Tuple Slice NamedExpr
comprehension arguments arg keyword alias
Load Store Del
And Or Add Sub Mult MatMult Div Mod Pow LShift RShift BitOr BitXor BitAnd FloorDiv
Invert Not UAdd USub Eq NotEq Lt LtE Gt GtE Is IsNot In NotIn
""".split()
_ALLOWED_NODES = tuple(getattr(ast, n) for n in _ALLOWED_NODE_NAMES)

_NODE_REASONS = {
    "With": "`with` isn't allowed — it is for files and locks, which strategies don't use.",
    "Delete": "`del` isn't allowed — assign a new value instead.",
    "Match": "`match` isn't allowed — use `if` and `elif`.",
    "TypeAlias": "`type` statements aren't allowed.",
}

_IMPORT_REASONS = {
    "os": "strategies can't touch files or the system.",
    "sys": "strategies can't touch the interpreter.",
    "subprocess": "strategies can't start other programs.",
    "socket": "strategies can't use the network.",
    "requests": "strategies can't use the network.",
    "urllib": "strategies can't use the network.",
    "http": "strategies can't use the network.",
    "random": "strategies must be deterministic, so there is no randomness.",
    "time": "strategies must be deterministic; read the clock with `ctx.now`.",
    "datetime": "strategies must be deterministic; read the clock with `ctx.now`.",
    "threading": "strategies can't start threads.",
    "multiprocessing": "strategies can't start processes.",
    "asyncio": "strategies can't be asynchronous.",
    "pandas": "use `ctx.indicators` and plain lists instead.",
    "numpy": "use `ctx.indicators` and plain lists instead.",
}

_HQ_ALIASED_AS = ("app.algos", "hq")  # how the built-in algorithms spell `import hq`


def _is_private(name: str) -> bool:
    # A lone `_` is the usual "ignore this" name and can't reach anything.
    return name.startswith("_") and name != "_"


def _check_name(node: ast.AST, name: str, kind: str) -> Problem | None:
    if name in FORBIDDEN_NAMES and kind == "name":
        return _problem(node, "forbidden_name", f"`{name}` isn't allowed — {FORBIDDEN_NAMES[name]}")
    if _is_private(name):
        what = "dunder" if name.startswith("__") and name.endswith("__") else "private"
        return _problem(
            node,
            "private_name",
            f"`{name}` isn't allowed — names starting with an underscore ({what} names) "
            "are how code escapes its limits.",
        )
    if kind == "attribute" and name in FORBIDDEN_ATTRIBUTES:
        return _problem(
            node,
            "forbidden_attribute",
            f"`.{name}` isn't allowed — format text with f-strings instead.",
        )
    return None


def _check_import(node: ast.Import | ast.ImportFrom) -> list[Problem]:
    out: list[Problem] = []
    allowed = ", ".join(f"`{m}`" for m in ALLOWED_IMPORTS)

    def refuse(module: str) -> None:
        reason = _IMPORT_REASONS.get(module.split(".")[0], f"only {allowed} can be imported.")
        out.append(_problem(node, "import_not_allowed", f"`{module}` can't be imported — {reason}"))

    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name not in ALLOWED_IMPORTS:
                refuse(alias.name)
        return out
    module = ("." * node.level) + (node.module or "")
    if node.level == 0 and node.module in ALLOWED_IMPORTS:
        if any(a.name == "*" for a in node.names):
            out.append(
                _problem(node, "star_import", f"`from {module} import *` isn't allowed — name what you use.")
            )
    elif node.level == 0 and node.module == _HQ_ALIASED_AS[0]:
        if [a.name for a in node.names] != [_HQ_ALIASED_AS[1]]:
            refuse(module)
    else:
        refuse(module)
    return out


def _check_tree(tree: ast.Module) -> list[Problem]:
    problems: list[Problem] = []
    allowed_decorators = ", ".join(f"`@{d}`" for d in ALLOWED_DECORATORS)
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            problems.append(_node_problem(node))
            continue
        if isinstance(node, ast.Name):
            problems.append(_check_name(node, node.id, "name"))
        elif isinstance(node, ast.Attribute):
            problems.append(_check_name(node, node.attr, "attribute"))
        elif isinstance(node, ast.arg):
            problems.append(_check_name(node, node.arg, "argument"))
        elif isinstance(node, ast.keyword) and node.arg:
            problems.append(_check_name(node, node.arg, "argument"))
        elif isinstance(node, ast.alias):
            if node.asname:
                problems.append(_check_name(node, node.asname, "argument"))
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                problems.append(
                    _problem(
                        node, "bare_except", "A bare `except:` isn't allowed — write `except Exception:`."
                    )
                )
            if node.name:
                problems.append(_check_name(node, node.name, "argument"))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            problems.extend(_check_import(node))
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            problems.append(_check_name(node, node.name, "argument"))
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Name) and decorator.id in ALLOWED_DECORATORS):
                    problems.append(
                        _problem(
                            decorator,
                            "decorator_not_allowed",
                            f"Only {allowed_decorators} can decorate a function.",
                        )
                    )
        if isinstance(node, ast.ClassDef) and node.keywords:
            problems.append(
                _problem(node, "syntax_not_allowed", "Class keywords such as `metaclass=` aren't allowed.")
            )
    return [p for p in problems if p is not None]


def _node_problem(node: ast.AST) -> Problem:
    kind = type(node).__name__
    if kind in ("Global", "Nonlocal"):
        return _problem(
            node,
            "scope_statement",
            f"`{kind.lower()}` isn't allowed — keep state on `self` instead.",
        )
    if kind in ("AsyncFunctionDef", "AsyncFor", "AsyncWith", "Await"):
        return _problem(
            node, "async_not_allowed", "`async` and `await` aren't allowed — hooks run one after another."
        )
    if kind in ("Yield", "YieldFrom"):
        return _problem(node, "yield_not_allowed", "`yield` isn't allowed — return a list instead.")
    reason = _NODE_REASONS.get(kind, f"this kind of code ({kind}) isn't available in strategies.")
    return _problem(
        node, "syntax_not_allowed", reason if reason.startswith("`") else reason[0].upper() + reason[1:]
    )


# --- literals and metadata ----------------------------------------------------------------


class _NotLiteral(Exception):
    def __init__(self, node: ast.AST):
        self.node = node


def _lit(node: ast.AST) -> Any:
    """The value of a literal expression, without running anything. Numbers, strings, booleans,
    None, tuples, lists, dicts and `Decimal("1.5")` are literals."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        items = [_lit(e) for e in node.elts]
        return tuple(items) if isinstance(node, ast.Tuple) else items
    if isinstance(node, ast.Dict):
        if any(k is None for k in node.keys):
            raise _NotLiteral(node)
        return {_lit(k): _lit(v) for k, v in zip(node.keys, node.values, strict=True)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand = _lit(node.operand)
        if isinstance(operand, (int, float, Decimal)) and not isinstance(operand, bool):
            return -operand if isinstance(node.op, ast.USub) else operand
    if (
        isinstance(node, ast.Call)
        and _callee_name(node.func) == "Decimal"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, (str, int))
    ):
        try:
            return Decimal(node.args[0].value)
        except InvalidOperation:
            raise _NotLiteral(node) from None
    raise _NotLiteral(node)


def _callee_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.attr
    return None


_PARAM_FIELDS = [f.name for f in dataclasses.fields(Param)]


def _param_from_call(name: str, call: ast.AST) -> tuple[Param | None, Problem | None]:
    if not isinstance(call, ast.Call) or _callee_name(call.func) != "Param":
        return None, _problem(
            call, "meta_not_literal", f"Setting `{name}` must be written as `hq.Param(...)`."
        )
    try:
        if len(call.args) > len(_PARAM_FIELDS):
            raise ValueError("Param takes at most 7 values.")
        kwargs = {_PARAM_FIELDS[i]: _lit(a) for i, a in enumerate(call.args)}
        for kw in call.keywords:
            if kw.arg is None or kw.arg not in _PARAM_FIELDS or kw.arg in kwargs:
                raise ValueError(f"Param doesn't take {kw.arg or '**'!r} here.")
            kwargs[kw.arg] = _lit(kw.value)
        return Param(**kwargs), None
    except _NotLiteral as bad:
        return None, _problem(
            bad.node,
            "meta_not_literal",
            f"Setting `{name}` must be written with plain values, not calculations.",
        )
    except (ValueError, TypeError, ArithmeticError) as why:
        return None, _problem(call, "bad_parameter", f"Setting `{name}` is not valid: {why}")


def _is_strategy_base(base: ast.AST, hq_names: set[str], strategy_names: set[str]) -> bool:
    if isinstance(base, ast.Name):
        return base.id in strategy_names
    return (
        isinstance(base, ast.Attribute)
        and base.attr == "Strategy"
        and isinstance(base.value, ast.Name)
        and base.value.id in hq_names
    )


def _strategy_classes(tree: ast.Module) -> list[ast.ClassDef]:
    hq_names: set[str] = set()
    strategy_names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            hq_names |= {a.asname or a.name for a in node.names if a.name == "hq"}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module == "hq":
                strategy_names |= {a.asname or a.name for a in node.names if a.name == "Strategy"}
            elif node.module == _HQ_ALIASED_AS[0]:
                hq_names |= {a.asname or a.name for a in node.names if a.name == "hq"}
    return [
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef)
        and any(_is_strategy_base(b, hq_names, strategy_names) for b in n.bases)
    ]


def extract_meta(tree: ast.Module) -> tuple[StrategyMeta | None, list[Problem]]:
    """The strategy's declared name, description, markets, interval and settings, read from the
    class body's literals; nothing is executed. Also reports a missing or doubled Strategy class.
    The meta is None when it can't be read in full."""
    classes = _strategy_classes(tree)
    if not classes:
        return None, [
            _problem(
                None,
                "no_strategy_class",
                "The file needs one class that subclasses `hq.Strategy`, and none was found.",
            )
        ]
    problems = [
        _problem(
            extra,
            "multiple_strategy_classes",
            f"Only one Strategy class per file; `{extra.name}` is a second "
            f"(the first is `{classes[0].name}`).",
        )
        for extra in classes[1:]
    ]
    cls = classes[0]
    assigned: dict[str, ast.AST] = {}
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            assigned[stmt.targets[0].id] = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            assigned[stmt.target.id] = stmt.value

    values: dict[str, Any] = {}
    broken = False
    for attr in ("name", "description", "markets", "interval", "PARAMETERS"):
        node = assigned.get(attr)
        if node is None:
            problems.append(
                _problem(cls, "meta_missing", f"`{cls.name}` must set `{attr}` in its class body.")
            )
            broken = True
            continue
        if attr == "PARAMETERS":
            continue
        try:
            values[attr] = _lit(node)
        except _NotLiteral as bad:
            problems.append(
                _problem(
                    bad.node,
                    "meta_not_literal",
                    f"`{attr}` must be written as plain values (text, numbers, tuples).",
                )
            )
            broken = True

    name, description = values.get("name"), values.get("description")
    for attr, value in (("name", name), ("description", description)):
        if attr in values and (not isinstance(value, str) or not value.strip()):
            problems.append(
                _problem(assigned[attr], "meta_invalid", f"`{attr}` must be some text, not empty.")
            )
            broken = True
    markets = values.get("markets")
    if "markets" in values and not (
        isinstance(markets, (tuple, list)) and markets and all(isinstance(m, str) and m for m in markets)
    ):
        problems.append(
            _problem(
                assigned["markets"],
                "meta_invalid",
                "`markets` must list at least one market, such as ('india',).",
            )
        )
        broken = True
    interval = values.get("interval")
    if "interval" in values and interval not in INTERVALS:
        problems.append(
            _problem(
                assigned["interval"],
                "bad_interval",
                f"`interval` must be one of {', '.join(INTERVALS)}, not {interval!r}.",
            )
        )
        broken = True

    warmup = 0
    warmup_node = assigned.get("warmup_bars")
    warmup_sentence = (
        "Declare `warmup_bars = <number>` on the class: the most bars your strategy needs "
        "before it can trade."
    )
    if warmup_node is None:
        problems.append(_problem(cls, "meta_missing", warmup_sentence))
        broken = True
    else:
        try:
            literal = _lit(warmup_node)
        except _NotLiteral as bad:
            problems.append(_problem(bad.node, "meta_not_literal", warmup_sentence))
            broken = True
        else:
            if isinstance(literal, bool) or not isinstance(literal, int):
                problems.append(_problem(warmup_node, "meta_not_literal", warmup_sentence))
                broken = True
            elif not 0 <= literal <= MAX_WARMUP_BARS:
                problems.append(
                    _problem(
                        warmup_node,
                        "meta_invalid",
                        f"`warmup_bars` must be between 0 and {MAX_WARMUP_BARS}, not {literal}.",
                    )
                )
                broken = True
            else:
                warmup = literal

    parameters: dict[str, Param] = {}
    declared = assigned.get("PARAMETERS")
    if declared is not None:
        if not isinstance(declared, ast.Dict):
            problems.append(
                _problem(
                    declared, "meta_not_literal", "`PARAMETERS` must be written as a dict of `hq.Param(...)`."
                )
            )
            broken = True
        else:
            for key, value in zip(declared.keys, declared.values, strict=True):
                if not (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and key.value.isidentifier()
                    and not _is_private(key.value)
                ):
                    problems.append(
                        _problem(
                            key or declared,
                            "meta_not_literal",
                            "Each setting's name must be a plain word in quotes.",
                        )
                    )
                    broken = True
                    continue
                param, problem = _param_from_call(key.value, value)
                if problem:
                    problems.append(problem)
                    broken = True
                elif param is not None:
                    parameters[key.value] = param

    if broken:
        return None, problems
    return (
        StrategyMeta(name.strip(), description.strip(), tuple(markets), interval, parameters, warmup),  # type: ignore[union-attr,arg-type]
        problems,
    )


# --- validate ---------------------------------------------------------------------------


def _module_level(tree: ast.Module) -> list[Problem]:
    out: list[Problem] = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Pass)):
            continue
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            continue  # a docstring
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
            try:
                _lit(stmt.value)
                continue
            except _NotLiteral:
                pass
        out.append(
            _problem(
                stmt,
                "module_level_code",
                "Top-level code isn't allowed — only imports, constants (plain values), functions and "
                "classes. "
                "Put this inside a method.",
            )
        )
    return out


def validate_source(source: str) -> ValidationReport:
    """Every problem with `source`, without running it. `meta` is filled whenever it could be read."""
    size = len(source.encode("utf-8", "replace"))
    if size > MAX_SOURCE_BYTES:
        return ValidationReport(
            False,
            [
                Problem(
                    0,
                    0,
                    "too_large",
                    f"The file is {size:,} bytes; the limit is {MAX_SOURCE_BYTES:,} bytes "
                    f"({MAX_SOURCE_BYTES // 1024} KB).",
                )
            ],
        )
    try:
        tree = ast.parse(source)
    except SyntaxError as why:
        line = why.lineno or 1
        return ValidationReport(
            False,
            [
                Problem(
                    line,
                    why.offset or 1,
                    "syntax_error",
                    f"Line {line}: this isn't valid Python — {why.msg}.",
                )
            ],
        )
    except (ValueError, RecursionError, MemoryError) as why:
        reason = "it is nested too deeply" if isinstance(why, RecursionError) else str(why)
        return ValidationReport(
            False, [Problem(1, 1, "syntax_error", f"Line 1: this can't be read — {reason}.")]
        )

    try:
        problems = _check_tree(tree) + _module_level(tree)
        meta, meta_problems = extract_meta(tree)
    except RecursionError:
        return ValidationReport(
            False, [Problem(1, 1, "syntax_error", "Line 1: this can't be read — it is nested too deeply.")]
        )
    problems += meta_problems
    unique = {(p.line, p.col, p.code): p for p in problems}
    ordered = sorted(unique.values(), key=lambda p: (p.line, p.col, p.code))
    return ValidationReport(not ordered, ordered, meta)


# --- dry run ----------------------------------------------------------------------------

FILENAME = "<strategy>"
_FIXTURE_BARS = 300
_MAX_TRACED_LINES = 2_000_000  # runaway-loop guard for the in-process runner only


@dataclass(frozen=True)
class Fixture:
    """What a dry run plays the strategy over: made up, deterministic, the same for every runner."""

    symbols: tuple[str, ...]
    bars: tuple[Bar, ...]  # one series, used for every symbol
    cash: Decimal


@dataclass(frozen=True)
class DryRunOutcome:
    problems: list[Problem]
    orders: int = 0
    logs: tuple[str, ...] = ()


# `Runner` is the seam: `run_in_process` here and `sandbox.run_in_subprocess` take the same source and
# fixture and return the same outcome, so `dry_run` and the API do not care which one runs.
Runner = Callable[[str, Fixture], DryRunOutcome]


def make_fixture(interval: str = "1d") -> Fixture:
    daily = interval in ("1d", "1wk")
    bars: list[Bar] = []
    previous = Decimal("100")
    for i in range(_FIXTURE_BARS):
        close = (Decimal(100) + Decimal(str(round(12 * math.sin(i / 8) + 0.05 * i, 2)))).quantize(
            Decimal("0.01")
        )
        when: str | int = (
            (date(2024, 1, 1) + timedelta(days=i)).isoformat() if daily else 1_700_000_000 + 3600 * i
        )
        bars.append(
            Bar(
                when,
                previous,
                max(previous, close) + 1,
                min(previous, close) - 1,
                close,
                1000 + 100 * (i % 7),
            )
        )
        previous = close
    return Fixture(("DRY",), tuple(bars), Decimal("100000"))


class _FakeBackend:
    """A tiny stand-in for the engine: orders fill at the next bar's open, stops and targets are
    honoured, nothing costs anything. It exists to exercise the strategy's code paths."""

    def __init__(self, fixture: Fixture):
        self.symbols = fixture.symbols
        self._bars = fixture.bars
        self._cash = fixture.cash
        self.idx = 0
        self.orders = 0
        self.logs: list[str] = []
        self.trades: list[TradeInfo] = []
        self._pending: list[OrderIntent] = []

    def now(self) -> datetime:
        return datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=self.idx)

    def cash(self) -> Decimal:
        return self._cash

    def available_cash(self) -> Decimal:
        return self._cash

    def bars(self, symbol: str, n: int) -> tuple[Bar, ...]:
        return self._bars[max(0, self.idx + 1 - n) : self.idx + 1] if n > 0 else ()

    def price(self, symbol: str) -> Decimal:
        return self._bars[self.idx].close

    def _open(self, symbol: str | None) -> list[TradeInfo]:
        return [t for t in self.trades if t.status == "open" and symbol in (None, t.symbol)]

    def position(self, symbol: str) -> Position:
        held = self._open(symbol)
        qty = sum((t.quantity if t.direction == "long" else -t.quantity for t in held), Decimal(0))
        total = sum((t.quantity for t in held), Decimal(0))
        return Position(
            symbol,
            qty,
            sum((t.quantity * t.entry_price for t in held), Decimal(0)) / total if total else Decimal(0),
        )

    def open_trades(self, symbol: str | None) -> tuple[TradeInfo, ...]:
        return tuple(self._open(symbol))

    def queue(self, intent: OrderIntent) -> None:
        self.orders += 1
        self._pending.append(intent)

    def set_protection(self, trade_id: int, stop: Decimal | None, target: Decimal | None) -> OrderResult:
        for i, t in enumerate(self.trades):
            if t.id == trade_id and t.status == "open":
                self.trades[i] = dataclasses.replace(t, stop_price=stop, target_price=target)
                return OrderResult(True)
        return OrderResult(False, f"There is no open trade {trade_id}.")

    def log(self, message: str) -> None:
        if len(self.logs) < MAX_LOG_LINES:
            self.logs.append(message)

    # --- stepping ---
    def _close(self, i: int, price: Decimal, how: str) -> TradeInfo:
        t = self.trades[i]
        sign = 1 if t.direction == "long" else -1
        self._cash += t.quantity * price * sign
        done = dataclasses.replace(
            t, status="closed", realized_pnl=(price - t.entry_price) * t.quantity * sign, closed_how=how
        )
        self.trades[i] = done
        return done

    def advance(self, idx: int) -> list[TradeInfo]:
        """Move to bar `idx`: fill what was queued at its open, then check stops. Returns the
        trades that closed."""
        self.idx = idx
        bar = self._bars[idx]
        closed: list[TradeInfo] = []
        for intent in self._pending:
            if intent.kind == "exit":
                for i, t in enumerate(self.trades):
                    if t.id == intent.trade_id and t.status == "open":
                        closed.append(self._close(i, bar.open, "exit"))
                continue
            symbol = intent.symbol
            qty = intent.quantity
            if qty is None and intent.percent_of_cash is not None:
                qty = (self._cash * intent.percent_of_cash / 100 / bar.open).to_integral_value(
                    rounding="ROUND_DOWN"
                )
            if intent.kind == "sell":
                remaining = qty
                for i, t in enumerate(self.trades):
                    if (
                        t.status == "open"
                        and t.symbol == symbol
                        and t.direction == "long"
                        and (remaining is None or remaining > 0)
                    ):
                        if remaining is not None and remaining < t.quantity:
                            self._cash += remaining * bar.open
                            self.trades[i] = dataclasses.replace(t, quantity=t.quantity - remaining)
                            remaining = Decimal(0)
                        else:
                            remaining = None if remaining is None else remaining - t.quantity
                            closed.append(self._close(i, bar.open, "sell"))
                continue
            if not qty or qty <= 0 or (intent.kind == "buy" and qty * bar.open > self._cash):
                continue
            direction = "long" if intent.kind == "buy" else "short"
            self._cash += -qty * bar.open if direction == "long" else qty * bar.open
            self.trades.append(
                TradeInfo(
                    len(self.trades) + 1, symbol, direction, qty, bar.open, self.now(), None, None, "open"
                )
            )
        self._pending = []
        for i, t in enumerate(self.trades):
            if t.status != "open":
                continue
            up = t.direction == "long"
            if t.stop_price is not None and (bar.low <= t.stop_price if up else bar.high >= t.stop_price):
                closed.append(self._close(i, t.stop_price, "stop_loss"))
            elif t.target_price is not None and (
                bar.high >= t.target_price if up else bar.low <= t.target_price
            ):
                closed.append(self._close(i, t.target_price, "target"))
        return closed


class _StepLimit(BaseException):
    """Raised inside strategy code that ran too many lines. A BaseException so the strategy's own
    `except Exception` can't swallow it (and a bare `except:` is refused by the validator)."""


class _LineCounter:
    """A trace function that counts executed lines of strategy code only (other frames return
    None, so library calls such as pandas run at full speed)."""

    def __init__(self, limit: int):
        self.left = limit

    def __call__(self, frame, event, arg):
        return self._line if frame.f_code.co_filename == FILENAME else None

    def _line(self, frame, event, arg):
        if event == "line":
            self.left -= 1
            if self.left < 0:
                raise _StepLimit
        return self._line


_SAFE_BUILTINS = (
    "abs min max sum len range enumerate zip sorted reversed round int float str bool list dict tuple set "
    "isinstance any all divmod pow map filter super classmethod staticmethod "
    "Exception ArithmeticError ZeroDivisionError OverflowError ValueError TypeError KeyError IndexError "
    "AttributeError RuntimeError AssertionError NotImplementedError"
).split()


def _restricted_import(name: str, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    if level == 0 and name == "hq":
        return hq
    if level == 0 and name == _HQ_ALIASED_AS[0] and tuple(fromlist or ()) == (_HQ_ALIASED_AS[1],):
        return SimpleNamespace(hq=hq)
    if level == 0 and name in ALLOWED_IMPORTS:
        return importlib.import_module(name)
    raise ImportError(f"`{name}` can't be imported in a strategy.")


def line_of(error: BaseException) -> tuple[int, int]:
    """Line and column of the deepest frame that is the strategy's own code."""
    found = (0, 0)
    for frame in traceback.extract_tb(error.__traceback__):
        if frame.filename == FILENAME and frame.lineno:
            found = (frame.lineno, (frame.colno or 0) + 1 if frame.colno is not None else 0)
    return found


def failure(code: str, stage: str, error: BaseException, text: str) -> DryRunOutcome:
    line, col = line_of(error)
    prefix = f"Line {line}: " if line else ""
    return DryRunOutcome([Problem(line, col, code, f"{prefix}{stage} {text}")])


def build_namespace(log: Callable[[str], None]) -> dict[str, Any]:
    """The globals strategy code is executed in: restricted builtins (`print` goes to `log`), the
    restricted `__import__` and `hq`. Shared by the in-process runner and the sandbox child."""
    safe = {name: getattr(builtins, name) for name in _SAFE_BUILTINS}
    safe["print"] = lambda *args, **kwargs: log(" ".join(str(a) for a in args))
    safe["__build_class__"] = builtins.__build_class__
    safe["__import__"] = _restricted_import
    return {"__builtins__": safe, "__name__": "strategy", "hq": hq}


def find_strategy_class(namespace: dict[str, Any]) -> type[hq.Strategy] | None:
    classes = [
        v
        for v in namespace.values()
        if isinstance(v, type) and v is not hq.Strategy and issubclass(v, hq.Strategy)
    ]
    return classes[0] if classes else None


def play(
    strategy: Any, ctx: StrategyContext, backend: _FakeBackend, fixture: Fixture, stage: list[str]
) -> None:
    """Call the strategy's hooks over `fixture` the way the runner does. `stage[0]` always names
    the hook in progress, so a caller that catches an exception can say where it happened."""
    stage[0] = "on_start"
    strategy.on_start(ctx)
    warmup = max(1, int(strategy.warmup_bars))
    for idx in range(len(fixture.bars)):
        stage[0] = "on_trade_closed"
        for trade in backend.advance(idx):
            strategy.on_trade_closed(ctx, trade)
        if idx + 1 >= warmup:
            stage[0] = "on_bar"
            strategy.on_bar(ctx)


def run_in_process(source: str, fixture: Fixture) -> DryRunOutcome:
    """Run `source` over `fixture` inside this process.

    NOT A SECURITY BOUNDARY. The restricted `__builtins__` only stops accidents. A determined
    author can still hang the process, exhaust memory or escape the namespace; the AST check
    that ran first and the sandboxed subprocess (`sandbox.py`) are what protect the site. The only
    guard here is a line counter so an honest endless loop ends instead of freezing a request.
    """
    backend = _FakeBackend(fixture)
    namespace = build_namespace(backend.log)

    stage = ["loading the file"]
    previous = sys.gettrace()
    sys.settrace(_LineCounter(_MAX_TRACED_LINES))
    try:
        exec(compile(source, FILENAME, "exec"), namespace)  # noqa: S102 - see the docstring
        cls = find_strategy_class(namespace)
        if cls is None:
            return DryRunOutcome(
                [Problem(0, 0, "no_strategy_class", "No class subclassing `hq.Strategy` was found.")]
            )
        stage[0] = "checking the default settings"
        try:
            params = validate_params(cls, {})
        except ParameterError as why:
            return DryRunOutcome([Problem(0, 0, "bad_parameter", f"The default settings are refused: {why}")])
        stage[0] = "creating the strategy"
        strategy = cls()
        play(strategy, StrategyContext(backend, params), backend, fixture, stage)
    except _StepLimit as stop:
        return failure(
            "dry_run_timeout", stage[0], stop, "ran for too long — is there a loop that never ends?"
        )
    except SyntaxError as why:
        return failure("syntax_error", stage[0], why, f"isn't valid Python: {why.msg}.")
    except Exception as why:  # noqa: BLE001 - strategy code is untrusted
        text = f"{type(why).__name__}: {why}"
        return failure(
            "dry_run_error", stage[0], why, f"raised {text if len(text) <= 200 else text[:197] + '...'}"
        )
    finally:
        sys.settrace(previous)
    return DryRunOutcome([], backend.orders, tuple(backend.logs))


def dry_run(source: str, *, runner: Runner | None = None, interval: str = "1d") -> list[Problem]:
    """Play the strategy over a made-up price series; the problems found (none when it finishes
    without raising). `runner` decides where the code runs; the default is in this process."""
    return (runner or run_in_process)(source, make_fixture(interval)).problems


def validate_and_dry_run(source: str, *, runner: Runner | None = None) -> ValidationReport:
    report = validate_source(source)
    if not report.ok:
        return report
    assert report.meta is not None
    problems = dry_run(source, runner=runner, interval=report.meta.interval)
    return ValidationReport(not problems, problems, report.meta)
