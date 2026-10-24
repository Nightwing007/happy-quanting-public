"""Strategies inside the virtual sim: which one a session runs, and its run held in memory.

A session may carry a strategy of four kinds: a `library` algorithm, a saved one (`mine`), uploaded
`source`, or a published marketplace `listing` (a way to try it before subscribing; its code,
settings and logs never reach the tester). Like `marketplace/live.py`, one `StrategyRun` per
session lives in a module dict, is rebound to each request's fresh context and is closed when the
session is reset, deleted or finished, so a sandbox child never outlives its session.

The sim steps the run in the backtester's order (move the cursor, then `StrategyRun.step()`, which
flushes queued orders, calls `on_bar` and runs the tick), so both give the same trades.

Manual trading alongside a strategy is allowed: it is the same account, so a person can take over
or hedge a run, and the strategy sees those trades like any others.
"""

import threading
from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.algos.api import validate_params
from app.algos.library import LIBRARY
from app.algos.runner import LogLine, StrategyRun, run_strategy_on
from app.algos.sandbox import SandboxedStrategy, load_strategy
from app.algos.validate import validate_source
from app.market_data.base import Bar, MarketDataProvider
from app.marketplace import listings
from app.models import AlgoListing, ListingStatus, SimSession, User, UserAlgo
from app.schemas import SimStrategyIn, SimStrategyOut
from app.sim.runner import SimError, SimNotFound
from app.trading.tick import run_tick

if TYPE_CHECKING:
    from app.sim.runner import SimRun

KINDS = ("library", "mine", "source", "listing")
LOG_LINES = 100


@dataclass(frozen=True)
class Resolved:
    """A validated request: what the session stores, and the bar size the strategy is built for."""

    name: str
    interval: str
    fields: dict  # SimSession columns to set


def _library(key: str | None):
    if key is None or key not in LIBRARY:
        raise SimError(f"There is no algorithm '{key}'. Choose one of: {', '.join(LIBRARY)}.")
    return LIBRARY[key]


def resolve(db: Session, spec: SimStrategyIn, owner_user_id: int | None) -> Resolved:
    """Check a strategy request and pin what it runs. Raises `SimError`s (and the marketplace's
    `invalid_source` with line-numbered problems) with sentences a person can act on."""
    if spec.kind == "library":
        cls = _library(spec.key)
        validate_params(cls, spec.params or {})
        fields = dict(strategy_kind="library", strategy_key=spec.key, params=spec.params or {})
        return Resolved(cls.name, cls.interval, fields)
    if spec.kind == "mine":
        algo = db.get(UserAlgo, spec.algo_id) if spec.algo_id is not None else None
        if algo is None or algo.owner_user_id != owner_user_id:  # someone else's is "not found"
            raise SimNotFound(f"There is no saved algorithm {spec.algo_id}.")
        if algo.source is not None:
            # Editor code is pinned on the session like `source`, so a later edit or delete of the
            # saved algorithm can't change a running sim.
            meta = listings.check_source(algo.source)
            fields = dict(
                strategy_kind="mine", user_algo_id=algo.id, source=algo.source, params=dict(algo.params)
            )
            return Resolved(algo.name, meta.interval, fields)
        cls = _library(algo.strategy_key)
        fields = dict(
            strategy_kind="mine", strategy_key=algo.strategy_key, user_algo_id=algo.id,
            params=dict(algo.params),
        )
        return Resolved(algo.name, cls.interval, fields)
    if spec.kind == "source":
        if not spec.source:
            raise SimError("Send the algorithm's code in `source`.")
        meta = listings.check_source(spec.source)  # raises with every problem, each worded with its line
        sandbox = load_strategy(spec.source)  # starts no process until a hook runs
        try:
            validate_params(sandbox, spec.params or {})  # type: ignore[arg-type]
        finally:
            sandbox.close()
        fields = dict(strategy_kind="source", source=spec.source, params=spec.params or {})
        return Resolved(meta.name, meta.interval, fields)
    listing = db.get(AlgoListing, spec.listing_id) if spec.listing_id is not None else None
    if listing is None or listing.status != ListingStatus.PUBLISHED:  # a draft or retired one is hidden
        raise SimNotFound(f"There is no listing {spec.listing_id} to try.")
    # The current published version is pinned, as a subscriber's would be.
    _code, interval = listings.code_for(db, listing.id, listing.version)
    return Resolved(
        listing.name, interval,
        dict(strategy_kind="listing", listing_id=listing.id, listing_version=listing.version),
    )  # fmt: skip


def mismatch_message(name: str, strategy_interval: str, interval: str) -> str:
    return (
        f"{name} is built for {strategy_interval} bars, so the simulation must use "
        f"{strategy_interval} bars, not {interval}."
    )


def warmup_bars(db: Session, session: SimSession) -> int:
    """The bars the strategy asks for before it can act, as the backtester reads them (uploaded
    code declares a literal `warmup_bars` that the validator reads without running it)."""
    kind = session.strategy_kind
    if session.source is not None and kind in ("source", "mine"):
        return _source_warmup(session.source)
    if kind in ("library", "mine"):
        return _library(session.strategy_key).warmup_bars
    if kind == "listing":
        code, _ = listings.code_for(db, session.listing_id, session.listing_version)
        return _source_warmup(code) if isinstance(code, str) else _library(code[0]).warmup_bars
    return 0


