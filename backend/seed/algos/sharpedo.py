from decimal import Decimal

import hq


class OversoldAmbush(hq.Strategy):
    name = "Oversold ambush"
    description = (
        "A contrarian mean-reversion strategy for US and Indian stocks on daily bars. It waits "
        "for a stock to be both oversold (RSI under 30) and stretched below its lower Bollinger "
        "band, buys, and takes profit at the middle band; a 5% stop-loss limits the damage. Long "
        "only, one position per stock, so it often sits in cash. It assumes sharp drops snap back "
        "toward the average; in a real breakdown it keeps catching falling knives and takes "
        "repeated stop-losses. The target is the middle band at the moment of entry."
    )
    markets = ("india", "international")
    interval = "1d"
    warmup_bars = 21
    PARAMETERS = {
        "rsi_period": hq.Param("int", 14, min=2, max=100, label="RSI period"),
        "rsi_below": hq.Param("int", 30, min=5, max=50, label="Buy when RSI is below"),
        "band_period": hq.Param("int", 20, min=3, max=200, label="Band period"),
        "band_k": hq.Param("decimal", Decimal("2"), min="0.5", max=4, label="Band width (k)"),
        "stop_loss_percent": hq.Param("decimal", Decimal("5"), min="0.5", max=50, label="Stop-loss (%)"),
        "percent_of_cash": hq.Param("decimal", Decimal("40"), min=1, max=100, label="Cash per entry (%)"),
    }

    def on_start(self, ctx):
        self.warmup_bars = max(ctx.params["rsi_period"], ctx.params["band_period"]) + 2

    def on_bar(self, ctx):
        p = ctx.params
        for symbol in ctx.symbols:
            closes = ctx.close_series(symbol, max(p["rsi_period"], p["band_period"]) * 3)
            rsi = ctx.indicators.rsi(closes, p["rsi_period"])[-1]
            mid, _, lower = ctx.indicators.bollinger(closes, p["band_period"], float(p["band_k"]))
            price = ctx.price(symbol)
            trades = ctx.open_trades(symbol)
            for trade in trades:
                if trade.stop_price is None:
                    target = Decimal(str(mid[-1]))
                    # A target at or under the price would be refused, so a recovery that already
                    # passed the middle band just gets its stop.
                    ctx.set_protection(
                        trade.id,
                        stop=trade.entry_price * (1 - p["stop_loss_percent"] / 100),
                        target=target if target > price else None,
                    )
            if not trades and rsi < p["rsi_below"] and closes[-1] < lower[-1]:
                ctx.buy(symbol, percent_of_cash=p["percent_of_cash"])
