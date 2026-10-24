"""Watchlist operations. Like the engine, writes commit before returning."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.market_data import get_quotes
from app.market_data.base import MarketDataProvider, Quote
from app.models import WatchlistItem
from app.trading.engine import get_account


def list_items(db: Session, provider: MarketDataProvider) -> list[tuple[WatchlistItem, Quote | None]]:
    account = get_account(db)
    items = db.scalars(
        select(WatchlistItem).where(WatchlistItem.account_id == account.id).order_by(WatchlistItem.id)
    ).all()
    quotes = get_quotes(provider, [i.symbol for i in items])
    return [(i, quotes.get(i.symbol)) for i in items]


def add_item(db: Session, provider: MarketDataProvider, symbol: str) -> tuple[WatchlistItem, Quote]:
    """Add `symbol`, or return the existing item. Raises SymbolNotFound for an unknown symbol."""
    account = get_account(db)
    quote = provider.get_quote(symbol)  # also validates the symbol
    item = db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.account_id == account.id, WatchlistItem.symbol == quote.symbol
        )
    )
    if item is None:
        item = WatchlistItem(
            account_id=account.id, symbol=quote.symbol, name=quote.name, created_at=clock.now()
        )
        db.add(item)
        db.commit()
    return item, quote


def remove_item(db: Session, symbol: str) -> bool:
    account = get_account(db)
    item = db.scalar(
        select(WatchlistItem).where(WatchlistItem.account_id == account.id, WatchlistItem.symbol == symbol)
    )
    if item is None:
        return False
    db.delete(item)
    db.commit()
    return True
