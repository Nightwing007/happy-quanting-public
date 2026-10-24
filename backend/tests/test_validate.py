"""The code rules: the AST validator, literal metadata, the dry run, the doc, and the API route.

Each bad snippet is a whole valid strategy with one thing wrong, so the test pins both the stable
`code` and the line it is reported on (found by the marker text, not counted by hand).
"""

import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from app.algos import rules
from app.algos.library import LIBRARY
from app.algos.validate import (
    DryRunOutcome,
    Fixture,
    Problem,
    dry_run,
    validate_and_dry_run,
    validate_source,
)

HEAD = """import hq


class S(hq.Strategy):
    name = "S"
    description = "d"
    markets = ("crypto",)
    interval = "1d"; warmup_bars = 0  # one line so the tests below keep their line numbers
    PARAMETERS = {}

"""


def in_bar(stmt: str) -> str:
    return HEAD + f"    def on_bar(self, ctx):\n        {stmt}\n"


def with_head_line(old: str, new: str) -> str:
    assert old in HEAD
    return in_bar("pass").replace(old, new)


SECOND_CLASS = in_bar("pass") + "\n\nclass T(hq.Strategy):\n    pass\n"

# (id, source, expected code, text of the line it must be reported on; None = whole file, line 0)
BAD = [
    ("import os", "import os\n" + in_bar("pass"), "import_not_allowed", "import os"),
    (
        "from subprocess",
        "from subprocess import run\n" + in_bar("pass"),
        "import_not_allowed",
        "from subprocess",
    ),
    ("import random", "import random\n" + in_bar("pass"), "import_not_allowed", "import random"),
    ("relative import", "from . import x\n" + in_bar("pass"), "import_not_allowed", "from . import"),
    ("star import", "from hq import *\n" + in_bar("pass"), "star_import", "import *"),
    ("open", in_bar('open("f")'), "forbidden_name", 'open("f")'),
    ("eval", in_bar('eval("1")'), "forbidden_name", "eval("),
    ("exec", in_bar('exec("1")'), "forbidden_name", "exec("),
    ("__import__", in_bar('__import__("os")'), "forbidden_name", "__import__"),
    ("dunder walk", in_bar("x = ().__class__.__bases__"), "private_name", "__class__"),
    ("private attribute", in_bar("ctx._backend"), "private_name", "ctx._backend"),
    ("dunder def", HEAD + "    def __init__(self):\n        pass\n", "private_name", "def __init__"),
    ("getattr", in_bar('getattr(ctx, "y")'), "forbidden_name", "getattr"),
    ("globals", in_bar("globals()"), "forbidden_name", "globals()"),
    ("type", in_bar("type(ctx)"), "forbidden_name", "type(ctx)"),
    ("global", in_bar("global x"), "scope_statement", "global x"),
    (
        "async def",
        HEAD + "    async def on_bar(self, ctx):\n        pass\n",
        "async_not_allowed",
        "async def",
    ),
    ("yield", in_bar("yield 1"), "yield_not_allowed", "yield 1"),
    ("with", in_bar("with ctx:\n            pass"), "syntax_not_allowed", "with ctx"),
    ("str.format", in_bar('"{0.__class__}".format(ctx)'), "forbidden_attribute", ".format("),
    (
        "bare except",
        in_bar("try:\n            pass\n        except:\n            pass"),
        "bare_except",
        "except:",
    ),
    (
        "decorator",
        HEAD + "    @property\n    def on_bar(self, ctx):\n        pass\n",
        "decorator_not_allowed",
        "@property",
    ),
    ("module-level call", in_bar("pass") + "\nsetup()\n", "module_level_code", "setup()"),
    ("two Strategy classes", SECOND_CLASS, "multiple_strategy_classes", "class T"),
    ("no Strategy class", "import hq\n\nx = 1\n", "no_strategy_class", None),
    (
        "non-literal PARAMETERS",
        with_head_line("PARAMETERS = {}", "PARAMETERS = make()"),
        "meta_not_literal",
        "PARAMETERS",
    ),
    ("non-literal markets", with_head_line('("crypto",)', "tuple(['a'])"), "meta_not_literal", "markets"),
    ("missing interval", in_bar("pass").replace('interval = "1d"; ', ""), "meta_missing", "class S"),
    ("missing warmup_bars", in_bar("pass").replace("; warmup_bars = 0", ""), "meta_missing", "class S"),
    ("sum as warmup_bars", with_head_line("warmup_bars = 0", "warmup_bars = 5 + 1"), "meta_not_literal", "5"),
    ("float warmup_bars", with_head_line("warmup_bars = 0", "warmup_bars = 2.5"), "meta_not_literal", "2.5"),
    ("too many warmup_bars", with_head_line("warmup_bars = 0", "warmup_bars = 5000"), "meta_invalid", "5000"),
    ("bad interval", with_head_line('"1d"', '"2d"'), "bad_interval", "interval ="),
    (
        "bad parameter",
        with_head_line("{}", '{"x": hq.Param("int", 5, min=10)}'),
        "bad_parameter",
        "PARAMETERS",
    ),
    ("oversize", "#" * (rules.MAX_SOURCE_BYTES + 1), "too_large", None),
    ("syntax error", "def f(:\n", "syntax_error", "def f(:"),
]


