"""What an engine call acts on: one account, one price source, one clock.

Passing these explicitly (instead of reading a global account and `clock.now()`) is what lets a
sim, a backtest and a live account trade side by side: each has its own account and its own
idea of what time it is, and none can touch another's rows.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.market_data.base import MarketDataProvider
from app.models import Account


@dataclass(frozen=True)
class TradingContext:
    db: Session
    account: Account
    provider: MarketDataProvider
    # Called, not stored as a value, so every read sees the context's current time. Must return
    # an aware UTC datetime.
    now: Callable[[], datetime]
