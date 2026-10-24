from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DbSession, Provider, clean_symbol
from app.models import Order, OrderStatus, TradeStatus
from app.schemas import (
    BrokerRefOut,
    ChargeOut,
    ExitIn,
    OrderIn,
    OrderOut,
    OrderPreviewOut,
    PayoutsOut,
    PortfolioOut,
    ProtectionIn,
    ProtectionPreviewOut,
    TradeOut,
)
from app.trading import engine

router = APIRouter(prefix="/api", tags=["trading"])


@router.get("/portfolio", response_model=PortfolioOut)
def portfolio(db: DbSession, provider: Provider):
    return engine.get_portfolio(db, provider)


@router.post("/portfolio/reset", response_model=PortfolioOut)
def reset_portfolio(db: DbSession, provider: Provider):
    engine.reset_account(db)
    return engine.get_portfolio(db, provider)


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    db: DbSession,
    status: OrderStatus | None = None,
    symbol: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    account = engine.get_account(db)
    query = select(Order).where(Order.account_id == account.id)
    if status is not None:
        query = query.where(Order.status == status)
    if symbol is not None:
        query = query.where(Order.symbol == clean_symbol(symbol))
    return db.scalars(query.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit)).all()


@router.post("/orders", response_model=OrderOut)
def create_order(body: OrderIn, db: DbSession, provider: Provider):
    return engine.place_order(
        db,
        provider,
        symbol=clean_symbol(body.symbol),
        side=body.side,
        type=body.type,
        quantity=body.quantity_decimal(),
        limit_price=body.limit_price_decimal(),
    )


def _preview_out(cost: engine.PlanCost) -> OrderPreviewOut:
    return OrderPreviewOut(
        symbol=cost.symbol,
        side=cost.side,
        quantity=cost.quantity,
        price=cost.price,
        value=cost.value,
        currency=cost.currency,
        fx_rate=cost.fx_rate,
        value_account=cost.value_account,
        charges=[ChargeOut.model_validate(c) for c in cost.charges],
        charges_total=cost.charges_total,
        cash_change=cost.cash_change,
        margin_change=cost.margin_change,
        realized_pnl=cost.realized_pnl,
        legs=[engine.leg_out(leg) for leg in cost.legs],
        fifo=cost.fifo,
        note=cost.note,
        broker=BrokerRefOut(code=cost.broker.code, name=cost.broker.name),
        market=BrokerRefOut(code=cost.market.code, name=cost.market.name),
    )


@router.post("/orders/preview", response_model=OrderPreviewOut)
def preview_order(body: OrderIn, db: DbSession, provider: Provider):
    cost = engine.preview_order(
        db,
        provider,
        symbol=clean_symbol(body.symbol),
        side=body.side,
        type=body.type,
        quantity=body.quantity_decimal(),
        limit_price=body.limit_price_decimal(),
    )
    return _preview_out(cost)


@router.delete("/orders/{order_id}", response_model=OrderOut)
def cancel_order(order_id: int, db: DbSession):
    return engine.cancel_order(db, order_id)


@router.get("/trades", response_model=list[TradeOut])
def list_trades(
    db: DbSession,
    provider: Provider,
    status: TradeStatus | None = None,
    symbol: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    return engine.list_trades(
        db, provider, status=status, symbol=clean_symbol(symbol) if symbol else None, limit=limit
    )


@router.get("/payouts", response_model=PayoutsOut)
def payouts(db: DbSession, limit: Annotated[int, Query(ge=1, le=500)] = 200):
    return engine.get_payouts(db, limit=limit)


@router.post("/trades/{trade_id}/exit", response_model=OrderOut)
def exit_trade(trade_id: int, db: DbSession, provider: Provider, body: ExitIn | None = None):
    quantity = body.quantity_decimal() if body else None
    return engine.exit_trade(db, provider, trade_id, quantity)


@router.post("/trades/{trade_id}/exit/preview", response_model=OrderPreviewOut)
def preview_exit(trade_id: int, db: DbSession, provider: Provider, body: ExitIn | None = None):
    quantity = body.quantity_decimal() if body else None
    return _preview_out(engine.preview_exit(db, provider, trade_id, quantity))


@router.post("/trades/{trade_id}/protection/preview", response_model=ProtectionPreviewOut)
def preview_protection(trade_id: int, body: ProtectionIn, db: DbSession, provider: Provider):
    preview = engine.preview_protection(db, provider, trade_id, body.stop_decimal(), body.target_decimal())
    return ProtectionPreviewOut(
        current_price=preview.current_price,
        currency=preview.currency,
        stop_error=preview.errors.get("stop_price"),
        target_error=preview.errors.get("target_price"),
        stop_outcome=preview.stop_outcome,  # type: ignore[arg-type]
        target_outcome=preview.target_outcome,  # type: ignore[arg-type]
    )


@router.put("/trades/{trade_id}/protection", response_model=TradeOut)
def set_protection(trade_id: int, body: ProtectionIn, db: DbSession, provider: Provider):
    return engine.set_protection(db, provider, trade_id, body.stop_decimal(), body.target_decimal())
