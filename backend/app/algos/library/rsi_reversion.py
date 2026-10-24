from decimal import Decimal

from app.algos import hq


class RsiReversion(hq.Strategy):
    name = "RSI mean reversion"
    description = (
        "Buys a dip and sells the bounce. It buys when the RSI falls below the oversold level, puts "
        "a stop-loss under the entry, and sells when the RSI recovers to the exit level. Long only, "
        "daily bars. It assumes prices snap back after sharp drops, which holds for steady markets "
        "and fails in a real downtrend: the stop-loss is what limits that damage, at the cost of "
        "being stopped out before some recoveries."
    )
    markets = ("india", "international", "crypto")
    interval = "1d"
    warmup_bars = 15
    PARAMETERS = {
        "period": hq.Param("int", 14, min=2, max=100, label="RSI period", help="Bars in the RSI."),
        "oversold": hq.Param(
            "int", 30, min=1, max=50, label="Oversold level", help="Buy when the RSI is below this."
        ),
        "exit_level": hq.Param(
            "int", 55, min=30, max=99, label="Exit level", help="Sell when the RSI is above this."
        ),
        "stop_loss_percent": hq.Param(
            "decimal",
            Decimal("5"),
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

    @classmethod
    def check_params(cls, params):
        if params["exit_level"] <= params["oversold"]:
            return ["Exit level must be above the Oversold level."]
        return []

    def on_start(self, ctx):
        self.warmup_bars = ctx.params["period"] + 1

    def on_bar(self, ctx):
        p = ctx.params
        stop_factor = 1 - p["stop_loss_percent"] / 100
        for symbol in ctx.symbols:
            value = ctx.indicators.rsi(ctx.close_series(symbol, p["period"] * 4), p["period"])[-1]
            trades = ctx.open_trades(symbol)
            for trade in trades:
                # A fresh entry filled after the last bar's decision: protect it at once.
                if trade.stop_price is None:
                    ctx.set_protection(trade.id, stop=ctx.price(symbol) * stop_factor)
            if not trades and value < p["oversold"]:
                ctx.buy(symbol, percent_of_cash=p["percent_of_cash"])
            elif trades and value > p["exit_level"]:
                ctx.sell(symbol)
