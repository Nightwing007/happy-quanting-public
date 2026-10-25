"""Deployments: the user's own algorithms (a library one with tuned settings, or one they saved)
running live on a dedicated paper account.

Same shape as a marketplace subscription, without a creator or a fee: the capital moves from the
live account into a `kind="algo"` account, the background loop steps one `StrategyRun` per active
deployment (`closed_only`, so the forming bar is hidden), and stopping exits through the engine
before the cash comes back. The shared parts live in `algos/live_runs.py`.

What runs is a snapshot taken at deploy time (see `models.Deployment`): changing the saved
algorithm afterwards never changes a deployment.

Pause. A paused deployment keeps its positions, and the tick (fills, stop-loss and target
protection, intraday square-off, financing) still runs on its account every pass, because those
are real open positions. Only the strategy goes quiet: its run is closed, so it decides and
orders nothing, and on resume it is rebuilt (losing its own memory, as after a restart) and
picks up the positions it finds.
"""

import logging
from collections import deque
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.algos import live_runs
from app.algos.api import ParameterError, validate_params
from app.algos.library import LIBRARY
from app.algos.live_runs import Held
from app.algos.runner import LogLine
from app.algos.sandbox import load_strategy
from app.hosted import refuse_saved_code
from app.market_data.base import MarketDataProvider
from app.marketplace.listings import MarketplaceError, _market_codes, check_source
from app.models import CashTransfer, Deployment, DeploymentStatus, User, UserAlgo
from app.trading import engine
from app.trading.context import TradingContext
from app.trading.tick import run_tick

logger = logging.getLogger(__name__)
ZERO = Decimal(0)
LOG_LINES = 200  # what the page can show of "what the algo is doing"

_registry = live_runs.Registry()
_runs = _registry.runs
_lock = live_runs.KeyedLocks()
# The last LOG_LINES lines of each deployment, kept in memory only (a restart empties them).
_logs: dict[int, deque[LogLine]] = {}


class DeploymentError(MarketplaceError):
    """A deployment request that can't be honoured; `code` is what clients branch on. A subclass of
    the marketplace's error so the app's one handler answers it (`invalid_source` carries problems)."""


def _err(code: str, message: str) -> DeploymentError:
    return DeploymentError(code, message)


def not_found(deployment_id: int) -> DeploymentError:
    return DeploymentError("deployment_not_found", f"There is no deployment {deployment_id}.", 404)


# --- reading -----------------------------------------------------------------------------------


def get_deployment(db: Session, user: User, deployment_id: int) -> Deployment:
    """The user's own deployment; anyone else's is "not found"."""
    found = db.get(Deployment, deployment_id)
    if found is None or found.user_id != user.id:
        raise not_found(deployment_id)
    return found


def list_deployments(db: Session, user: User) -> list[Deployment]:
    return list(
        db.scalars(select(Deployment).where(Deployment.user_id == user.id).order_by(Deployment.id.desc()))
    )


def returned_cash(db: Session, dep: Deployment) -> Decimal:
    """What came back to the live account when the deployment stopped."""
    rows = db.scalars(
        select(CashTransfer.amount).where(CashTransfer.deployment_id == dep.id, CashTransfer.kind == "return")
    )
    return sum(rows, ZERO)


def dep_context(db: Session, provider: MarketDataProvider, dep: Deployment) -> TradingContext:
    return live_runs.account_context(db, provider, dep.account_id)


def logs(deployment_id: int) -> list[LogLine]:
    """The strategy's recent log lines, oldest first."""
    return list(_logs.get(deployment_id, ()))


# --- deploying ---------------------------------------------------------------------------------


def _plain(value):
    return f"{value:f}" if isinstance(value, Decimal) else value


def _snapshot_params(strategy, merged: dict) -> dict:
    """Every setting of the strategy (defaults filled in), coerced and bounds-checked, as JSON."""
    try:
        values = validate_params(strategy, merged)
    except ParameterError as why:
        raise DeploymentError("invalid_params", str(why)) from why
    return {name: _plain(v) for name, v in values.items()}