@pytest.mark.parametrize("source,code,marker", [b[1:] for b in BAD], ids=[b[0] for b in BAD])
def test_bad_snippet_is_refused_with_its_code_and_line(source, code, marker):
    report = validate_source(source)
    assert not report.ok
    expected_line = (
        0 if marker is None else 1 + next(i for i, text in enumerate(source.splitlines()) if marker in text)
    )
    assert (expected_line, code) in {(p.line, p.code) for p in report.problems}, report.problems
    for p in report.problems:
        assert p.message  # a sentence for every one
        assert p.message.startswith(f"Line {p.line}: ") or p.line == 0


def test_the_message_names_the_line_and_the_reason():
    report = validate_source(in_bar('open("f")'))
    assert (
        report.problems[0].message == "Line 12: `open` isn't allowed — strategies can't read or write files."
    )


def test_every_problem_is_reported_not_just_the_first():
    source = "import os\nimport random\n" + in_bar("eval('1')\n        globals()")
    codes = [(p.line, p.code) for p in validate_source(source).problems]
    assert codes == [
        (1, "import_not_allowed"),
        (2, "import_not_allowed"),
        (14, "forbidden_name"),
        (15, "forbidden_name"),
    ]


def test_lambda_while_math_and_a_lone_underscore_are_fine():
    stmt = (
        "f = lambda x: x + 1\n        for _ in range(2):\n            f(1)\n"
        "        while False:\n            pass"
    )
    source = "import math\nfrom decimal import Decimal\nLIMIT = 5\n" + in_bar(stmt)
    assert validate_and_dry_run(source).ok


def test_exception_in_on_bar_is_caught_by_the_dry_run_with_its_line():
    report = validate_and_dry_run(in_bar("1 / 0"))
    assert not report.ok
    (problem,) = report.problems
    assert (problem.line, problem.code) == (12, "dry_run_error")
    assert problem.message.startswith("Line 12: on_bar raised ZeroDivisionError")


def test_a_loop_that_never_ends_is_stopped_by_the_dry_run():
    report = validate_and_dry_run(in_bar("while True:\n            pass"))
    (problem,) = report.problems
    assert problem.code == "dry_run_timeout"
    assert problem.line in (12, 13)


def test_swallowing_the_stop_signal_does_not_hang_the_dry_run():
    body = (
        "while True:\n            try:\n                pass\n"
        "            except Exception:\n                pass"
    )
    assert validate_and_dry_run(in_bar(body)).problems[0].code == "dry_run_timeout"


