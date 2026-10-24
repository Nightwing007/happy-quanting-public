"""Backtests: queue one, poll it, read its results, delete it."""

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.algos import jobs
from app.api.deps import DbSession, Provider
from app.models import Backtest
from app.schemas import BacktestDetailOut, BacktestIn, BacktestSummaryOut

router = APIRouter(prefix="/api/backtests", tags=["backtests"])


@router.post("", response_model=BacktestSummaryOut)
def create_backtest(body: BacktestIn, db: DbSession, provider: Provider):
    return jobs.queue_backtest(db, provider, body)


@router.get("", response_model=list[BacktestSummaryOut])
def list_backtests(db: DbSession):
    return list(db.scalars(select(Backtest).order_by(Backtest.id.desc())))


@router.get("/{backtest_id}", response_model=BacktestDetailOut)
def get_backtest(backtest_id: int, db: DbSession):
    return jobs.get_backtest(db, backtest_id)


@router.delete("/{backtest_id}", status_code=204)
def delete_backtest(backtest_id: int, db: DbSession):
    jobs.delete_backtest(db, backtest_id)
    return Response(status_code=204)
