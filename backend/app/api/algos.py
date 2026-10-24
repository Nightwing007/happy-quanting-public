"""Predefined algorithms, read-only."""

from decimal import Decimal

from fastapi import APIRouter

from app.algos.api import Param, Strategy
from app.algos.library import LIBRARY
from app.schemas import AlgoOut, AlgoParamOut

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
