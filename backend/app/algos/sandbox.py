"""Run uploaded strategy code in a separate process with limits (step 25b).

The parent owns the engine. The child owns only the strategy: it executes the source in the
restricted namespace of `validate.py`, and every `ctx` call becomes a message to the parent, which
answers it on the real `Backend`. So the code that decides trades never holds an account, a
session or a provider, and whatever it does to its own memory or CPU can be cut off by killing it.

One child per run (`SandboxedStrategy`), started on first use with `multiprocessing` "spawn" (a
fresh interpreter, nothing inherited) and talking over one `Pipe`:

    parent -> child  ("call", hook, args, params, symbols)   run a hook
                     ("reply" ...) answers to the child's backend requests, ("close",)
    child  -> parent ("backend", method, args)               a `ctx` call
                     ("done", warmup_bars, result) | ("error", line, text) | ("limit", code)

Limits (`rules.py`), all enforced by the parent:
- per hook: wall time the child spends working on one hook call (time the parent spends answering
  its requests is not counted, so a slow engine never blames the strategy);
- per run: the same time summed over all hooks;
- memory: on Windows the parent reads the child's working set every ~50 ms through
  `psapi.GetProcessMemoryInfo`; on POSIX the child sets `RLIMIT_AS` before it starts the strategy;
- log size: lines are cut at `MAX_LOG_CHARS` and dropped past `MAX_LOG_LINES`; one message may not
  exceed `_MAX_MESSAGE_BYTES`.
A breach kills the child (`terminate`, then `kill`) and raises `SandboxError(code, message)`; the
strategy is then finished for this run and later hooks do nothing.

Messages are pickles, but never trusted ones: both sides unpickle through an allow-list of the few
plain data classes that cross the pipe, so a hostile child cannot make the parent build anything else.

WHAT THIS PROTECTS AGAINST: honest bugs and mild abuse from code that already passed the AST
allow-list: endless loops, memory blow-ups, runaway output, a crash of the interpreter, a strategy
reaching the engine, files or the network (it has no handle to any of them). WHAT IT DOES NOT:
a determined escape from CPython itself (a bug in the interpreter or a C extension, the child's
operating-system privileges are the parent's own, no seccomp, no jail, no network block). That is
fine on your own machine and not on a public site, which the README already records.
"""

import dataclasses
import enum
import io
import multiprocessing
import pickle
import sys
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from app.algos.api import (
    MAX_BARS,
    MAX_LOG_CHARS,
    MAX_LOG_LINES,
    OrderIntent,
    ParameterError,
    StrategyContext,
    TradeInfo,
    validate_params,
)
from app.algos.rules import CPU_SECONDS_PER_HOOK, MEMORY_MB, WALL_SECONDS_PER_RUN
from app.algos.validate import (
    FILENAME,
    DryRunOutcome,
    Fixture,
    Problem,
    StrategyMeta,
    _FakeBackend,
    build_namespace,
    find_strategy_class,
    line_of,
    play,
    validate_source,
)

_START_SECONDS = 60.0  # spawning imports pandas; not part of any limit
_POLL_SECONDS = 0.05
_MAX_MESSAGE_BYTES = 16 * 1024 * 1024
_HOOKS = ("on_start", "on_bar", "on_trade_closed")
_BACKEND_METHODS = "now cash available_cash bars price position open_trades queue set_protection log".split()
_NO_BACKEND = SimpleNamespace(symbols=())  # `check_params` has no `ctx`, so nothing is asked
_NEEDS_SYMBOL = ("bars", "price", "position")


class SandboxError(Exception):
    """A limit was breached or the child failed. `code` is stable; `message` is a sentence for the author."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class UserCodeError(Exception):
    """The strategy raised inside a hook. The child is fine and keeps running."""

    def __init__(self, line: int, text: str):
        super().__init__(f"Line {line}: {text}" if line else text)
        self.line = line
        self.text = text


class InvalidStrategy(Exception):
    """`load_strategy` refused the source; `problems` are the validator's."""

    def __init__(self, problems: list[Problem]):
        super().__init__(" ".join(p.message for p in problems) or "The strategy was refused.")
        self.problems = problems


