import statistics
from decimal import Decimal

import hq


class UptrendDipBuyer(hq.Strategy):
    name = "Uptrend dip buyer"
    description = (
        "A defensive delivery strategy for Indian stocks on daily bars. It only buys a stock that "
        "trades above its 100-day average, and only after three lower closes in a row: a small "
        "dip inside a rising trend. Each position is small (15% of available cash) and carries a "
        "6% stop-loss and an 8% target; it also sells if the stock closes under its 100-day "
        "average. Long only, held overnight as delivery. It assumes dips in uptrends tend to "
        "bounce; it sits in cash through long downtrends and misses fast rallies that never "
        "pull back."
    )
    markets = ("india",)
    interval = "1d"
    warmup_bars = 101
    PARAMETERS = {
        "trend_period": hq.Param("int", 100, min=20, max=400, label="Trend average (days)"),
        "dip_days": hq.Param("int", 3, min=2, max=10, label="Lower closes in a row"),
        "stop_loss_percent": hq.Param("decimal", Decimal("6"), min="0.5", max=50, label="Stop-loss (%)"),
        "target_percent": hq.Param("decimal", Decimal("8"), min="0.5", max=100, label="Target (%)"),
        "percent_of_cash": hq.Param("decimal", Decimal("15"), min=1, max=100, label="Cash per position (%)"),
    }

    def on_start(self, ctx):
        self.warmup_bars = ctx.params["trend_period"] + 1

    def on_bar(self, ctx):
        p = ctx.params
        for symbol in ctx.symbols:
            closes = ctx.close_series(symbol, p["trend_period"])
            trend = statistics.fmean(closes)
            trades = ctx.open_trades(symbol)
            for trade in trades:
                if trade.stop_price is None:
                    ctx.set_protection(
                        trade.id,
                        stop=trade.entry_price * (1 - p["stop_loss_percent"] / 100),
                        target=trade.entry_price * (1 + p["target_percent"] / 100),
                    )
            if trades and closes[-1] < trend:
                ctx.sell(symbol)
                continue
            recent = closes[-p["dip_days"] - 1 :]
            pulled_back = all(recent[i + 1] < recent[i] for i in range(p["dip_days"]))
            if not trades and closes[-1] > trend and pulled_back:
                ctx.buy(symbol, percent_of_cash=p["percent_of_cash"])