def _resolve(
    db: Session, user: User, library_key: str | None, params: dict | None, algo_id: int | None
) -> dict:  # fmt: skip
    """What to pin: the Deployment's strategy columns plus `name` and the `markets` it may trade."""
    if (library_key is None) == (algo_id is None):
        raise DeploymentError("one_algorithm", "Give exactly one of: a library algorithm or a saved one.")
    given = dict(params or {})
    if library_key is not None:
        cls = LIBRARY.get(library_key)
        if cls is None:
            choices = ", ".join(LIBRARY)
            raise DeploymentError(
                "unknown_algorithm", f"There is no algorithm '{library_key}'. Choose one of: {choices}."
            )
        return dict(
            name=cls.name, markets=cls.markets, strategy_kind="library", strategy_key=library_key,
            params=_snapshot_params(cls, given), source=None, user_algo_id=None,
        )  # fmt: skip
    algo = db.get(UserAlgo, algo_id)
    if algo is None or algo.owner_user_id != user.id:  # someone else's is "not found"
        raise DeploymentError("algo_not_found", f"There is no saved algorithm {algo_id}.", 404)
    merged = {**algo.params, **given}  # the saved settings are the start; anything sent wins
    if algo.source is None:  # a library algorithm with the settings the person tuned
        cls = LIBRARY.get(algo.strategy_key)
        if cls is None:
            raise DeploymentError("unknown_algorithm", f"There is no algorithm '{algo.strategy_key}'.")
        return dict(
            name=algo.name, markets=cls.markets, strategy_kind="mine", strategy_key=algo.strategy_key,
            params=_snapshot_params(cls, merged), source=None, user_algo_id=algo.id,
        )  # fmt: skip
    refuse_saved_code(algo)
    meta = check_source(algo.source)  # editor code and block graphs run under the same code rules
    sandbox = load_strategy(algo.source)  # starts no process until a hook runs
    try:
        pinned = _snapshot_params(sandbox, merged)
    finally:
        sandbox.close()
    return dict(
        name=algo.name, markets=meta.markets, strategy_kind="mine", strategy_key="", params=pinned,
        source=algo.source, user_algo_id=algo.id,
    )  # fmt: skip


def deploy(
    db: Session,
    provider: MarketDataProvider,
    user: User,
    *,
    library_key: str | None = None,
    params: dict | None = None,
    algo_id: int | None = None,
    symbols: list[str],
    capital: Decimal,
    name: str | None = None,
) -> Deployment:
    """Check everything, fund a new algo account from the user's live cash and record the
    deployment. The strategy starts on the next pass of the background loop."""
    pinned = _resolve(db, user, library_key, params, algo_id)
    markets = pinned.pop("markets")
    default_name = pinned.pop("name")
    names = live_runs.clean_symbols(symbols, _err)
    live = engine.account_for_user(db, user.id)
    live_runs.check_symbols(provider, live, names, _market_codes(list(markets)), _err)
    capital = live_runs.check_capital(live, capital, _err)

    now = clock.now()
    account = live_runs.open_account(db, live, user.id, capital)
    dep = Deployment(
        user_id=user.id, name=(name or "").strip() or default_name, account_id=account.id, symbols=names,
        capital=capital, status=DeploymentStatus.ACTIVE, created_at=now, **pinned,
    )  # fmt: skip
    db.add(dep)
    db.flush()
    db.add(CashTransfer(deployment_id=dep.id, kind="fund", amount=capital, created_at=now))
    db.commit()
    return dep


# --- pause, resume, stop -----------------------------------------------------------------------


def pause(db: Session, user: User, deployment_id: int) -> Deployment:
    """Stop the strategy placing new orders; positions, protection and the tick carry on."""
    dep = get_deployment(db, user, deployment_id)
    with _lock(dep.id):
        db.refresh(dep)
        if dep.status != DeploymentStatus.ACTIVE:
            raise DeploymentError("deployment_not_active", "Only a running deployment can be paused.", 409)
        dep.status = DeploymentStatus.PAUSED
        db.commit()
    _registry.drop(dep.id)  # the strategy decides nothing from here; close its sandbox child
    return dep


def resume(db: Session, user: User, deployment_id: int) -> Deployment:
    """Let the strategy trade again; it is rebuilt on the next pass of the loop."""
    dep = get_deployment(db, user, deployment_id)
    with _lock(dep.id):
        db.refresh(dep)
        if dep.status != DeploymentStatus.PAUSED:
            raise DeploymentError("deployment_not_paused", "Only a paused deployment can be resumed.", 409)
        dep.status = DeploymentStatus.ACTIVE
        db.commit()
    return dep


