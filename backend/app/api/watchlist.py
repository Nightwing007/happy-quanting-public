from fastapi import APIRouter, HTTPException, Response

from app.api.deps import LiveContext, SymbolParam, clean_symbol
from app.market_data.base import Quote
from app.models import WatchlistItem
from app.schemas import QuoteOut, WatchlistIn, WatchlistItemOut
from app.trading import watchlist

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _item_out(item: WatchlistItem, quote: Quote | None) -> WatchlistItemOut:
    live = QuoteOut.from_quote(quote) if quote else None
    return WatchlistItemOut(
        symbol=item.symbol,
        name=item.name,
        created_at=item.created_at,
        price=live.price if live else None,
        change=live.change if live else None,
        change_percent=live.change_percent if live else None,
        currency=live.currency if live else None,
    )


@router.get("", response_model=list[WatchlistItemOut])
def list_watchlist(ctx: LiveContext):
    return [_item_out(item, quote) for item, quote in watchlist.list_items(ctx)]


@router.post("", response_model=WatchlistItemOut)
def add_to_watchlist(body: WatchlistIn, ctx: LiveContext):
    item, quote = watchlist.add_item(ctx, clean_symbol(body.symbol))
    return _item_out(item, quote)


@router.delete("", status_code=204)
def remove_from_watchlist(ctx: LiveContext, symbol: SymbolParam):
    symbol = clean_symbol(symbol)
    if not watchlist.remove_item(ctx, symbol):
        raise HTTPException(status_code=404, detail=f"{symbol} is not on your watchlist.")
    return Response(status_code=204)
