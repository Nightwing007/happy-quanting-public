from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.market_data import get_provider
from app.market_data.base import MarketDataProvider
from app.sim import runner
from app.trading import engine
from app.trading.context import TradingContext

DbSession = Annotated[Session, Depends(get_db)]
Provider = Annotated[MarketDataProvider, Depends(get_provider)]


def get_live_context(db: DbSession, provider: Provider) -> TradingContext:
    return engine.live_context(db, provider)


# Every route trades through this. It is the one place that decides which account and which
# clock a request acts on, so a sim route can hand out a different context without touching
# the routes' bodies.
LiveContext = Annotated[TradingContext, Depends(get_live_context)]

def get_sim_context(session_id: int, db: DbSession, provider: Provider) -> TradingContext:
    """The context of one simulation: its own account, priced from its replayed bars, on the
    clock of its cursor. `session_id` is the path parameter of the routes that use this."""
    return runner.build_context(db, runner.get_session(db, session_id), provider)


# Symbols go in query params, never paths: Yahoo symbols contain ^, = and . (^GSPC, EURUSD=X,
# RELIANCE.NS), which break or get rewritten in URL paths.
SymbolParam = Annotated[
    str,
    Query(min_length=1, max_length=32, description="Yahoo-style symbol, e.g. AAPL, RELIANCE.NS, ^GSPC"),
]


def clean_symbol(symbol: str) -> str:
    # Yahoo symbols are upper-case; "^" and the exchange suffix are untouched by this.
    return symbol.strip().upper()
