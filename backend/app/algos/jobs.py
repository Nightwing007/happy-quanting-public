"""Backtests as background jobs: queued by the API, run one at a time on a worker thread.

One at a time because a run holds the CPU and the SQLite write lock for seconds; two at once would
only make both slower. Tests call `run_backtest_job` directly and never start the thread.
"""

import logging
import threading
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.algos.api import ParameterError
from app.algos.backtest import (
    BacktestConflict,
    BacktestError,
    BacktestNotFound,
    check_request,
    run_backtest,
    sweep_scratch_accounts,
)
from app.algos.sandbox import SandboxError, UserCodeError
from app.config import get_settings
from app.db import SessionLocal
from app.market_data import get_provider
from app.market_data.base import MarketDataError, MarketDataProvider
from app.models import Backtest, BacktestStatus, UserAlgo
from app.schemas import BacktestIn, BacktestResultsOut
from app.trading.errors import TradingError

logger = logging.getLogger(__name__)

IDLE_SECONDS = 2.0
_wake = threading.Event()


def _plain(value):
    return f"{value:f}" if isinstance(value, Decimal) else value


def queue_backtest(
    db: Session,
    provider: MarketDataProvider,
    body: BacktestIn,
    *,
    owner_user_id: int | None = None,
    today: date | None = None,
) -> Backtest:
    """Check the request as far as can be done without history, then queue it. Raises with a
    sentence when it can't run, so nothing doomed waits in the queue."""
    settings = get_settings()
    cash = body.starting_cash if body.starting_cash is not None else settings.starting_cash
    strategy, params = body.strategy, body.params
    if body.algo_id is not None:
        saved = db.get(UserAlgo, body.algo_id)
        if saved is None or saved.owner_user_id != owner_user_id:
            raise BacktestNotFound(f"There is no saved algorithm {body.algo_id}.")
        # The saved settings are the starting point; anything sent with the request wins.
        strategy, params = saved.strategy_key, {**saved.params, **body.params}
    elif strategy is None:
        raise BacktestError("Say which algorithm to test: a library key or a saved algorithm.")
    req = check_request(
        db, provider, strategy_key=strategy, strategy_cls=None, params=params,
        symbols=body.symbols, interval=body.interval, start=body.start_date, end=body.end_date,
        starting_cash=cash, brokers=body.brokers, today=today,
    )  # fmt: skip
    row = Backtest(
        owner_user_id=owner_user_id,
        strategy_key=req.key,
        params={name: _plain(v) for name, v in req.values.items()},
        symbols=req.names,
        interval=body.interval,
        start_date=body.start_date,
        end_date=body.end_date,
        starting_cash=cash,
        account_currency=settings.base_currency,
        brokers=req.brokers,
        status=BacktestStatus.QUEUED,
        progress=0,
        created_at=clock.now(),
    )
    db.add(row)
    db.commit()
    _wake.set()
    return row


def _load(db: Session, backtest_id: int) -> Backtest:
    found = db.get(Backtest, backtest_id)
    if found is None:
        raise BacktestNotFound(f"There is no backtest {backtest_id}.")
    return found


def get_backtest(db: Session, backtest_id: int, owner_user_id: int) -> Backtest:
    """The owner's backtest; someone else's is "not found". The worker uses `_load` instead."""
    found = _load(db, backtest_id)
    if found.owner_user_id != owner_user_id:
        raise BacktestNotFound(f"There is no backtest {backtest_id}.")
    return found


def list_backtests(db: Session, owner_user_id: int) -> list[Backtest]:
    return list(
        db.scalars(
            select(Backtest).where(Backtest.owner_user_id == owner_user_id).order_by(Backtest.id.desc())
        )
    )


def delete_backtest(db: Session, backtest_id: int, owner_user_id: int) -> None:
    row = get_backtest(db, backtest_id, owner_user_id)
    if row.status == BacktestStatus.RUNNING:
        raise BacktestConflict("This backtest is running. Delete it once it has finished.")
    db.delete(row)
    db.commit()


def _failure_text(why: Exception) -> str:
    if isinstance(
        why, ParameterError | BacktestError | MarketDataError | TradingError | SandboxError | UserCodeError
    ):
        return getattr(why, "message", None) or str(why)
    logger.exception("Backtest failed")
    return f"The backtest failed unexpectedly ({type(why).__name__}: {why})."


def run_backtest_job(
    db: Session, backtest_id: int, provider: MarketDataProvider | None = None, *, today: date | None = None
) -> None:
    """Run one queued backtest to the end, storing its results (or why it failed) on its row."""
    row = _load(db, backtest_id)  # the worker runs every owner's jobs
    provider = provider or get_provider()
    row.status = BacktestStatus.RUNNING
    row.progress = 0
    row.error = None
    db.commit()

    def report(percent: int) -> None:
        if percent != row.progress:
            row.progress = percent
            db.commit()

    def keep(results: BacktestResultsOut) -> None:
        row.results = results.model_dump(mode="json")
        row.status = BacktestStatus.DONE
        row.progress = 100
        db.commit()

    try:
        run_backtest(
            db, provider, strategy_key=row.strategy_key, params=row.params, symbols=row.symbols,
            interval=row.interval, start=row.start_date, end=row.end_date,
            starting_cash=row.starting_cash, brokers=row.brokers,
            account_currency=row.account_currency, today=today, progress=report, store=keep,
            owner_user_id=row.owner_user_id,
        )  # fmt: skip
    except Exception as why:  # noqa: BLE001 - whatever went wrong is what the person reads
        db.rollback()
        row.status = BacktestStatus.FAILED
        row.error = _failure_text(why)
        db.commit()


def _next_queued(db: Session) -> int | None:
    return db.scalar(
        select(Backtest.id).where(Backtest.status == BacktestStatus.QUEUED).order_by(Backtest.id).limit(1)
    )


def _recover(db: Session) -> None:
    """At start-up nothing is running, so a row still marked running was cut off by a restart and
    any backtest account is a leftover."""
    for row in db.scalars(select(Backtest).where(Backtest.status == BacktestStatus.RUNNING)):
        row.status = BacktestStatus.FAILED
        row.error = "The server restarted while this backtest was running. Run it again."
    db.commit()
    sweep_scratch_accounts(db)


def _work(stop: threading.Event) -> None:
    try:
        with SessionLocal() as db:
            _recover(db)
    except Exception:  # noqa: BLE001 - the worker must come up regardless
        logger.exception("Backtest recovery failed")
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                job = _next_queued(db)
                if job is not None:
                    run_backtest_job(db, job)
                    continue
        except Exception:  # noqa: BLE001 - the worker must survive any single failure
            logger.exception("Backtest worker failed; will retry")
        _wake.wait(IDLE_SECONDS)
        _wake.clear()


def start_worker() -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    thread = threading.Thread(target=_work, args=(stop,), name="backtest-worker", daemon=True)
    thread.start()
    return thread, stop


def stop_worker(thread: threading.Thread, stop: threading.Event) -> None:
    stop.set()
    _wake.set()
    thread.join(timeout=2)
