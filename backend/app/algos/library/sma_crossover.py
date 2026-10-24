from decimal import Decimal

from app.algos import hq


class SmaCrossover(hq.Strategy):
    name = "SMA crossover"
    description = (
        "A trend follower. It buys when the fast moving average of the close rises above the slow "
        "one and sells everything when it falls back below. Long only, daily bars. It earns in "
        "long, smooth trends and gives money back in sideways markets, where the averages cross "
        "back and forth (each round trip also pays full charges). Orders fill at the open of the "
        "day after the crossover."
    )
    markets = ("india", "international", "crypto")
    interval = "1d"
    warmup_bars = 31
    PARAMETERS = {
        "fast_period": hq.Param(
            "int", 10, min=2, max=100, label="Fast period", help="Bars in the fast average."
        ),
        "slow_period": hq.Param(
            "int", 30, min=3, max=300, label="Slow period", help="Bars in the slow average."
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
        if params["fast_period"] >= params["slow_period"]:
            return ["Fast period must be smaller than Slow period, or the two averages never cross."]
        return []

    def on_start(self, ctx):
        # One extra bar so the previous bar's averages exist to compare with.
        self.warmup_bars = ctx.params["slow_period"] + 1

    def on_bar(self, ctx):
        fast_n, slow_n = ctx.params["fast_period"], ctx.params["slow_period"]
        for symbol in ctx.symbols:
            closes = ctx.close_series(symbol, slow_n + 1)
            fast = ctx.indicators.sma(closes, fast_n)
            slow = ctx.indicators.sma(closes, slow_n)
            crossed_up = fast[-2] <= slow[-2] and fast[-1] > slow[-1]
            crossed_down = fast[-2] >= slow[-2] and fast[-1] < slow[-1]
            held = ctx.position(symbol).quantity
            if crossed_up and held == 0:
                ctx.buy(symbol, percent_of_cash=ctx.params["percent_of_cash"])
            elif crossed_down and held > 0:
                ctx.sell(symbol)
