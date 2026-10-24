from decimal import Decimal

from app.algos import hq


class BollingerReversion(hq.Strategy):
    name = "Bollinger band reversion"
    description = (
        "Buys when the close falls below the lower Bollinger band and aims for the middle band (the "
        "moving average), where it takes profit; a stop-loss sits below the entry. Long only, daily "
        "bars. It assumes prices return to their average, so it suits range-bound markets and "
        "struggles when a drop is the start of a trend. The target is the middle band at the moment "
        "of entry and does not move afterwards."
    )
    markets = ("india", "international", "crypto")
    interval = "1d"
    warmup_bars = 20
    PARAMETERS = {
        "period": hq.Param(
            "int", 20, min=3, max=200, label="Band period", help="Bars in the moving average."
        ),
        "k": hq.Param(
            "decimal",
            Decimal("2"),
            min="0.5",
            max=4,
            label="Band width (k)",
            help="Standard deviations either side of the average.",
        ),
        "stop_loss_percent": hq.Param(
            "decimal",
            Decimal("4"),
            min="0.5",
            max=50,
            label="Stop-loss (%)",
            help="Distance of the stop-loss below the entry price.",
        ),
        "percent_of_cash": hq.Param(
            "decimal",
            Decimal("50"),
            min=1,
            max=100,
            label="Cash per entry (%)",
            help="Share of available cash spent on each purchase.",
        ),
    }

    def on_start(self, ctx):
        self.warmup_bars = ctx.params["period"]

    def on_bar(self, ctx):
        p = ctx.params
        stop_factor = 1 - p["stop_loss_percent"] / 100
        for symbol in ctx.symbols:
            closes = ctx.close_series(symbol, p["period"])
            mid, _, lower = ctx.indicators.bollinger(closes, p["period"], float(p["k"]))
            price = ctx.price(symbol)
            trades = ctx.open_trades(symbol)
            for trade in trades:
                if trade.stop_price is None:
                    target = Decimal(str(mid[-1]))
                    # A target at or under the price would be refused, so a filled entry that has
                    # already recovered past the middle band just gets its stop.
                    ctx.set_protection(
                        trade.id, stop=price * stop_factor, target=target if target > price else None
                    )
            if not trades and closes[-1] < lower[-1]:
                ctx.buy(symbol, percent_of_cash=p["percent_of_cash"])
