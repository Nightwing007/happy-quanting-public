"""Predefined algorithms (read-only) and the ones people saved."""

import pathlib
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app import clock
from app.algos import rules
from app.algos.api import Param, Strategy, validate_params
from app.algos.library import LIBRARY
from app.algos.sandbox import load_strategy, run_in_subprocess
from app.algos.validate import validate_and_dry_run, validate_source
from app.api.deps import CurrentUser, DbSession
from app.models import UserAlgo
from app.schemas import (
    AlgoOut,
    AlgoParamOut,
    ProblemOut,
    RulesOut,
    StrategyMetaOut,
    UserAlgoIn,
    UserAlgoOut,
    ValidateIn,
    ValidationReportOut,
)

router = APIRouter(prefix="/api/algos", tags=["algos"])


def _plain(value):
    return f"{value:f}" if isinstance(value, Decimal) else value


def _param_out(name: str, param: Param) -> AlgoParamOut:
    return AlgoParamOut(
        name=name,
        label=param.label or name.replace("_", " ").capitalize(),
        kind=param.kind,  # type: ignore[arg-type]
        default=_plain(param.default),
        min=_plain(param.min),
        max=_plain(param.max),
        choices=list(param.choices),
        help=param.help,
    )


def _algo_out(key: str, algo: type[Strategy]) -> AlgoOut:
    return AlgoOut(
        key=key,
        name=algo.name,
        description=algo.description,
        markets=list(algo.markets),
        interval=algo.interval,
        warmup_bars=algo.warmup_bars,
        parameters=[_param_out(n, p) for n, p in algo.PARAMETERS.items()],
    )


@router.get("/library", response_model=list[AlgoOut])
def list_library():
    return [_algo_out(key, algo) for key, algo in LIBRARY.items()]


RULES_DOC = pathlib.Path(__file__).parents[3] / "docs" / "algo-rules.md"


@router.get("/rules", response_model=RulesOut)
def algo_rules():
    """The rules page and its numbers, from the one doc and the one constants module (public)."""
    return RulesOut(markdown=RULES_DOC.read_text(encoding="utf-8"), limits=rules.DOCUMENTED_LIMITS)


@router.post("/validate", response_model=ValidationReportOut)
def validate_code(body: ValidateIn, user: CurrentUser):
    """Check uploaded strategy code against the rules in docs/algo-rules.md; nothing is saved."""
    report = validate_and_dry_run(body.source, runner=run_in_subprocess)
    meta = report.meta
    return ValidationReportOut(
        ok=report.ok,
        problems=[
            ProblemOut(line=p.line, col=p.col, code=p.code, message=p.message) for p in report.problems
        ],
        meta=None
        if meta is None
        else StrategyMetaOut(
            name=meta.name,
            description=meta.description,
            markets=list(meta.markets),
            interval=meta.interval,
            parameters=[_param_out(n, p) for n, p in meta.parameters.items()],
            warmup_bars=meta.warmup_bars,
        ),
    )


# --- saved algorithms: a library strategy plus the settings someone tuned --------------------


def _mine_out(row: UserAlgo) -> UserAlgoOut:
    if row.source is not None:  # editor code: the name, bar size and markets are its own literals
        meta = validate_source(row.source).meta
        return UserAlgoOut(
            id=row.id, name=row.name, description=row.description, strategy="",
            strategy_name=meta.name if meta else row.name, interval=meta.interval if meta else "",
            markets=list(meta.markets) if meta else [], params=row.params, source=row.source,
            created_at=row.created_at,
        )  # fmt: skip
    algo = LIBRARY.get(row.strategy_key)
    return UserAlgoOut(
        id=row.id,
        name=row.name,
        description=row.description,
        strategy=row.strategy_key,
        strategy_name=algo.name if algo else row.strategy_key,
        interval=algo.interval if algo else "",
        markets=list(algo.markets) if algo else [],
        params=row.params,
        created_at=row.created_at,
    )


def _checked(body: UserAlgoIn) -> tuple[str, dict]:
    """The strategy and its full, validated settings; raises with the server's own sentences."""
    if body.strategy is None:
        raise HTTPException(status_code=400, detail="Say which algorithm this is built on, or send `source`.")
    algo = LIBRARY.get(body.strategy)
    if algo is None:
        raise HTTPException(
            status_code=400,
            detail=f"There is no algorithm '{body.strategy}'. Choose one of: {', '.join(LIBRARY)}.",
        )
    values = validate_params(algo, body.params)
    return body.strategy, {name: _plain(v) for name, v in values.items()}


def _checked_source(body: UserAlgoIn) -> dict:
    """Editor code must pass the code rules (raises with every problem, worded with its line); the
    settings are validated against the class's own `PARAMETERS`."""
    from app.marketplace.listings import check_source  # here: listings reads the algos package

    check_source(body.source or "")
    sandbox = load_strategy(body.source or "")  # starts no process until a hook runs
    try:
        values = validate_params(sandbox, body.params)  # type: ignore[arg-type]
    finally:
        sandbox.close()
    return {name: _plain(v) for name, v in values.items()}


def _found(db, algo_id: int, user_id: int) -> UserAlgo:
    row = db.get(UserAlgo, algo_id)
    if row is None or row.owner_user_id != user_id:
        raise HTTPException(status_code=404, detail=f"There is no saved algorithm {algo_id}.")
    return row


@router.get("/mine", response_model=list[UserAlgoOut])
def list_mine(db: DbSession, user: CurrentUser):
    rows = db.scalars(select(UserAlgo).where(UserAlgo.owner_user_id == user.id).order_by(UserAlgo.id.desc()))
    return [_mine_out(r) for r in rows]


@router.post("/mine", response_model=UserAlgoOut)
def create_mine(body: UserAlgoIn, db: DbSession, user: CurrentUser):
    if body.source is not None and body.strategy is not None:
        raise HTTPException(status_code=400, detail="Send either `strategy` or `source`, not both.")
    if body.source is not None:
        key, params = "", _checked_source(body)
    else:
        key, params = _checked(body)
    row = UserAlgo(
        owner_user_id=user.id,
        name=body.name,
        description=body.description,
        strategy_key=key,
        params=params,
        source=body.source,
        created_at=clock.now(),
    )
    db.add(row)
    db.commit()
    return _mine_out(row)


@router.get("/mine/{algo_id}", response_model=UserAlgoOut)
def get_mine(algo_id: int, db: DbSession, user: CurrentUser):
    return _mine_out(_found(db, algo_id, user.id))


@router.put("/mine/{algo_id}", response_model=UserAlgoOut)
def update_mine(algo_id: int, body: UserAlgoIn, db: DbSession, user: CurrentUser):
    row = _found(db, algo_id, user.id)
    if body.source is not None and body.strategy is not None:
        raise HTTPException(status_code=400, detail="Send either `strategy` or `source`, not both.")
    if body.source is not None:
        row.strategy_key, row.params, row.source = "", _checked_source(body), body.source
    else:
        row.strategy_key, row.params = _checked(body)
        row.source = None
    row.name, row.description = body.name, body.description
    db.commit()
    return _mine_out(row)


@router.delete("/mine/{algo_id}", status_code=204)
def delete_mine(algo_id: int, db: DbSession, user: CurrentUser):
    db.delete(_found(db, algo_id, user.id))
    db.commit()
    return Response(status_code=204)
