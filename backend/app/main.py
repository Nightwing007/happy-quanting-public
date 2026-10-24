import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import market, trading, watchlist
from app.api import settings as settings_api
from app.api.deps import Provider
from app.config import Settings, get_settings
from app.db import SessionLocal
from app.market_data import get_provider
from app.market_data.base import DataUnavailable, MarketDataError, SymbolNotFound
from app.migrate import upgrade_database
from app.trading.engine import (
    accrue_financing,
    convert_account_currency,
    fill_open_orders,
    first_run_setup,
    square_off_due,
    trigger_protected_trades,
)
from app.trading.errors import TradingError

logger = logging.getLogger(__name__)

FILL_INTERVAL_SECONDS = 60


def _run_step(name: str, step) -> None:
    # Each step gets its own session and its own failure handling, so a bad tick in one (say,
    # a quote that won't load) never stops the others. Sessions are not thread-safe, hence one here.
    try:
        with SessionLocal() as db:
            result = step(db, get_provider())
        if result:
            logger.info("%s: %s", name, result if isinstance(result, int) else len(result))
    except Exception:  # noqa: BLE001 - one failing step must not stop the rest
        logger.exception("%s failed; will retry", name)


def _fill_once() -> None:
    # Runs in a worker thread.
    _run_step("Filling open orders", fill_open_orders)
    _run_step("Firing stop-losses and targets", trigger_protected_trades)
    _run_step("Squaring off intraday shorts", square_off_due)
    _run_step("Charging borrow and funding", accrue_financing)


async def _fill_loop() -> None:
    while True:
        await asyncio.sleep(FILL_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(_fill_once)
        except Exception:  # noqa: BLE001 - the loop must survive any single failure
            logger.exception("Background tick failed; will retry")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Migrations first: everything else assumes the schema exists. Tests switch this off via
    # RUN_MIGRATIONS=false, otherwise the TestClient's lifespan would touch the real dev DB.
    settings = get_settings()
    if settings.run_migrations:
        upgrade_database()
        # Same gate: without migrations there may be no tables (and in tests, no real DB).
        with SessionLocal() as db:
            first_run_setup(db)
            # BASE_CURRENCY changed since the account was made: convert it (or log and carry on).
            convert_account_currency(db, get_provider(), settings.base_currency)
    task = asyncio.create_task(_fill_loop()) if settings.background_jobs else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="Happy Quanting", lifespan=lifespan)
app.include_router(market.router)
app.include_router(trading.router)
app.include_router(settings_api.router)
app.include_router(watchlist.router)


def _market_error(status_code: int):
    def handler(request: Request, exc: MarketDataError) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    return handler


app.add_exception_handler(SymbolNotFound, _market_error(404))
app.add_exception_handler(DataUnavailable, _market_error(503))
app.add_exception_handler(MarketDataError, _market_error(502))


def _trading_error(request: Request, exc: TradingError) -> JSONResponse:
    content = {"detail": exc.message, "code": exc.code}
    fields = getattr(exc, "fields", None)
    if fields:
        content["fields"] = fields
    return JSONResponse(status_code=400, content=content)


app.add_exception_handler(TradingError, _trading_error)


async def _validation_error(request: Request, exc: RequestValidationError):
    # Pydantic's list of error dicts is for developers. For an order the person typed, give one
    # readable sentence; every other route keeps the default shape.
    errors = exc.errors()
    path = request.url.path
    order_like = path in ("/api/orders", "/api/orders/preview") or (
        path.startswith("/api/trades/") and path.endswith(("/exit", "/exit/preview"))
    )
    protection_like = path.startswith("/api/trades/") and path.endswith(
        ("/protection", "/protection/preview")
    )
    if (order_like and request.method == "POST" or protection_like) and errors:
        error = errors[0]
        message = str(error["msg"]).removeprefix("Value error, ")
        field = str(error["loc"][-1])
        if field not in ("quantity", "limit_price", "stop_price", "target_price"):
            message = f"{field}: {message}"
        return JSONResponse(status_code=422, content={"detail": message})
    return await request_validation_exception_handler(request, exc)


app.add_exception_handler(RequestValidationError, _validation_error)


@app.get("/api/health")
def health(provider: Provider, settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    return {
        "status": "ok",
        "data_source": provider.name,
        "base_currency": settings.base_currency,
    }
