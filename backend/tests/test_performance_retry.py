"""A performance window that failed for want of market data is tried again with backoff; one that
failed because of the strategy is not. The public note never shows the raw error."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.market_data.base import DataUnavailable, SymbolNotFound
from app.market_data.fake import FakeProvider
from app.marketplace import performance
from app.models import AlgoListing, ListingPerformance
from tests import test_marketplace
from tests.test_marketplace import create, short_windows  # noqa: F401 - autouse fixture

canned_results = test_marketplace.canned_results

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch):
    state = {"now": NOW}
    monkeypatch.setattr(clock, "now", lambda: state["now"])
    return state


def published(client: TestClient, db: Session) -> AlgoListing:
    listing = db.get(AlgoListing, create(client)["id"])
    listing.status = "published"
    db.commit()
    performance.queue_performance(db, listing)
    return listing


def rows(db: Session) -> list[ListingPerformance]:
    db.expire_all()
    return list(db.scalars(select(ListingPerformance).order_by(ListingPerformance.id)))


def fail_with(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def boom(*a, **kw):
        raise error

    monkeypatch.setattr(performance, "run_backtest", boom)


def test_transient_failure_is_requeued_with_backoff_and_succeeds_on_retry(
    client: TestClient, db: Session, fake_provider: FakeProvider, monkeypatch, frozen_clock, canned_results
):
    listing = published(client, db)
    fail_with(monkeypatch, DataUnavailable())
    assert performance.run_next_queued(db, fake_provider) is True
    first = rows(db)
    assert [r.status for r in first] == ["failed"] * 3
    assert [r.attempts for r in first] == [1] * 3
    assert all(r.retry_after == NOW + timedelta(minutes=10) for r in first)

    # Not due yet: nothing is picked up.
    assert performance.run_next_queued(db, fake_provider) is False

    # Due: failed again, so the pause grows (30 min, then 2 h).
    frozen_clock["now"] = NOW + timedelta(minutes=11)
    assert performance.run_next_queued(db, fake_provider) is True
    second = rows(db)
    assert [r.attempts for r in second] == [2] * 3
    assert second[0].retry_after == NOW + timedelta(minutes=11) + timedelta(minutes=30)

    # Data is back: the retry succeeds.
    monkeypatch.setattr(performance, "run_backtest", lambda *a, **kw: canned_results)
    frozen_clock["now"] = NOW + timedelta(hours=1)
    assert performance.run_next_queued(db, fake_provider) is True
    done = rows(db)
    assert {r.status for r in done} == {"done"} and all(r.retry_after is None for r in done)
    assert listing.id  # the same listing throughout


def test_retries_stop_after_five_attempts(
    client: TestClient, db: Session, fake_provider: FakeProvider, monkeypatch, frozen_clock
):
    published(client, db)
    fail_with(monkeypatch, SymbolNotFound("BTC-USD"))
    for _ in range(performance.MAX_ATTEMPTS):
        assert performance.run_next_queued(db, fake_provider) is True
        frozen_clock["now"] += timedelta(hours=3)
    final = rows(db)
    assert [r.attempts for r in final] == [performance.MAX_ATTEMPTS] * 3
    assert all(r.status == "failed" and r.retry_after is None for r in final)
    assert performance.run_next_queued(db, fake_provider) is False
    # Out of retries: the real reason is shown again.
    assert not performance.is_waiting_to_retry(final[0])


def test_a_retry_leaves_finished_windows_alone(
    client: TestClient, db: Session, fake_provider: FakeProvider, monkeypatch, frozen_clock, canned_results
):
    published(client, db)
    monkeypatch.setattr(performance, "run_backtest", lambda *a, **kw: canned_results)
    performance.run_next_queued(db, fake_provider)
    one = rows(db)[0]
    stamp = one.computed_at
    one.status, one.retry_after, one.attempts = "failed", NOW, 1
    db.commit()
    asked = []
    monkeypatch.setattr(
        performance, "run_backtest", lambda *a, **kw: asked.append(kw["start"]) or canned_results
    )
    frozen_clock["now"] = NOW + timedelta(minutes=1)
    assert performance.run_next_queued(db, fake_provider) is True
    assert len(asked) == 1
    assert {r.status for r in rows(db)} == {"done"}
    assert rows(db)[1].computed_at == stamp  # untouched


def test_a_strategy_error_is_not_retried(
    client: TestClient, db: Session, fake_provider: FakeProvider, monkeypatch, frozen_clock
):
    published(client, db)
    fail_with(monkeypatch, ValueError("division by zero in on_bar"))
    assert performance.run_next_queued(db, fake_provider) is True
    failed = rows(db)
    assert all(r.status == "failed" and r.retry_after is None for r in failed)
    assert all(r.attempts == performance.MAX_ATTEMPTS for r in failed)
    frozen_clock["now"] += timedelta(days=1)
    assert performance.run_next_queued(db, fake_provider) is False
    performance.requeue_retryable_failures(db)  # a restart does not revive it either
    assert {r.status for r in rows(db)} == {"failed"}


def test_startup_requeues_retryable_failed_windows(
    client: TestClient, db: Session, fake_provider: FakeProvider
):
    published(client, db)
    a, b, c = rows(db)
    # a: failed before retries existed (0 attempts); b: waiting on a pause; c: out of attempts.
    a.status, a.note = "failed", "No market data found for 'BTC-USD'."
    b.status, b.attempts, b.retry_after = "failed", 2, NOW + timedelta(hours=1)
    c.status, c.attempts = "failed", performance.MAX_ATTEMPTS
    db.commit()
    performance.requeue_retryable_failures(db)
    a, b, c = rows(db)
    assert (a.status, b.status, c.status) == ("queued", "queued", "failed")
    assert a.retry_after is None and b.retry_after is None


def test_public_note_for_a_waiting_window_has_no_error_text(
    client: TestClient, db: Session, fake_provider: FakeProvider, monkeypatch
):
    listing = published(client, db)
    fail_with(monkeypatch, SymbolNotFound("BTC-USD"))
    performance.run_next_queued(db, fake_provider)
    windows = client.get(f"/api/marketplace/listings/{listing.id}").json()["performance"]
    assert [w["status"] for w in windows] == ["failed"] * 3
    assert {w["note"] for w in windows} == {
        "Measuring again soon — market data was temporarily unavailable."
    }
    # The stored reason is kept for the logs, not shown.
    assert "BTC-USD" in rows(db)[0].note
