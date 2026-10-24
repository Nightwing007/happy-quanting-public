"""A listing's track record, measured by the server on standard windows.

The creator picks the test symbols; the server backtests the listing on them over the last 3
months, 1 year and 3 years (where the interval's history reaches) with the app's default
brokers and starting cash. Only totals and curves are kept: per-trade prices, orders and logs
could reveal the entry rules, so they are dropped before anything is stored.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import clock
from app.algos import jobs
from app.algos.backtest import run_backtest
from app.config import get_settings
from app.market_data import get_provider
from app.market_data.base import MarketDataError, MarketDataProvider
from app.market_data.history import LIMITS, earliest_date, today_utc
from app.models import AlgoListing, ListingPerformance, PerformanceStatus
from app.schemas import (
    BacktestResultsOut,
    PerformanceBuyHoldOut,
    PerformanceDrawdownOut,
    PerformanceMetricsOut,
    PerformancePointOut,
    PerformanceResultsOut,
)
from app.trading import brokers as broker_data

logger = logging.getLogger(__name__)

# window -> (days back from today, how it reads in a sentence)
WINDOWS: dict[str, tuple[int, str]] = {
    "3mo": (91, "3-month"),
    "1y": (365, "1-year"),
    "3y": (1095, "3-year"),
}
HEADLINE_ORDER = ("1y", "3y", "3mo")

# A window that failed for want of market data is tried again after these pauses (the last one
# repeats) until MAX_ATTEMPTS failures; anything else (a strategy error, too few bars) is final.
MAX_ATTEMPTS = 5
RETRY_BACKOFF = (timedelta(minutes=10), timedelta(minutes=30), timedelta(hours=2))
WAITING_NOTE = "Measuring again soon — market data was temporarily unavailable."


def window_range(window: str, today: date) -> tuple[date, date]:
    return today - timedelta(days=WINDOWS[window][0]), today


def performance_only(results: BacktestResultsOut) -> PerformanceResultsOut:
    """The part of a backtest a buyer may see. Built field by field, so nothing a backtest later
    gains (trades, orders, logs, settings, the strategy's name) can slip into a listing."""
    m = results.metrics
    hold = results.buy_and_hold
    return PerformanceResultsOut(
        account_currency=results.account_currency,
        metrics=PerformanceMetricsOut(
            starting_cash=m.starting_cash,
            final_equity=m.final_equity,
            total_return_pct=m.total_return_pct,
            cagr_pct=m.cagr_pct,
            cagr_note=m.cagr_note,
            max_drawdown_pct=m.max_drawdown_pct,
            sharpe=m.sharpe,
            sharpe_note=m.sharpe_note,
            win_rate_pct=m.win_rate_pct,
            profit_factor=m.profit_factor,
            trade_count=m.trades_closed,
            total_charges=m.total_charges,
            exposure_pct=m.exposure_pct,
        ),
        equity_curve=[
            PerformancePointOut(at=p.at, equity=p.equity, buy_hold_equity=p.buy_hold_equity)
            for p in results.equity_curve
        ],
        drawdown=[
            PerformanceDrawdownOut(at=d.at, strategy_pct=d.strategy_pct, buy_hold_pct=d.buy_hold_pct)
            for d in results.drawdown
        ],
        buy_and_hold=PerformanceBuyHoldOut(
            final_equity=hold.final_equity,
            total_return_pct=hold.total_return_pct,
            cagr_pct=hold.cagr_pct,
            max_drawdown_pct=hold.max_drawdown_pct,
            total_charges=hold.total_charges,
        ),
    )


def queue_performance(db: Session, listing: AlgoListing) -> None:
    """Forget the old measurements and queue one row per window for the current version."""
    today = today_utc()
    db.execute(delete(ListingPerformance).where(ListingPerformance.listing_id == listing.id))
    for window in WINDOWS:
        start, end = window_range(window, today)
        db.add(
            ListingPerformance(
                listing_id=listing.id,
                window=window,
                version=listing.version,
                start=start,
                end=end,
                status=PerformanceStatus.QUEUED,
            )
        )
    db.commit()
    jobs.wake()


def _row(db: Session, listing: AlgoListing, window: str, start: date, end: date) -> ListingPerformance:
    row = db.scalar(
        select(ListingPerformance).where(
            ListingPerformance.listing_id == listing.id,
            ListingPerformance.window == window,
            ListingPerformance.version == listing.version,
        )
    )
    if row is None:
        row = ListingPerformance(listing_id=listing.id, window=window, version=listing.version)
        db.add(row)
    row.start, row.end = start, end
    return row


def _unavailable_note(interval: str, window: str, today: date) -> str | None:
    """Why `interval` can't reach back far enough for `window`, or None when it can."""
    start, _ = window_range(window, today)
    earliest = earliest_date(interval, today)
    if earliest is None or start >= earliest:
        return None
    return (
        f"{interval} data only goes back about {LIMITS[interval].stated_days} days, "
        f"so a {WINDOWS[window][1]} result can't be measured."
    )


def is_retryable(why: Exception) -> bool:
    """A data failure may pass on its own; a strategy error or too little history never will."""
    return isinstance(why, MarketDataError | ConnectionError | TimeoutError)


def is_waiting_to_retry(row: ListingPerformance) -> bool:
    return row.status == PerformanceStatus.FAILED and (row.attempts or 0) < MAX_ATTEMPTS


def compute_performance(
    db: Session,
    provider: MarketDataProvider,
    listing: AlgoListing,
    today: date | None = None,
    *,
    only_queued: bool = False,
) -> list[ListingPerformance]:
    """Backtest the listing on its test symbols for every window and store each outcome on its
    row. A window the history can't cover is "unavailable" with the reason; a run that fails is
    "failed" with a sentence. Neither stops the other windows. With `only_queued`, windows that already
    finished (or failed) are left alone, so a retry doesn't redo what worked."""
    today = today or today_utc()
    settings = get_settings()
    rows = []
    for window in WINDOWS:
        start, end = window_range(window, today)
        if only_queued:
            before = db.scalar(
                select(ListingPerformance).where(
                    ListingPerformance.listing_id == listing.id,
                    ListingPerformance.window == window,
                    ListingPerformance.version == listing.version,
                )
            )
            if before is not None and before.status != PerformanceStatus.QUEUED:
                rows.append(before)
                continue
        row = _row(db, listing, window, start, end)
        row.results, row.note, row.computed_at, row.retry_after = None, None, None, None
        rows.append(row)
        note = _unavailable_note(listing.interval, window, today)
        if note is not None:
            row.status, row.note, row.computed_at = PerformanceStatus.UNAVAILABLE, note, clock.now()
            db.commit()
            continue
        row.status = PerformanceStatus.RUNNING
        db.commit()
        try:
            results = run_backtest(
                db, provider, strategy_key=listing.strategy_key, source=listing.source, params=listing.params,
                symbols=list(listing.test_symbols), interval=listing.interval, start=start, end=end,
                starting_cash=settings.starting_cash, brokers=dict(broker_data.DEFAULT_BROKERS),
                account_currency=settings.base_currency, today=today, owner_user_id=listing.owner_user_id,
            )  # fmt: skip
            row.results = performance_only(results).model_dump(mode="json")
            row.status = PerformanceStatus.DONE
        except Exception as why:  # noqa: BLE001 - whatever went wrong is what the creator reads
            db.rollback()
            row.results, row.status, row.note = None, PerformanceStatus.FAILED, jobs._failure_text(why)
            _schedule_retry(row, why)
        row.computed_at = clock.now()
        db.commit()
    return rows


def _schedule_retry(row: ListingPerformance, why: Exception) -> None:
    attempts = (row.attempts or 0) + 1
    if not is_retryable(why) or attempts >= MAX_ATTEMPTS:
        row.attempts, row.retry_after = MAX_ATTEMPTS if not is_retryable(why) else attempts, None
        return
    row.attempts = attempts
    row.retry_after = clock.now() + RETRY_BACKOFF[min(attempts, len(RETRY_BACKOFF)) - 1]


def requeue_due(db: Session) -> None:
    """Failed windows whose pause is over go back in the queue."""
    now = clock.now()
    for row in db.scalars(
        select(ListingPerformance).where(
            ListingPerformance.status == PerformanceStatus.FAILED,
            ListingPerformance.retry_after.is_not(None),
            ListingPerformance.retry_after <= now,
            ListingPerformance.attempts < MAX_ATTEMPTS,
        )
    ):
        row.status, row.retry_after = PerformanceStatus.QUEUED, None
    db.commit()


def run_next_queued(db: Session, provider: MarketDataProvider | None = None) -> bool:
    """Measure one listing that has queued windows. The worker calls this when no backtest waits."""
    requeue_due(db)
    listing_id = db.scalar(
        select(ListingPerformance.listing_id)
        .where(ListingPerformance.status == PerformanceStatus.QUEUED)
        .order_by(ListingPerformance.id)
        .limit(1)
    )
    if listing_id is None:
        return False
    listing = db.get(AlgoListing, listing_id)  # the worker serves every owner's listings
    if listing is None:
        return True
    compute_performance(db, provider or get_provider(), listing, only_queued=True)
    return True


def recover_interrupted(db: Session) -> None:
    """At start-up nothing is running, so a window still marked running was cut off by a restart."""
    for row in db.scalars(
        select(ListingPerformance).where(ListingPerformance.status == PerformanceStatus.RUNNING)
    ):
        row.status = PerformanceStatus.QUEUED
    db.commit()


def requeue_retryable_failures(db: Session) -> None:
    """At start-up, every failed window that retrying could still fix is queued again at once,
    including ones that failed before retries existed (they have 0 attempts)."""
    for row in db.scalars(
        select(ListingPerformance).where(
            ListingPerformance.status == PerformanceStatus.FAILED,
            ListingPerformance.attempts < MAX_ATTEMPTS,
        )
    ):
        row.status, row.retry_after = PerformanceStatus.QUEUED, None
    db.commit()