def stop(db: Session, provider: MarketDataProvider, user: User, deployment_id: int) -> Deployment:
    """Stop trading and wind the account down. If an exit has to wait for the market to open the
    deployment stays `stopping` and the background loop finishes it."""
    dep = get_deployment(db, user, deployment_id)
    if dep.status == DeploymentStatus.STOPPED:
        return dep
    dep.status = DeploymentStatus.STOPPING
    db.commit()
    _registry.drop(dep.id)
    advance_stop(db, provider, dep)
    return dep


def advance_stop(db: Session, provider: MarketDataProvider, dep: Deployment) -> bool:
    """Move a stopping deployment forward: exit what is open and, once the account is flat, return
    its cash to the live account. Returns whether it is now stopped."""
    with _lock(dep.id):
        db.refresh(dep)
        if dep.status == DeploymentStatus.STOPPED:
            return True  # the other thread finished it: the cash is already back
        ctx = dep_context(db, provider, dep)
        db.refresh(ctx.account)
        live_runs.wind_down(ctx)
        if not live_runs.is_flat(ctx):
            return False
        live_runs.return_cash(db, ctx.account, dep.user_id, {"deployment_id": dep.id})
        dep.status = DeploymentStatus.STOPPED
        dep.stopped_at = clock.now()
        db.commit()
        return True


# --- running live ------------------------------------------------------------------------------


def drop(deployment_id: int) -> None:
    _registry.drop(deployment_id)


def drop_all() -> None:
    _registry.drop_all()


def _note(deployment_id: int, at, text: str) -> None:
    _logs.setdefault(deployment_id, deque(maxlen=LOG_LINES)).append(LogLine(at, text))


def _drain(deployment_id: int) -> None:
    held = _runs.get(deployment_id)
    if held is not None:
        buffer = _logs.setdefault(deployment_id, deque(maxlen=LOG_LINES))
        buffer.extend(held.run.drain_logs())


def _build(ctx: TradingContext, dep: Deployment) -> Held:
    """Build from the pinned snapshot, never from the saved algorithm it came from."""
    if dep.source is not None:
        sandbox = load_strategy(dep.source)
        strategy = sandbox
    else:
        sandbox, strategy = None, LIBRARY[dep.strategy_key]
    return live_runs.build_held(ctx, strategy, sandbox, dep.params, list(dep.symbols), 0)


def _step_active(db: Session, provider: MarketDataProvider, dep: Deployment) -> None:
    ctx = dep_context(db, provider, dep)
    with _lock(dep.id):
        db.refresh(dep)
        if dep.status != DeploymentStatus.ACTIVE:
            return  # paused or stopped since the pass began: it must not order again
        try:
            _registry.step(dep.id, ctx, lambda: _build(ctx, dep))
        except Exception as why:
            _note(dep.id, ctx.now(), f"The algorithm could not run: {type(why).__name__}: {why}")
            raise
        finally:
            _drain(dep.id)


def _advance(db: Session, provider: MarketDataProvider, dep: Deployment) -> None:
    if dep.status == DeploymentStatus.ACTIVE:
        _step_active(db, provider, dep)
        return
    _registry.drop(dep.id)
    run_tick(dep_context(db, provider, dep))  # protection, fills and square-off still apply
    if dep.status == DeploymentStatus.STOPPING:
        advance_stop(db, provider, dep)


def run_deployments_once(db: Session, provider: MarketDataProvider) -> None:
    """One pass of the background loop. Every failure is contained to its deployment."""
    deps = list(
        db.scalars(
            select(Deployment).where(Deployment.status != DeploymentStatus.STOPPED).order_by(Deployment.id)
        )
    )
    for dep in deps:
        try:
            _advance(db, provider, dep)
        except Exception:  # noqa: BLE001 - one deployment's failure must not stop the others
            db.rollback()
            logger.exception("Deployment %s failed; will retry", dep.id)
    # Anything no longer active must not keep a child process alive.
    active = {d.id for d in deps if d.status == DeploymentStatus.ACTIVE}
    for dep_id in list(_runs):
        if dep_id not in active:
            _registry.drop(dep_id)
