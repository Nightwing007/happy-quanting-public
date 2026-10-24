from decimal import Decimal

from app.algos import hq


class CryptoVolatilityBreakout(hq.Strategy):
    name = "Crypto volatility breakout"
    description = (
        "Buys when the close jumps more than a multiple of the average true range (ATR) above the "
        "previous close, and sets a stop-loss an ATR-based distance below the entry, so the stop "
        "widens in wild markets and tightens in calm ones. Exits when the close drops by the same "
        "multiple of ATR. Hourly bars, long only, built for crypto, which trades around the clock; "
        "markets with sessions and overnight gaps will not behave the same. Crypto moves fast: a "
        "gap through a stop fills at the market, not at the stop price."
    )
    markets = ("crypto",)
    interval = "1h"
    warmup_bars = 16
    PARAMETERS = {
        "atr_period": hq.Param(
            "int", 14, min=2, max=100, label="ATR period", help="Bars in the average true range."
        ),
        "multiplier": hq.Param(
            "decimal",
            Decimal("1.5"),
            min="0.2",
            max=10,
            label="Breakout multiplier",
            help="How many ATRs above the previous close counts as a breakout.",
        ),
        "stop_multiplier": hq.Param(
            "decimal",
            Decimal("2"),
            min="0.5",
            max=10,
            label="Stop distance (ATRs)",
            help="How many ATRs below the entry the stop-loss sits.",
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
                    ctx.set_protection(trade.id, stop=close - atr * p["stop_multiplier"])
            if not trades and close > previous + atr * p["multiplier"]:
                ctx.buy(symbol, percent_of_cash=p["percent_of_cash"])
            elif trades and close < previous - atr * p["multiplier"]:
                ctx.sell(symbol)