def test_print_goes_to_the_log_and_orders_are_counted():
    calls = []

    def runner(source: str, fixture: Fixture) -> DryRunOutcome:
        calls.append((source, fixture))
        return DryRunOutcome([Problem(3, 1, "x", "Line 3: stub")])

    source = in_bar("pass")
    assert dry_run(source, runner=runner) == [Problem(3, 1, "x", "Line 3: stub")]
    assert calls[0][0] == source and len(calls[0][1].bars) > 100  # the seam 25b plugs into

    from app.algos.validate import make_fixture, run_in_process

    outcome = run_in_process(in_bar("print('hi'); ctx.buy('DRY', 1)"), make_fixture())
    assert outcome.problems == [] and outcome.logs[0] == "hi" and outcome.orders > 0


def test_the_restricted_namespace_has_no_open():
    from app.algos.validate import make_fixture, run_in_process

    # Reaching `open` by a spelling the AST check can't see still fails at run time.
    source = HEAD + "    def on_bar(self, ctx):\n        ctx.log(open)\n"
    problems = run_in_process(source, make_fixture()).problems
    assert problems[0].code == "dry_run_error" and "NameError" in problems[0].message


def test_meta_is_read_from_literals_without_running_anything():
    source = pathlib.Path(LIBRARY["sma_crossover"].__module__.replace(".", "/") + ".py")
    text = (pathlib.Path(__file__).parents[1] / source).read_text(encoding="utf-8")
    meta = validate_source(text).meta
    assert meta is not None
    assert (meta.name, meta.interval, meta.markets) == (
        "SMA crossover",
        "1d",
        ("india", "international", "crypto"),
    )
    assert list(meta.parameters) == ["fast_period", "slow_period", "percent_of_cash"]
    assert meta.parameters["fast_period"].kind == "int"


@pytest.mark.parametrize("key", list(LIBRARY))
def test_every_library_algorithm_passes_validate_and_dry_run(key):
    path = pathlib.Path(__file__).parents[1] / (LIBRARY[key].__module__.replace(".", "/") + ".py")
    report = validate_and_dry_run(path.read_text(encoding="utf-8"))
    assert report.ok, report.problems
    assert report.meta is not None and report.meta.name == LIBRARY[key].name


# --- the page and the constants agree ------------------------------------------------------

DOC = pathlib.Path(__file__).parents[2] / "docs" / "algo-rules.md"


def test_the_rules_page_matches_the_constants():
    text = DOC.read_text(encoding="utf-8")
    listed = dict(re.findall(r"^([A-Z_]+) = (\d+)$", text, re.MULTILINE))
    assert {k: int(v) for k, v in listed.items()} == rules.DOCUMENTED_LIMITS
    for name in [*rules.FORBIDDEN_NAMES, *rules.INTERVALS, *rules.ALLOWED_IMPORTS, *rules.ALLOWED_DECORATORS]:
        assert f"`{name}`" in text, name
    assert "**50 KB**" in text and rules.MAX_SOURCE_BYTES == 50 * 1024


# --- the route -----------------------------------------------------------------------------


def test_validate_route_returns_the_report(client: TestClient):
    good = client.post("/api/algos/validate", json={"source": in_bar("pass")}).json()
    assert good["ok"] is True and good["problems"] == []
    assert good["meta"]["name"] == "S" and good["meta"]["interval"] == "1d"

    bad = client.post("/api/algos/validate", json={"source": in_bar("eval('1')")}).json()
    assert bad["ok"] is False
    assert bad["problems"] == [
        {"line": 12, "col": 9, "code": "forbidden_name", "message": bad["problems"][0]["message"]}
    ]


def test_validate_route_needs_a_login(anon_client: TestClient):
    assert anon_client.post("/api/algos/validate", json={"source": ""}).status_code == 401


def test_rules_route_is_public_and_serves_the_one_doc(anon_client: TestClient):
    body = anon_client.get("/api/algos/rules").json()
    assert body["markdown"] == DOC.read_text(encoding="utf-8")
    assert body["limits"] == rules.DOCUMENTED_LIMITS
