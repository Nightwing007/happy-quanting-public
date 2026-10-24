"""The simulation: sessions that replay past days, and the ordinary trading routes scoped to one."""

from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentUser, DbSession, Provider, get_sim_context
from app.api.trading import build_router
from app.models import SimSession, SimStatus
from app.schemas import (
    BarOut,
    SimControlIn,
    SimExchangeTimeOut,
    SimLogOut,
    SimSessionIn,
    SimSessionOut,
    SimSessionStateOut,
)
from app.sim import runner, strategies

router = APIRouter(prefix="/api/sim/sessions", tags=["sim"])

# Everything a person does inside a simulation, through the same route bodies as the live account.
trading_router = build_router("/api/sim/sessions/{session_id}", get_sim_context, ["sim"], resettable=False)


def _out(run: runner.SimRun) -> dict:
    session = run.session
    return dict(
        id=session.id,
        account_id=session.account_id,
        symbols=session.symbols,
        interval=session.interval,
        start_date=session.start_date,
        end_date=session.end_date,
        speed=session.speed,
        status=session.status,
        cursor=session.cursor,
        exchange_times=[
            SimExchangeTimeOut(
                symbol=symbol, timezone=zone, local_time=session.cursor.astimezone(ZoneInfo(zone))
            )
            for symbol, zone in run.timezones.items()
        ],
        progress_percent=runner.progress_percent(run),
        created_at=session.created_at,
    )


def _revealed(run: runner.SimRun, limit: int) -> dict[str, list[BarOut]]:
    """The last `limit` bars of each symbol that had finished by the cursor. The replay answers
    only with those, so nothing from after the cursor can reach a chart."""
    out: dict[str, list[BarOut]] = {}
    for symbol in run.session.symbols:
        series = run.replay.get_bars(symbol, run.session.interval, "max") if limit else []
        out[symbol] = [BarOut(**vars(b)) for b in series[-limit:]] if limit else []
    return out


def _session_out(db: DbSession, session: SimSession, provider: Provider) -> SimSessionOut:
    return SimSessionOut(**_out(runner.build_run(db, session, provider)))


@router.post("", response_model=SimSessionOut)
def create_session(body: SimSessionIn, db: DbSession, provider: Provider, user: CurrentUser):
    session = runner.create_session(
        db,
        provider,
        symbols=body.symbols,
        interval=body.interval,
        start_date=body.start_date,
        end_date=body.end_date,
        speed=body.speed,
        owner_user_id=user.id,
        strategy=body.strategy,
    )
    return _session_out(db, session, provider)


@router.get("", response_model=list[SimSessionOut])
def list_sessions(db: DbSession, provider: Provider, user: CurrentUser):
    return [_session_out(db, s, provider) for s in runner.list_sessions(db, user.id)]


@router.get("/{session_id}", response_model=SimSessionStateOut)
def get_state(
    session_id: int,
    db: DbSession,
    provider: Provider,
    user: CurrentUser,
    bars_limit: Annotated[int, Query(ge=0, le=20000)] = 1000,
):
    session = runner.get_session(db, session_id, user.id)
    run = runner.build_run(db, session, provider)
    # strategy_log is empty for a listing (the tester may not see how it behaves), by construction.
    log = [SimLogOut(at=line.at, text=line.text) for line in strategies.log_lines(session)]
    return SimSessionStateOut(
        **_out(run),
        bars=_revealed(run, bars_limit),
        strategy=strategies.describe(db, session),
        strategy_log=log,
    )


@router.post("/{session_id}/control", response_model=SimSessionOut)
def control(session_id: int, body: SimControlIn, db: DbSession, provider: Provider, user: CurrentUser):
    session = runner.get_session(db, session_id, user.id)
    if body.speed is not None:
        runner.set_speed(db, session, body.speed)
    match body.action:
        case "start":
            runner.set_status(db, session, SimStatus.RUNNING)
        case "pause":
            runner.set_status(db, session, SimStatus.PAUSED)
        case "step":
            if session.status not in (SimStatus.READY, SimStatus.PAUSED):
                raise runner.SimConflict("Pause the simulation before stepping it.")
            runner.advance(db, session, body.steps or 1, provider)
            if session.status == SimStatus.READY:
                runner.set_status(db, session, SimStatus.PAUSED)
        case "reset":
            runner.reset_session(db, session, provider)
    return _session_out(db, session, provider)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: int, db: DbSession, user: CurrentUser):
    runner.delete_session(db, runner.get_session(db, session_id, user.id))
    return Response(status_code=204)
