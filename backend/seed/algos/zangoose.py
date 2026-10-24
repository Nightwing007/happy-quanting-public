from decimal import Decimal

import hq

# 1h bars on purpose: Yahoo keeps 15-minute data for only ~60 days, 1h reaches about 2 years.


class HourlyMomentumBreakout(hq.Strategy):
    name = "Hourly momentum breakout"
    description = (
        "An aggressive momentum strategy for Indian and US equities on hourly bars. It buys when the "
        "close breaks above the highest high of the last N hours and, where the market allows "
        "shorting, sells short when it breaks below the lowest low. Each trade gets a tight stop "
        "(a small multiple of the average true range) and a target twice as far away. Expect many "
        "small stopped-out losses and the occasional run that pays for them; it trades often, so "
        "charges weigh on it. It assumes breakouts carry on for a few hours, and it does worst in "
        "choppy, range-bound sessions. Indian shorts are intraday and are squared off before the "
        "close; US shorts pay borrow fees."
    )
    markets = ("india", "international")
    interval = "1h"
    warmup_bars = 21
    PARAMETERS = {
        "lookback": hq.Param("int", 20, min=3, max=200, label="Breakout lookback (hours)"),
        "atr_period": hq.Param("int", 14, min=2, max=100, label="ATR period"),
        "stop_atr": hq.Param("decimal", Decimal("1.5"), min="0.3", max=10, label="Stop distance (ATRs)"),
        "reward_multiple": hq.Param("decimal", Decimal("2"), min="0.5", max=10, label="Target = stop x"),
        "allow_shorts": hq.Param("bool", True, label="Allow shorts"),
        "percent_of_cash": hq.Param("decimal", Decimal("25"), min=1, max=100, label="Cash per entry (%)"),
    }

    def on_start(self, ctx):
        self.warmup_bars = max(ctx.params["lookback"], ctx.params["atr_period"]) + 2

    def on_bar(self, ctx):
        p = ctx.params
        for symbol in ctx.symbols:
            bars = ctx.bars(symbol, max(p["lookback"], p["atr_period"]) * 3)
            highs = [float(b.high) for b in bars]
            lows = [float(b.low) for b in bars]
            closes = [float(b.close) for b in bars]
            atr = Decimal(str(ctx.indicators.atr(highs[:-1], lows[:-1], closes[:-1], p["atr_period"])[-1]))
            trades = ctx.open_trades(symbol)
            for trade in trades:
                if trade.stop_price is None:
                    risk = atr * p["stop_atr"]
                    reward = risk * p["reward_multiple"]
                    entry = trade.entry_price
                    if trade.direction == "long":
                        stop, target = entry - risk, entry + reward
                    else:
                        stop, target = entry + risk, entry - reward
                    ctx.set_protection(trade.id, stop=stop, target=target if target > 0 else None)
            if trades:
                continue
            channel_high = max(highs[-p["lookback"] - 1 : -1])
            channel_low = min(lows[-p["lookback"] - 1 : -1])
            if closes[-1] > channel_high:
                ctx.buy(symbol, percent_of_cash=p["percent_of_cash"])
            elif p["allow_shorts"] and closes[-1] < channel_low:
                ctx.short(symbol, percent_of_cash=p["percent_of_cash"])
