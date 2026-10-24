from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.market_data import get_provider
from app.market_data.base import MarketDataProvider

DbSession = Annotated[Session, Depends(get_db)]
Provider = Annotated[MarketDataProvider, Depends(get_provider)]

# Symbols go in query params, never paths: Yahoo symbols contain ^, = and . (^GSPC, EURUSD=X,
# RELIANCE.NS), which break or get rewritten in URL paths.
SymbolParam = Annotated[
    str,
    Query(min_length=1, max_length=32, description="Yahoo-style symbol, e.g. AAPL, RELIANCE.NS, ^GSPC"),
]


def clean_symbol(symbol: str) -> str:
    # Yahoo symbols are upper-case; "^" and the exchange suffix are untouched by this.
    return symbol.strip().upper()