@dataclass(frozen=True)
class Limits:
    hook_seconds: float = CPU_SECONDS_PER_HOOK
    run_seconds: float = WALL_SECONDS_PER_RUN
    memory_mb: int = MEMORY_MB


# --- messages ---------------------------------------------------------------------------

# The only classes a message may contain besides builtins' plain types.
_ALLOWED_GLOBALS = {
    ("decimal", "Decimal"),
    ("datetime", "datetime"),
    ("datetime", "date"),
    ("datetime", "timedelta"),
    ("datetime", "timezone"),
    ("zoneinfo", "ZoneInfo"),
    ("zoneinfo", "ZoneInfo._unpickle"),
    ("app.algos.api", "Bar"),
    ("app.algos.api", "Position"),
    ("app.algos.api", "TradeInfo"),
    ("app.algos.api", "OrderIntent"),
    ("app.algos.api", "OrderResult"),
}


class _SafeUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if (module, name) not in _ALLOWED_GLOBALS:
            raise pickle.UnpicklingError(f"{module}.{name} may not cross the sandbox pipe.")
        return super().find_class(module, name)


def _plain(value: Any) -> Any:
    """Enums (the engine's `TradeStatus`) become their values so only plain data is pickled."""
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, tuple):
        return tuple(_plain(v) for v in value)
    if isinstance(value, TradeInfo):
        return dataclasses.replace(
            value, **{f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
        )
    return value


def _send(conn, message: tuple) -> None:
    conn.send_bytes(pickle.dumps(_plain(message), protocol=4))


def _recv(conn, maxlength: int | None = None) -> tuple:
    return _SafeUnpickler(io.BytesIO(conn.recv_bytes(maxlength))).load()


# --- the child --------------------------------------------------------------------------


class _ProxyBackend:
    """The `Backend` the strategy's `ctx` sees in the child: every call is a request to the parent."""

    def __init__(self, conn):
        self._conn = conn
        self.symbols: tuple[str, ...] = ()

    def _ask(self, method: str, *args):
        _send(self._conn, ("backend", method, args))
        reply = _recv(self._conn)
        if reply[0] == "ok":
            return reply[1]
        raise RuntimeError(reply[1])

    def now(self):
        return self._ask("now")

    def cash(self):
        return self._ask("cash")

    def available_cash(self):
        return self._ask("available_cash")

    def bars(self, symbol, n):
        return self._ask("bars", symbol, n)

    def price(self, symbol):
        return self._ask("price", symbol)

    def position(self, symbol):
        return self._ask("position", symbol)

    def open_trades(self, symbol):
        return self._ask("open_trades", symbol)

    def queue(self, intent):
        return self._ask("queue", intent)

    def set_protection(self, trade_id, stop, target):
        return self._ask("set_protection", trade_id, stop, target)

    def log(self, message):
        return self._ask("log", message)


def _limit_memory(megabytes: int) -> None:
    """POSIX: cap the address space just above what the interpreter already holds. (Windows has no
    equivalent here; its parent polls the working set instead.)"""
    try:
        import resource  # noqa: PLC0415 - not available on Windows

        with open("/proc/self/statm") as statm:
            used = int(statm.read().split()[0]) * resource.getpagesize()
    except ImportError, OSError, ValueError:
        return
    cap = used + megabytes * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (cap, cap))


def _error_text(why: BaseException) -> str:
    text = f"{type(why).__name__}: {why}"
    return text if len(text) <= 200 else text[:197] + "..."


