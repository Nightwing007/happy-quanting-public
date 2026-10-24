from decimal import Decimal

import hq

# 1h bars on purpose: Yahoo keeps 15-minute data for only ~60 days, 1h reaches about 2 years.


class CryptoAtrBreakout(hq.Strategy):
    name = "Crypto ATR breakout"
    description = (
        "An explosive volatility-breakout strategy for crypto on hourly bars, running around the "
        "clock. When a close jumps more than 6 times the average true range (ATR) above the "
        "previous close it buys; when it drops by the same amount it sells short. Each trade has a "
        "fixed stop 4 ATRs away and a target 8 ATRs away, set once at entry (no trailing). Crypto "
        "costs are high, so it waits for rare big moves and trades seldom. Expect "
        "streaks of stop-outs in quiet, drifting markets and large moves when volatility "
        "expands. Crypto can gap through a stop, which then fills at the market, and shorts pay "
        "funding."
    )
    markets = ("crypto",)
    interval = "1h"
    warmup_bars = 16
    PARAMETERS = {
        "atr_period": hq.Param("int", 14, min=2, max=100, label="ATR period"),
        "trigger_atr": hq.Param("decimal", Decimal("6"), min="0.2", max=10, label="Breakout size (ATRs)"),
        "stop_atr": hq.Param("decimal", Decimal("4"), min="0.5", max=10, label="Stop distance (ATRs)"),
        "target_atr": hq.Param("decimal", Decimal("8"), min="0.5", max=20, label="Target distance (ATRs)"),
        "percent_of_cash": hq.Param("decimal", Decimal("10"), min=1, max=100, label="Cash per entry (%)"),
    }

    def on_start(self, ctx):
        self.warmup_bars = ctx.params["atr_period"] + 2

    def on_bar(self, ctx):
        p = ctx.params
        for symbol in ctx.symbols:
            bars = ctx.bars(symbol, p["atr_period"] * 3)
            highs = [float(b.high) for b in bars]
            lows = [float(b.low) for b in bars]
            closes = [float(b.close) for b in bars]
            # The ATR up to the previous bar, so the bar being judged cannot widen its own yardstick.
            atr = Decimal(str(ctx.indicators.atr(highs[:-1], lows[:-1], closes[:-1], p["atr_period"])[-1]))
            previous, close = bars[-2].close, bars[-1].close
            trades = ctx.open_trades(symbol)
            for trade in trades:
                if trade.stop_price is None:
                    stop, target = atr * p["stop_atr"], atr * p["target_atr"]
                    entry = trade.entry_price
                    if trade.direction == "long":
                        ctx.set_protection(trade.id, stop=entry - stop, target=entry + target)
                    else:
                        ctx.set_protection(trade.id, stop=entry + stop, target=entry - target)
            if trades:
                continue
            if close > previous + atr * p["trigger_atr"]:
                ctx.buy(symbol, percent_of_cash=p["percent_of_cash"])
            elif close < previous - atr * p["trigger_atr"]:
                ctx.short(symbol, percent_of_cash=p["percent_of_cash"])
