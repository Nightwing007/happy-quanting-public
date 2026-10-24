"""What one tick of the clock does to an account.

The live background loop and the sim runner both call `run_tick`, so a replayed minute does
exactly what a real one does, in the same order. The order matters: protection fires before the
square-off so a stop that has been hit is reported as a stop, and financing comes last.
"""

import logging
from collections.abc import Callable

from app.trading.context import TradingContext
from app.trading.engine import (
    accrue_financing,
    fill_open_orders,
    square_off_due,
    trigger_protected_trades,
)

logger = logging.getLogger(__name__)

TICK_STEPS: tuple[tuple[str, Callable[[TradingContext], int | list]], ...] = (
    ("Filling open orders", fill_open_orders),
    ("Firing stop-losses and targets", trigger_protected_trades),
    ("Squaring off intraday shorts", square_off_due),
    ("Charging borrow and funding", accrue_financing),
)


def run_tick(ctx: TradingContext) -> None:
    for name, step in TICK_STEPS:
        # Each step fails on its own, so a quote that won't load for one never stops the others.
        try:
            result = step(ctx)
            if result:
                logger.info("%s: %s", name, result if isinstance(result, int) else len(result))
        except Exception:  # noqa: BLE001 - one failing step must not stop the rest
            ctx.db.rollback()
            logger.exception("%s failed; will retry", name)