def _child_main(conn, source: str, memory_mb: int) -> None:
    """Entry point of the child process."""
    proxy = _ProxyBackend(conn)
    try:
        namespace = build_namespace(proxy.log)
        exec(compile(source, FILENAME, "exec"), namespace)  # noqa: S102 - the sandbox's whole job
        cls = find_strategy_class(namespace)
        if cls is None:
            _send(conn, ("load_error", 0, "No class subclassing `hq.Strategy` was found."))
            return
        strategy = cls()
        _limit_memory(memory_mb)
        _send(conn, ("ready", int(strategy.warmup_bars)))
    except Exception as why:  # noqa: BLE001 - untrusted code
        _send(conn, ("load_error", line_of(why)[0], _error_text(why)))
        return

    ctx = None
    try:
        while True:
            message = _recv(conn)
            if message[0] == "close":
                return
            _, hook, args, params, symbols = message
            proxy.symbols = tuple(symbols)
            try:
                if hook == "check_params":
                    result = list(cls.check_params(*args))
                elif hook in _HOOKS:
                    if ctx is None:
                        ctx = StrategyContext(proxy, params)
                    result = getattr(strategy, hook)(ctx, *args)
                else:
                    raise ValueError(f"unknown hook {hook}")
                _send(conn, ("done", int(strategy.warmup_bars), result))
            except MemoryError:
                _send(conn, ("limit", "memory_limit"))
            except Exception as why:  # noqa: BLE001 - reported, the child keeps running
                _send(conn, ("error", line_of(why)[0], _error_text(why)))
    except EOFError, OSError:
        return  # the parent went away


# --- the parent -------------------------------------------------------------------------


class _WindowsMemory:
    """Working-set size of another process through `psapi.GetProcessMemoryInfo`."""

    def __init__(self, pid: int):
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        self._counters = Counters
        self._ctypes = ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        self._psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        self._close_handle = kernel32.CloseHandle
        self._handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION

    def bytes(self) -> int | None:
        if not self._handle:
            return None
        counters = self._counters()
        counters.cb = self._ctypes.sizeof(counters)
        if not self._psapi.GetProcessMemoryInfo(self._handle, self._ctypes.byref(counters), counters.cb):
            return None
        return counters.WorkingSetSize

    def close(self) -> None:
        if self._handle:
            self._close_handle(self._handle)
            self._handle = None


def _kill(proc) -> None:
    """terminate, then kill, and wait: no process outlives a run."""
    if proc is None:
        return
    try:
        if proc.is_alive():
            proc.terminate()
            proc.join(2)
        if proc.is_alive():
            proc.kill()
            proc.join(2)
    except OSError, ValueError, AssertionError:
        pass


def _seconds(value: float) -> str:
    return f"{value:g}"


