"""The task that plays running sessions at their speed."""

import asyncio
import logging
import time

from sqlalchemy import select

from app.db import SessionLocal
from app.market_data import get_provider
from app.models import SimSession, SimStatus
from app.sim.runner import advance

logger = logging.getLogger(__name__)

TICK_SECONDS = 1.0


def drive_once() -> None:
    """Advance every running session by its speed (bars per second, over one second). Runs in a
    worker thread, so it opens its own database session."""
    with SessionLocal() as db:
        provider = get_provider()
        ids = list(db.scalars(select(SimSession.id).where(SimSession.status == SimStatus.RUNNING)))
        for session_id in ids:
            try:
                session = db.get(SimSession, session_id)
                if session is not None:
                    advance(db, session, session.speed, provider)
            except Exception:  # noqa: BLE001 - one bad session must not stop the others
                db.rollback()
                logger.exception("Simulation %d failed to advance; will retry", session_id)


async def drive_loop() -> None:
    while True:
        started = time.monotonic()
        try:
            await asyncio.to_thread(drive_once)
        except Exception:  # noqa: BLE001 - the loop must survive any single failure
            logger.exception("Simulation driver tick failed; will retry")
        # Sleep what is left of the second, so a slow tick does not also add a pause.
        await asyncio.sleep(max(0.0, TICK_SECONDS - (time.monotonic() - started)))
