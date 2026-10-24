class TradingError(Exception):
    """A problem with an order, worded for the person who placed it. `code` is the stable
    snake_case name clients branch on; the message is for people and may be reworded."""

    code = "trading_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InsufficientFunds(TradingError):
    code = "insufficient_funds"


class InsufficientShares(TradingError):
    code = "insufficient_shares"


class InvalidOrder(TradingError):
    code = "invalid_order"


class NotTradable(TradingError):
    code = "not_tradable"


class OrderNotOpen(TradingError):
    code = "order_not_open"


class OrderNotFound(TradingError):
    code = "order_not_found"


class UnsupportedMarket(TradingError):
    """The symbol's exchange is one whose costs we don't model."""

    code = "unsupported_market"


class BrokerNotAvailable(TradingError):
    """The broker chosen in Settings doesn't offer this market (or doesn't exist)."""

    code = "broker_unavailable"


class InvalidBroker(TradingError):
    """A broker choice that isn't a broker of that segment."""

    code = "invalid_broker"


class ShortNotAllowed(TradingError):
    """A sell that would open a short the market or the moment doesn't allow. The planner picks
    the subclass, so nothing downstream has to read the message to know what went wrong."""

    code = "short_not_allowed"


class ShortNotOffered(ShortNotAllowed):
    """The market has no short-selling rule at all."""

    code = "short_not_offered"


class ShortMarketClosed(ShortNotAllowed):
    """An intraday short can't wait for the open: there is no after-market order for one."""

    code = "short_market_closed"


class ShortQuantityInvalid(ShortNotAllowed, InvalidOrder):
    """The short part of a sell isn't a multiple of the smallest quantity that can be borrowed."""

    code = "short_quantity_invalid"


class TradeNotFound(TradingError):
    code = "trade_not_found"


class TradeNotOpen(TradingError):
    code = "trade_not_open"


class ProtectionInvalid(TradingError):
    """A stop-loss or target on the wrong side of the price, or not a usable price. `fields`
    maps "stop_price" / "target_price" to the sentence for that field, so a form can show each
    beside its input."""

    code = "protection_invalid"

    def __init__(self, fields: dict[str, str]):
        super().__init__(" ".join(fields.values()))
        self.fields = fields