class SandboxedStrategy:
    """Stands in for a `Strategy` instance in `StrategyRun`. Its attributes come from the validator's
    literal reading of the source (the code is never executed here); its hooks run in the child."""

    def __init__(self, source: str, meta: StrategyMeta, limits: Limits | None = None):
        self._source = source
        self.limits = limits or Limits()
        self.name = meta.name
        self.description = meta.description
        self.markets = meta.markets
        self.interval = meta.interval
        self.PARAMETERS = meta.parameters
        # The class's literal is known before anything runs, so the backtester and the sim can
        # preload it; the child's own value (set in on_start) replaces it once the strategy runs.
        self.warmup_bars = meta.warmup_bars
        self.failure: SandboxError | None = None  # set when a limit stopped the run
        self.process = None  # the child, kept after close so callers can check it is gone
        self._conn = None
        self._memory: _WindowsMemory | None = None
        self._run_spent = 0.0
        self._log_lines = 0
        self._closed = False

    # --- the hooks -------------------------------------------------------------------
    def on_start(self, ctx: StrategyContext) -> None:
        self._hook("on_start", (), ctx)

    def on_bar(self, ctx: StrategyContext) -> None:
        self._hook("on_bar", (), ctx)

    def on_trade_closed(self, ctx: StrategyContext, trade: TradeInfo) -> None:
        self._hook("on_trade_closed", (trade,), ctx)

    def check_params(self, params: dict) -> list[str]:
        """The class's cross-setting rules, which are the author's code, so they run in the child."""
        if self.failure is not None:
            raise self.failure
        return self._converse("check_params", (params,), _NO_BACKEND, params, ())

    def _hook(self, hook: str, args: tuple, ctx: StrategyContext) -> None:
        if self.failure is not None or self._closed:
            return  # stopped once; don't record the same error for every later bar
        self._converse(hook, args, ctx._backend, ctx.params, ctx.symbols)  # noqa: SLF001

    # --- the conversation ---------------------------------------------------------------
    def _converse(self, hook: str, args: tuple, backend: Any, params: dict, symbols: tuple) -> Any:
        try:
            self._ensure_started()
            try:
                _send(self._conn, ("call", hook, args, params, tuple(symbols)))
            except OSError:
                raise self._died(hook) from None
            return self._serve(hook, backend)
        except SandboxError as why:
            self.failure = why
            self.close()
            raise

    def _serve(self, hook: str, backend: Any) -> Any:
        hook_spent = 0.0
        while True:
            started = time.monotonic()
            message = self._receive(
                hook, self.limits.hook_seconds - hook_spent, self.limits.run_seconds - self._run_spent
            )
            took = time.monotonic() - started
            hook_spent += took
            self._run_spent += took
            kind = message[0]
            if kind == "backend":
                _send(self._conn, self._answer(backend, message))
            elif kind == "done":
                self.warmup_bars = max(0, message[1])
                return message[2]
            elif kind == "error":
                raise UserCodeError(message[1], message[2])
            elif kind == "limit":
                raise self._memory_breach(hook)
            else:
                raise SandboxError(
                    "sandbox_failed", f"The strategy's process sent something unexpected in {hook}."
                )

    def _receive(self, hook: str, hook_left: float, run_left: float, *, startup: bool = False) -> tuple:
        """Wait for the child's next message, polling so the clocks and the memory are checked."""
        started = time.monotonic()
        next_memory = started
        while True:
            elapsed = time.monotonic() - started
            if startup:
                left = _START_SECONDS - elapsed
                if left <= 0:
                    raise SandboxError("sandbox_failed", "The sandbox did not start in time.")
            elif hook_left - elapsed <= 0:
                raise SandboxError(
                    "hook_timeout",
                    f"Your strategy took longer than {_seconds(self.limits.hook_seconds)} s in {hook} "
                    "and was stopped.",
                )
            elif run_left - elapsed <= 0:
                raise SandboxError(
                    "run_timeout",
                    f"Your strategy used more than {_seconds(self.limits.run_seconds)} s of running time "
                    "in this run and was stopped.",
                )
            else:
                left = min(hook_left, run_left) - elapsed
            try:
                if self._conn.poll(min(_POLL_SECONDS, left)):
                    return _recv(self._conn, _MAX_MESSAGE_BYTES)
            except EOFError, ConnectionError:
                raise self._died(hook) from None
            except (OSError, pickle.UnpicklingError) as why:
                raise SandboxError(
                    "sandbox_failed", f"The strategy's process sent a message that was refused ({why})."
                ) from None
            if not self.process.is_alive() and not self._conn.poll(0):
                raise self._died(hook)
            if time.monotonic() >= next_memory:
                next_memory = time.monotonic() + _POLL_SECONDS
                if not startup and self._over_memory():
                    raise self._memory_breach(hook)

    def _answer(self, backend: Any, message: tuple) -> tuple:
        """Service one `ctx` call on the real backend. Arguments come from a process we don't trust,
        so they are checked the way the facade would have."""
        _, method, args = message
        if method not in _BACKEND_METHODS or not isinstance(args, tuple):
            raise SandboxError(
                "sandbox_failed", "The strategy's process asked for something it may not have."
            )
        try:
            if method in _NEEDS_SYMBOL or (method == "open_trades" and args[0] is not None):
                if args[0] not in backend.symbols:
                    return ("err", f"{args[0]} is not one of this run's symbols.")
            if method == "bars":
                args = (args[0], max(0, min(int(args[1]), MAX_BARS)))
            elif method == "queue":
                if not isinstance(args[0], OrderIntent):
                    return ("err", "queue needs an order.")
            elif method == "log":
                if self._log_lines >= MAX_LOG_LINES:
                    return ("ok", None)
                self._log_lines += 1
                args = (str(args[0])[:MAX_LOG_CHARS],)
            return ("ok", getattr(backend, method)(*args))
        except Exception as why:  # noqa: BLE001 - what the engine said becomes the strategy's error
            return ("err", str(why) or type(why).__name__)

    # --- the child's life -----------------------------------------------------------------
    def _ensure_started(self) -> None:
        if self._conn is not None:
            return
        if self._closed:
            raise SandboxError("sandbox_failed", "This sandbox was closed.")
        context = multiprocessing.get_context("spawn")
        parent_end, child_end = context.Pipe(duplex=True)
        proc = context.Process(
            target=_child_main, args=(child_end, self._source, self.limits.memory_mb), daemon=True
        )
        self.process = proc
        self._conn = parent_end
        try:
            proc.start()
        except Exception as why:  # noqa: BLE001
            raise SandboxError("sandbox_failed", f"The sandbox could not start ({why}).") from None
        finally:
            child_end.close()
        if sys.platform == "win32":
            self._memory = _WindowsMemory(proc.pid)
        message = self._receive("starting", 0, 0, startup=True)
        if message[0] == "load_error":
            line = f"Line {message[1]}: " if message[1] else ""
            raise SandboxError("load_error", f"{line}the file could not be loaded ({message[2]}).")
        if message[0] != "ready":
            raise SandboxError("sandbox_failed", "The sandbox did not start properly.")
        self.warmup_bars = max(0, message[1])

    def _over_memory(self) -> bool:
        if self._memory is None:
            return False  # POSIX: the child's own RLIMIT_AS answers with a MemoryError
        used = self._memory.bytes()
        return used is not None and used > self.limits.memory_mb * 1024 * 1024

    def _memory_breach(self, hook: str) -> SandboxError:
        return SandboxError(
            "memory_limit",
            f"Your strategy used more than {self.limits.memory_mb} MB of memory in {hook} and was stopped.",
        )

    def _died(self, hook: str) -> SandboxError:
        self.process.join(1)
        return SandboxError(
            "sandbox_failed",
            f"The strategy's process ended unexpectedly in {hook} (exit code {self.process.exitcode}).",
        )

    def close(self) -> None:
        """Stop the child and wait for it. Safe to call twice."""
        self._closed = True
        proc, conn, memory = self.process, self._conn, self._memory
        self._conn = self._memory = None
        if proc is not None and conn is not None and self.failure is None:
            try:
                _send(conn, ("close",))
                proc.join(1)
            except OSError, ValueError:
                pass
        _kill(proc)
        if conn is not None:
            conn.close()
        if memory is not None:
            memory.close()

    def __enter__(self) -> SandboxedStrategy:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001, S110 - interpreter shutdown
            pass


