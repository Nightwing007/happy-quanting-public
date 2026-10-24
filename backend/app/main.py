import asyncio
import contextlib
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import clock
from app.algos import jobs as backtest_jobs
from app.algos.api import ParameterError
from app.algos.backtest import BacktestError
from app.algos.runner import StrategyRunError
from app.api import algos, backtests, blocks, market, marketplace, sim, trading, watchlist
from app.api import auth as auth_api
from app.api import settings as settings_api
from app.api.deps import Provider
from app.auth import AuthError, ensure_demo_password
from app.config import Settings, get_settings
from app.db import SessionLocal
from app.market_data import get_provider
from app.market_data.base import DataUnavailable, MarketDataError, SymbolNotFound
from app.market_data.history import HistoryRangeError
from app.marketplace.listings import MarketplaceError
from app.marketplace.live import drop_all, run_subscriptions_once
from app.marketplace.seed import seed_marketplace
from app.migrate import upgrade_database
from app.sim.driver import drive_loop
from app.sim.runner import SimError
from app.trading.context import TradingContext
from app.trading.engine import (
    convert_account_currency,
    first_run_setup,
    live_accounts,
    live_context,
)
from app.trading.errors import OrderNotFound, TradeNotFound, TradingError
from app.trading.tick import run_tick

logger = logging.getLogger(__name__)

FILL_INTERVAL_SECONDS = 60
NOT_FOUND_CODES = {OrderNotFound.code, TradeNotFound.code}


def _fill_once() -> None:
    # Runs in a worker thread, so it opens its own session (sessions are not thread-safe).
    # Live accounts only: a sim or backtest account is driven by its own run, on its own clock.
    try:
        with SessionLocal() as db:
            provider = get_provider()
            for account in live_accounts(db):
                run_tick(TradingContext(db, account, provider, lambda: clock.now()))
            # Subscriptions trade on their own accounts, after the live tick so both see one clock.
            # This loop only exists when background jobs are on.
            run_subscriptions_once(db, provider)
    except Exception:  # noqa: BLE001 - the loop must survive any single failure
        logger.exception("Background tick failed; will retry")


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
            demo_password = ensure_demo_password(db)
            if demo_password:
                # print, not the logger: a password must not land in log files.
                print(f"\n=====\nDemo login: demo / {demo_password}  (shown once)\n=====", flush=True)
            # BASE_CURRENCY changed since the account was made: convert it (or log and carry on).
            for account in live_accounts(db):
                if account.user_id is not None:
                    ctx = live_context(db, get_provider(), account.user_id)
                    convert_account_currency(ctx, settings.base_currency)
            if settings.seed_demo_marketplace and settings.background_jobs:
                try:
                    seed_marketplace(db, get_provider())
                except Exception:  # noqa: BLE001 - e.g. offline: the demo listings are not worth a failed start
                    logger.exception("Seeding the demo marketplace failed; it will be retried next start")
    tasks = (
        [asyncio.create_task(_fill_loop()), asyncio.create_task(drive_loop())]
        if settings.background_jobs
        else []
    )
    worker = backtest_jobs.start_worker() if settings.background_jobs else None
    try:
        yield
    finally:
        if worker is not None:
            backtest_jobs.stop_worker(*worker)
        drop_all()  # close any subscription sandbox children
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="Happy Quanting", lifespan=lifespan)
app.include_router(auth_api.router)
app.include_router(algos.router)
app.include_router(blocks.router)
app.include_router(market.router)
app.include_router(trading.router)
app.include_router(sim.router)
app.include_router(sim.trading_router)
app.include_router(backtests.router)
app.include_router(marketplace.router)
app.include_router(settings_api.router)
app.include_router(watchlist.router)


def _market_error(status_code: int):
    def handler(request: Request, exc: MarketDataError) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": exc.message})

    return handler


app.add_exception_handler(HistoryRangeError, _market_error(400))
app.add_exception_handler(SymbolNotFound, _market_error(404))
app.add_exception_handler(DataUnavailable, _market_error(503))
app.add_exception_handler(MarketDataError, _market_error(502))


def _trading_error(request: Request, exc: TradingError) -> JSONResponse:
    content = {"detail": exc.message, "code": exc.code}
    fields = getattr(exc, "fields", None)
    if fields:
        content["fields"] = fields
    # A missing order or trade is a 404, and another user's is "missing" too (never a 403).
    status = 404 if exc.code in NOT_FOUND_CODES else 400
    return JSONResponse(status_code=status, content=content)


app.add_exception_handler(TradingError, _trading_error)


def _auth_error(request: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})


app.add_exception_handler(AuthError, _auth_error)


def _sim_error(request: Request, exc: SimError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


app.add_exception_handler(SimError, _sim_error)


def _backtest_error(request: Request, exc: BacktestError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


app.add_exception_handler(BacktestError, _backtest_error)


def _marketplace_error(request: Request, exc: MarketplaceError) -> JSONResponse:
    content: dict = {"detail": exc.message, "code": exc.code}
    if exc.problems:
        content["problems"] = [
            {"line": p.line, "col": p.col, "code": p.code, "message": p.message} for p in exc.problems
        ]
    return JSONResponse(status_code=exc.status_code, content=content)


app.add_exception_handler(MarketplaceError, _marketplace_error)


def _bad_settings(request: Request, exc: ParameterError | StrategyRunError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.add_exception_handler(ParameterError, _bad_settings)
app.add_exception_handler(StrategyRunError, _bad_settings)


async def _validation_error(request: Request, exc: RequestValidationError):
    # Pydantic's list of error dicts is for developers. For an order the person typed, give one
    # readable sentence; every other route keeps the default shape.
    errors = exc.errors()
    # A sim's trading routes are the live ones under a prefix, so they get the same wording.
    path = re.sub(r"^/api/sim/sessions/\d+", "/api", request.url.path)
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