def _source_warmup(source: str) -> int:
    report = validate_source(source)
    return report.meta.warmup_bars if report.meta is not None else 0


def load_warmup(db: Session, provider: MarketDataProvider, session: SimSession) -> dict[str, list[Bar]]:
    """Closed bars from before the start date, which the strategy sees as history but cannot trade
    on (same loader as the backtester). Empty when the session has no strategy."""
    if session.strategy_kind is None:
        return {s: [] for s in session.symbols}
    from app.algos.backtest import _load_warmup  # here: the backtester imports sim.runner, which imports us

    today = session.created_at.astimezone(UTC).date()
    return _load_warmup(
        db, provider, list(session.symbols), session.interval, session.start_date,
        warmup_bars(db, session), today,
    )  # fmt: skip


def describe(db: Session, session: SimSession) -> SimStrategyOut | None:
    """What the state shows about the strategy. A listing shows its name and creator only."""
    kind = session.strategy_kind
    if kind is None:
        return None
    if kind == "listing":
        listing = db.get(AlgoListing, session.listing_id) if session.listing_id else None
        creator = db.get(User, listing.owner_user_id) if listing is not None else None
        return SimStrategyOut(
            kind="listing", name=listing.name if listing else "A marketplace algorithm",
            interval=session.interval, creator=creator.username if creator else None,
        )  # fmt: skip
    if kind == "source":
        meta = validate_source(session.source or "").meta
        name = meta.name if meta is not None else "Uploaded code"
    else:
        algo = db.get(UserAlgo, session.user_algo_id) if kind == "mine" and session.user_algo_id else None
        name = algo.name if algo is not None else _library(session.strategy_key).name
    return SimStrategyOut(kind=kind, name=name, interval=session.interval)  # type: ignore[arg-type]


# --- the runs held in memory ------------------------------------------------------------------


@dataclass
class _Held:
    run: StrategyRun
    sandbox: SandboxedStrategy | None  # the child process of uploaded code; None for a library algo


_runs: dict[int, _Held] = {}
_finished_logs: dict[int, list[LogLine]] = {}
# Guards the dict only: a session's steps are already serialized by the runner's per-session lock,
# which every caller (advance, reset, delete) holds, so a run is never closed mid-step.
_lock = threading.RLock()


def drop(session_id: int, keep_log: bool = False) -> None:
    """Forget a session's run and close its sandbox child. `keep_log` (a session that finished)
    leaves its last log lines readable until it is reset or deleted."""
    with _lock:
        held = _runs.pop(session_id, None)
        if keep_log and held is not None:
            _finished_logs[session_id] = list(held.run.logs[-LOG_LINES:])
        elif not keep_log:
            _finished_logs.pop(session_id, None)
    if held is not None and held.sandbox is not None:
        held.sandbox.close()


def drop_all() -> None:
    for session_id in list(_runs):
        drop(session_id)
    _finished_logs.clear()


def _build(sim: SimRun) -> _Held:
    session = sim.session
    sandbox: SandboxedStrategy | None = None
    if session.source is not None and session.strategy_kind in ("source", "mine"):
        sandbox = load_strategy(session.source)
        strategy, params = sandbox, session.params
    elif session.strategy_kind in ("library", "mine"):
        strategy, params = _library(session.strategy_key), session.params
    else:  # listing: the version pinned at create, never the listing's current fields
        code, _ = listings.code_for(sim.ctx.db, session.listing_id, session.listing_version)
        if isinstance(code, str):
            sandbox = load_strategy(code)
            strategy, params = sandbox, None
        else:
            strategy, params = _library(code[0]), code[1]
    try:
        run = run_strategy_on(sim.ctx, strategy, params, list(session.symbols))
        if sim.warmed and session.cursor == sim.first_cursor:
            # As in the backtester: the warmup bars are already closed, so the strategy may decide
            # on them before the first session opens and its order fills at that first open.
            run.step()
    except BaseException:
        if sandbox is not None:
            sandbox.close()
        raise
    return _Held(run, sandbox)


def ensure(sim: SimRun) -> StrategyRun | None:
    """The session's run on `sim`'s context (built on first use, and again after a restart, which
    loses only the strategy's own memory); None when the session has no strategy."""
    session = sim.session
    if session.strategy_kind is None:
        return None
    with _lock:
        held = _runs.get(session.id)
        if held is None:
            held = _runs[session.id] = _build(sim)
        else:
            held.run.rebind(sim.ctx)
        return held.run


def tick(sim: SimRun, run: StrategyRun | None) -> None:
    """One bar's work: the strategy's step (which includes the tick), or just the tick."""
    if run is None:
        run_tick(sim.ctx)
        return
    try:
        run.step()
    except BaseException:
        drop(sim.session.id, keep_log=True)  # a failed run is rebuilt next time; its child must not linger
        raise


def log_lines(session: SimSession) -> list[LogLine]:
    """The strategy's last log lines, for code the requester may see; never for a listing."""
    if session.strategy_kind in (None, "listing"):
        return []
    with _lock:
        held = _runs.get(session.id)
        if held is None:
            return list(_finished_logs.get(session.id, []))
        return list(held.run.logs[-LOG_LINES:])