def load_strategy(source: str, limits: Limits | None = None) -> SandboxedStrategy:
    """Validate `source`, then return a strategy that runs it in a child process (started on first
    use). Raises `InvalidStrategy` with the validator's problems when the code breaks the rules."""
    report = validate_source(source)
    if not report.ok or report.meta is None:
        raise InvalidStrategy(report.problems)
    return SandboxedStrategy(source, report.meta, limits)


def run_in_subprocess(source: str, fixture: Fixture, limits: Limits | None = None) -> DryRunOutcome:
    """`validate.Runner` over the sandbox: the dry run's fake backend stays here, the strategy runs
    in a child. Same outcome as `run_in_process`, plus the limits."""
    try:
        strategy = load_strategy(source, limits)
    except InvalidStrategy as refused:
        return DryRunOutcome(refused.problems)
    backend = _FakeBackend(fixture)
    stage = ["checking the default settings"]
    with strategy:
        try:
            params = validate_params(strategy, {})  # type: ignore[arg-type]
            stage[0] = "creating the strategy"
            play(strategy, StrategyContext(backend, params), backend, fixture, stage)
        except ParameterError as why:
            return DryRunOutcome([Problem(0, 0, "bad_parameter", f"The default settings are refused: {why}")])
        except SandboxError as why:
            return DryRunOutcome([Problem(0, 0, why.code, why.message)])
        except UserCodeError as why:
            prefix = f"Line {why.line}: " if why.line else ""
            return DryRunOutcome(
                [Problem(why.line, 0, "dry_run_error", f"{prefix}{stage[0]} raised {why.text}")]
            )
    return DryRunOutcome([], backend.orders, tuple(backend.logs))


__all__ = [
    "InvalidStrategy",
    "Limits",
    "SandboxError",
    "SandboxedStrategy",
    "UserCodeError",
    "load_strategy",
    "run_in_subprocess",
]
