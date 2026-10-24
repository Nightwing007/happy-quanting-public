import statistics
from decimal import Decimal

import hq


class WeeklyTrendFollower(hq.Strategy):
    name = "Weekly trend follower"
    description = (
        "A patient, long-only trend follower for global equities on weekly bars. It buys when the "
        "10-week average of closes rises above the 40-week average and sells when it falls back "
        "below, so it makes only a few trades a year and lets winners run. It has no stop-loss: "
        "the crossover is the exit, which can give back a good part of a gain before it triggers. "
        "It assumes markets trend for months; in sideways years it takes small losses on false "
        "crossovers, and it lags a plain buy-and-hold in strong bull runs because it waits for "
        "confirmation."
    )
    markets = ("india", "international")
    interval = "1wk"
    warmup_bars = 41
    PARAMETERS = {
        "fast_period": hq.Param("int", 10, min=2, max=100, label="Fast average (weeks)"),
        "slow_period": hq.Param("int", 40, min=3, max=200, label="Slow average (weeks)"),
        "percent_of_cash": hq.Param("decimal", Decimal("90"), min=1, max=100, label="Cash per entry (%)"),
    }

    @classmethod
    def check_params(cls, params):
        if params["fast_period"] >= params["slow_period"]:
            return ["Fast average must be shorter than Slow average."]
        return []

    def on_start(self, ctx):
        self.warmup_bars = ctx.params["slow_period"] + 1

    def on_bar(self, ctx):
        p = ctx.params
        for symbol in ctx.symbols:
            closes = ctx.close_series(symbol, p["slow_period"])
            fast = statistics.fmean(closes[-p["fast_period"] :])
            slow = statistics.fmean(closes)
            held = ctx.position(symbol).quantity
            if held == 0 and fast > slow:
                # Split the cash across the symbols so a second one can still be bought.
                ctx.buy(symbol, percent_of_cash=p["percent_of_cash"] / len(ctx.symbols))
            elif held > 0 and fast < slow:
                ctx.sell(symbol)
