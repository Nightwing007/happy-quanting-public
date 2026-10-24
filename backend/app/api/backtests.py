"""Backtests: queue one, poll it, read its results, delete it."""

from fastapi import APIRouter, Response

from app.algos import jobs
from app.api.deps import CurrentUser, DbSession, Provider
from app.schemas import BacktestDetailOut, BacktestIn, BacktestSummaryOut

router = APIRouter(prefix="/api/backtests", tags=["backtests"])


@router.post("", response_model=BacktestSummaryOut)
def create_backtest(body: BacktestIn, db: DbSession, provider: Provider, user: CurrentUser):
    return jobs.queue_backtest(db, provider, body, owner_user_id=user.id)


@router.get("", response_model=list[BacktestSummaryOut])
def list_backtests(db: DbSession, user: CurrentUser):
    return jobs.list_backtests(db, user.id)


@router.get("/{backtest_id}", response_model=BacktestDetailOut)
def get_backtest(backtest_id: int, db: DbSession, user: CurrentUser):
    return jobs.get_backtest(db, backtest_id, user.id)


@router.delete("/{backtest_id}", status_code=204)
def delete_backtest(backtest_id: int, db: DbSession, user: CurrentUser):
    jobs.delete_backtest(db, backtest_id, user.id)
    return Response(status_code=204)
