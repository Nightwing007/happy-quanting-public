"""Shared test helpers (conftest holds fixtures)."""

from sqlalchemy.orm import Session

from app.market_data.base import MarketDataProvider
from app.trading import engine
from app.trading.context import TradingContext


def live(db: Session, provider: MarketDataProvider) -> TradingContext:
    """A context on `engine.get_account(db)`: the first live account, whoever owns it. On a bare
    test DB that is the demo user's; once the `client` fixture has signed up it is `tester`'s."""
    return engine.live_context(db, provider, engine.get_account(db).user_id)
