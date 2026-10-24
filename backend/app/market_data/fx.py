from decimal import Decimal

from .base import MarketDataProvider


def get_fx_rate(provider: MarketDataProvider, from_ccy: str, to_ccy: str) -> Decimal:
    if from_ccy == to_ccy:
        return Decimal(1)
    return provider.get_quote(f"{from_ccy}{to_ccy}=X").price
