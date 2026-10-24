from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.orm import Session

from app import auth, clock
from app.db import get_db
from app.market_data import get_provider
from app.market_data.base import MarketDataProvider
from app.models import SimStatus, User
from app.sim import runner
from app.trading import engine
from app.trading.context import TradingContext

DbSession = Annotated[Session, Depends(get_db)]
Provider = Annotated[MarketDataProvider, Depends(get_provider)]


def get_current_user(request: Request, db: DbSession) -> User:
    """The logged-in user, from the session cookie; 401 `not_authenticated` otherwise."""
    user = auth.user_for_token(db, request.cookies.get(auth.COOKIE), clock.now())
    if user is None:
        raise auth.AuthError("Please log in.", "not_authenticated", 401)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_live_context(db: DbSession, provider: Provider, user: CurrentUser) -> TradingContext:
    return engine.live_context(db, provider, user.id)


# Every route trades through this. It is the one place that decides which account and which
# clock a request acts on, so a sim route can hand out a different context without touching
# the routes' bodies.
LiveContext = Annotated[TradingContext, Depends(get_live_context)]


def get_sim_context(session_id: int, db: DbSession, provider: Provider, user: CurrentUser) -> TradingContext:
    """The context of one simulation: its own account, priced from its replayed bars, on the
    clock of its cursor. `session_id` is the path parameter of the routes that use this. Someone
    else's session is a 404, the same as one that does not exist."""
    return runner.build_context(db, runner.get_session(db, session_id, user.id), provider)


def get_open_sim_context(
    session_id: int, db: DbSession, provider: Provider, user: CurrentUser
) -> TradingContext:
    """Like `get_sim_context`, for routes that add an order or protection. A finished session's
    clock never moves again, so an order there could only sit forever: refused with a sentence."""
    session = runner.get_session(db, session_id, user.id)
    if session.status == SimStatus.FINISHED:
        raise runner.SimFinished(
            "This simulation has finished, so no new orders can be placed. Reset it to play again."
        )
    return runner.build_context(db, session, provider)


# Symbols go in query params, never paths: Yahoo symbols contain ^, = and . (^GSPC, EURUSD=X,
# RELIANCE.NS), which break or get rewritten in URL paths.
SymbolParam = Annotated[
    str,
    Query(min_length=1, max_length=32, description="Yahoo-style symbol, e.g. AAPL, RELIANCE.NS, ^GSPC"),
]


def clean_symbol(symbol: str) -> str:
    # Yahoo symbols are upper-case; "^" and the exchange suffix are untouched by this.
    return symbol.strip().upper()
