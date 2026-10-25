"""Deployments: run your own algorithms live on a paper sub-account (`algos/deployments.py`)."""

from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import select

from app.algos import deployments
from app.api.deps import CurrentUser, DbSession, Provider
from app.models import Deployment, DeploymentStatus, Order
from app.schemas import (
    DeploymentDetailOut,
    DeploymentIn,
    DeploymentLogOut,
    DeploymentOut,
    OrderOut,
    PortfolioOut,
    TradeOut,
)
from app.trading import engine

router = APIRouter(prefix="/api/deployments", tags=["deployments"])

RECENT_ORDERS = 50


def _summary(db: DbSession, provider: Provider, dep: Deployment) -> tuple[dict, engine.Portfolio]:
    ctx = deployments.dep_context(db, provider, dep)
    portfolio = engine.get_portfolio(ctx)
    if dep.status == DeploymentStatus.STOPPED:
        # Flat and emptied: what came back is the final worth, and nothing is left unrealized.
        equity, unrealized = deployments.returned_cash(db, dep), Decimal(0)
    else:
        equity, unrealized = portfolio.total_value, portfolio.unrealized_pnl
    fields = dict(
        id=dep.id, name=dep.name, status=dep.status, strategy_kind=dep.strategy_kind,
        strategy_key=dep.strategy_key, runs_code=dep.source is not None, user_algo_id=dep.user_algo_id,
        params=dict(dep.params), symbols=list(dep.symbols), currency=ctx.account.currency,
        capital=dep.capital, equity=equity, realized_pnl=ctx.account.realized_pnl,
        unrealized_pnl=unrealized, created_at=dep.created_at, stopped_at=dep.stopped_at,
    )  # fmt: skip
    return fields, portfolio


def _out(db: DbSession, provider: Provider, dep: Deployment) -> DeploymentOut:
    return DeploymentOut(**_summary(db, provider, dep)[0])


@router.post("", response_model=DeploymentOut)
def create_deployment(body: DeploymentIn, db: DbSession, provider: Provider, user: CurrentUser):
    dep = deployments.deploy(
        db, provider, user, library_key=body.library_key, params=body.params, algo_id=body.algo_id,
        symbols=body.symbols, capital=body.capital, name=body.name,
    )  # fmt: skip
    return _out(db, provider, dep)


@router.get("", response_model=list[DeploymentOut])
def list_deployments(db: DbSession, provider: Provider, user: CurrentUser):
    return [_out(db, provider, dep) for dep in deployments.list_deployments(db, user)]


@router.get("/{deployment_id}", response_model=DeploymentDetailOut)
def get_deployment(deployment_id: int, db: DbSession, provider: Provider, user: CurrentUser):
    dep = deployments.get_deployment(db, user, deployment_id)
    fields, portfolio = _summary(db, provider, dep)
    orders = db.scalars(
        select(Order)
        .where(Order.account_id == dep.account_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(RECENT_ORDERS)
    )
    return DeploymentDetailOut(
        **fields,
        portfolio=PortfolioOut.model_validate(portfolio, from_attributes=True),
        open_trades=[TradeOut.model_validate(t, from_attributes=True) for t in portfolio.trades],
        orders=[OrderOut.model_validate(o) for o in orders],
        log=[DeploymentLogOut(at=line.at, text=line.text) for line in deployments.logs(dep.id)],
        total_charges=portfolio.charges_paid.total,
        total_pnl=portfolio.realized_pnl + portfolio.unrealized_pnl,
    )


@router.post("/{deployment_id}/pause", response_model=DeploymentOut)
def pause_deployment(deployment_id: int, db: DbSession, provider: Provider, user: CurrentUser):
    return _out(db, provider, deployments.pause(db, user, deployment_id))


@router.post("/{deployment_id}/resume", response_model=DeploymentOut)
def resume_deployment(deployment_id: int, db: DbSession, provider: Provider, user: CurrentUser):
    return _out(db, provider, deployments.resume(db, user, deployment_id))


@router.post("/{deployment_id}/stop", response_model=DeploymentOut)
def stop_deployment(deployment_id: int, db: DbSession, provider: Provider, user: CurrentUser):
    return _out(db, provider, deployments.stop(db, provider, user, deployment_id))
