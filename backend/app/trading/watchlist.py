"""Watchlist operations. Like the engine, writes commit before returning."""

from sqlalchemy import select

from app.market_data import get_quotes
from app.market_data.base import Quote
from app.models import WatchlistItem
from app.trading.context import TradingContext


def list_items(ctx: TradingContext) -> list[tuple[WatchlistItem, Quote | None]]:
    items = ctx.db.scalars(
        select(WatchlistItem).where(WatchlistItem.account_id == ctx.account.id).order_by(WatchlistItem.id)
    ).all()
    quotes = get_quotes(ctx.provider, [i.symbol for i in items])
    return [(i, quotes.get(i.symbol)) for i in items]


def add_item(ctx: TradingContext, symbol: str) -> tuple[WatchlistItem, Quote]:
    """Add `symbol`, or return the existing item. Raises SymbolNotFound for an unknown symbol."""
    quote = ctx.provider.get_quote(symbol)  # also validates the symbol
    item = ctx.db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.account_id == ctx.account.id, WatchlistItem.symbol == quote.symbol
        )
    )
    if item is None:
        item = WatchlistItem(
            account_id=ctx.account.id, symbol=quote.symbol, name=quote.name, created_at=ctx.now()
        )
        ctx.db.add(item)
        ctx.db.commit()
    return item, quote


def remove_item(ctx: TradingContext, symbol: str) -> bool:
    item = ctx.db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.account_id == ctx.account.id, WatchlistItem.symbol == symbol
        )
    )
    if item is None:
        return False
    ctx.db.delete(item)
    ctx.db.commit()
    return True
