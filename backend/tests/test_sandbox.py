"""The sandbox: strategy code in a child process, `ctx` calls answered by this process.

Each child costs about a second to start (a fresh interpreter importing pandas), so tests share one
where they can and the limits are set low where a test needs a breach.
"""

import multiprocessing
import pathlib

import pytest

from app.algos.api import StrategyContext, validate_params
from app.algos.library import LIBRARY
from app.algos.sandbox import (
    InvalidStrategy,
    Limits,
    SandboxError,
    UserCodeError,
    load_strategy,
    run_in_subprocess,
)
from app.algos.validate import _FakeBackend, make_fixture, play

HEAD = """import hq


class S(hq.Strategy):
    name = "S"
    description = "d"
    markets = ("crypto",)
    interval = "1d"; warmup_bars = 0  # one line so the tests below keep their line numbers
    PARAMETERS = {}

"""

FAST = Limits(hook_seconds=0.7, run_seconds=30, memory_mb=256)


def source_of(key: str) -> str:
    path = pathlib.Path(__file__).parents[1] / (LIBRARY[key].__module__.replace(".", "/") + ".py")
    return path.read_text(encoding="utf-8")


def play_all(strategy) -> _FakeBackend:
    fixture = make_fixture("1d")
    backend = _FakeBackend(fixture)
    params = validate_params(strategy, {})
    play(strategy, StrategyContext(backend, params), backend, fixture, ["start"])
    return backend


@pytest.mark.parametrize("key", ["sma_crossover", "rsi_reversion"])
def test_sandbox_gives_the_same_trades_as_in_process(key):
    expected = play_all(LIBRARY[key]())
    with load_strategy(source_of(key)) as strategy:
        got = play_all(strategy)
        assert strategy.process.is_alive()
    assert expected.trades, "the fixture should make this algorithm trade"
    assert got.trades == expected.trades
    assert (got.orders, got.logs) == (expected.orders, expected.logs)
    assert strategy.process.is_alive() is False


def test_endless_loop_is_stopped_and_the_child_is_gone():
    source = HEAD + "    def on_bar(self, ctx):\n        n = 0\n        while True:\n            n = n + 1\n"
    strategy = load_strategy(source, FAST)
    backend = _FakeBackend(make_fixture("1d"))
    ctx = StrategyContext(backend, {})
    strategy.on_start(ctx)
    with pytest.raises(SandboxError) as stopped:
        strategy.on_bar(ctx)
    assert stopped.value.code == "hook_timeout"
    assert stopped.value.message == "Your strategy took longer than 0.7 s in on_bar and was stopped."
    assert strategy.process.is_alive() is False
    strategy.on_bar(ctx)  # finished for this run: later hooks do nothing instead of repeating the error
    assert multiprocessing.active_children() == []


def test_memory_blow_up_is_stopped():
    source = (
        HEAD
        + "    def on_bar(self, ctx):\n        hoard = []\n        while True:\n"
        + "            hoard.append([0] * 10**6)\n"
    )
    with load_strategy(source, Limits(hook_seconds=20, run_seconds=30, memory_mb=300)) as strategy:
        ctx = StrategyContext(_FakeBackend(make_fixture("1d")), {})
        with pytest.raises(SandboxError) as stopped:
            strategy.on_bar(ctx)
        assert stopped.value.code == "memory_limit"
        assert "300 MB" in stopped.value.message
        assert strategy.process.is_alive() is False


def test_an_exception_has_its_line_and_the_run_continues_and_backend_calls_work():
    source = (
        HEAD
        + "    def on_bar(self, ctx):\n"
        + '        if len(ctx.bars("DRY", 1000)) == 150:\n'
        + '            raise ValueError("boom")  # marker\n'
        + '        if ctx.position("DRY").quantity == 0:\n'
        + '            ctx.buy("DRY", quantity=5)\n'
        + "        else:\n"
        + '            ctx.log(f"holding {ctx.position(\'DRY\').quantity}")\n'
    )
    marker = source.splitlines().index('            raise ValueError("boom")  # marker') + 1
    fixture = make_fixture("1d")
    backend = _FakeBackend(fixture)
    ctx = StrategyContext(backend, {})
    errors: list[UserCodeError] = []
    with load_strategy(source, FAST) as strategy:
        strategy.on_start(ctx)
        for idx in range(len(fixture.bars)):
            backend.advance(idx)
            try:
                strategy.on_bar(ctx)
            except UserCodeError as why:
                errors.append(why)
        assert strategy.process.is_alive()
    assert [(e.line, e.text) for e in errors] == [(marker, "ValueError: boom")]
    assert backend.position("DRY").quantity == 5
    assert "holding 5" in backend.logs


def test_dry_run_in_the_subprocess_reports_the_line():
    source = HEAD + "    def on_bar(self, ctx):\n        return 1 / 0\n"
    problems = run_in_subprocess(source, make_fixture("1d")).problems
    assert [(p.line, p.code) for p in problems] == [(12, "dry_run_error")]
    assert "ZeroDivisionError" in problems[0].message


def test_dry_run_in_the_subprocess_passes_a_library_algorithm():
    outcome = run_in_subprocess(source_of("sma_crossover"), make_fixture("1d"))
    assert outcome.problems == []
    assert outcome.orders > 0


def test_load_strategy_refuses_invalid_source():
    with pytest.raises(InvalidStrategy) as refused:
        load_strategy("import os\n" + HEAD + "    def on_bar(self, ctx):\n        pass\n")
    assert [p.code for p in refused.value.problems] == ["import_not_allowed"]


def test_no_child_processes_remain():
    assert multiprocessing.active_children() == []
