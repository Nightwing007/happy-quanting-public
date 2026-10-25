"""Backtests as background jobs: queued by the API, run one at a time on a worker thread.

One at a time because a run holds the CPU and the SQLite write lock for seconds; two at once would
only make both slower. Tests call `run_backtest_job` directly and never start the thread.
"""

import logging
import threading
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
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
from app.algos.sandbox import SandboxError, UserCodeError, load_strategy
from app.config import get_settings
from app.db import SessionLocal
from app.hosted import refuse_code, refuse_saved_code
from app.market_data import get_provider
from app.market_data.base import MarketDataError, MarketDataProvider
from app.models import Backtest, BacktestStatus, UserAlgo
from app.schemas import BacktestIn, BacktestResultsOut
from app.trading.errors import TradingError

logger = logging.getLogger(__name__)

IDLE_SECONDS = 2.0
_wake = threading.Event()


def wake() -> None:
    """Tell the worker there is something new to do (a backtest, or a listing to measure)."""
    _wake.set()


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
    source = body.source
    if source is not None:
        refuse_code()
        if body.strategy is not None or body.algo_id is not None:
            raise BacktestError("Give one of: a library key, a saved algorithm, or code.")
        return _queue_source(db, provider, body, source, cash, owner_user_id, today)
    if body.algo_id is not None:
        saved = db.get(UserAlgo, body.algo_id)
        if saved is None or saved.owner_user_id != owner_user_id:
            raise BacktestNotFound(f"There is no saved algorithm {body.algo_id}.")
        if saved.source is not None:  # editor code runs like an uploaded `source`
            refuse_saved_code(saved)
            merged = body.model_copy(update={"params": {**saved.params, **body.params}})
            return _queue_source(db, provider, merged, saved.source, cash, owner_user_id, today)
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


def _queue_source(
    db: Session, provider: MarketDataProvider, body: BacktestIn, source: str, cash: Decimal,
    owner_user_id: int | None, today: date | None,
) -> Backtest:
    """Queue a backtest of the requester's uploaded code. The code is stored on the row (never in a
    response) for the worker; a break of the code rules is refused here with every problem."""
    from app.marketplace.listings import check_source  # imported here: listings reads this module's package

    check_source(source)  # raises MarketplaceError("invalid_source") carrying the problems
    strategy = load_strategy(source)  # starts nothing until a hook runs
    try:
        req = check_request(
            db, provider, strategy_key=strategy.name, strategy_cls=strategy, params=body.params,  # type: ignore[arg-type]
            symbols=body.symbols, interval=body.interval, start=body.start_date, end=body.end_date,
            starting_cash=cash, brokers=body.brokers, today=today,
        )  # fmt: skip
    finally:
        strategy.close()
    row = Backtest(
        owner_user_id=owner_user_id, strategy_key=strategy.name, source=source,
        params={name: _plain(v) for name, v in req.values.items()}, symbols=req.names,
        interval=body.interval, start_date=body.start_date, end_date=body.end_date, starting_cash=cash,
        account_currency=get_settings().base_currency, brokers=req.brokers, status=BacktestStatus.QUEUED,
        progress=0, created_at=clock.now(),
    )  # fmt: skip
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
    get_backtest(db, backtest_id, owner_user_id)
    # One statement, so a worker that starts the job between the check and the delete can't have
    # its row pulled from under it.
    gone = db.execute(
        delete(Backtest).where(Backtest.id == backtest_id, Backtest.status != BacktestStatus.RUNNING)
    )
    db.commit()
    if gone.rowcount == 0:
        db.expire_all()
        if db.get(Backtest, backtest_id) is not None:
            raise BacktestConflict("This backtest is running. Delete it once it has finished.")
        raise BacktestNotFound(f"There is no backtest {backtest_id}.")


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
    row = db.get(Backtest, backtest_id)  # the worker runs every owner's jobs
    if row is None:  # deleted between being picked and starting: nothing to run, not an error
        return
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
            db, provider, strategy_key=row.strategy_key, source=row.source, params=row.params,
            symbols=row.symbols, interval=row.interval, start=row.start_date, end=row.end_date,
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
    from app.badges import award as badge_award
    from app.marketplace import performance  # imported here: performance uses this module's helpers

    try:
        with SessionLocal() as db:
            _recover(db)
            performance.recover_interrupted(db)
            performance.requeue_retryable_failures(db)
    except Exception:  # noqa: BLE001 - the worker must come up regardless
        logger.exception("Backtest recovery failed")
    try:
        with SessionLocal() as db:
            badge_award.backfill_all(db, clock.now())  # past activity, once: no toast per badge
    except Exception:  # noqa: BLE001 - badges are not worth a failed start
        logger.exception("Badge backfill failed")
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                job = _next_queued(db)
                if job is not None:
                    run_backtest_job(db, job)
                    continue
                if performance.run_next_queued(db):
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
