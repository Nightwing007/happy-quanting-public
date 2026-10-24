from decimal import Decimal

from app.algos import hq


class DonchianBreakout(hq.Strategy):
    name = "Donchian breakout"
    description = (
        "A momentum strategy. It buys when the close breaks above the highest high of the last N "
        "bars and exits when the close drops below the lowest low of a shorter window. With "
        "'allow shorts' on it sells short on a break below the lowest low and covers on a break "
        "above the shorter window's high. Daily bars. Breakouts that fail are common, so expect "
        "many small losses and a few large wins. Shorting follows each market's rules: Indian "
        "shorts are intraday and are squared off before the close (so they rarely run for days), "
        "US shorts pay borrow fees, crypto shorts pay funding, and other markets refuse shorts."
    )
    markets = ("india", "international", "crypto")
    interval = "1d"
    warmup_bars = 21
    PARAMETERS = {
        "lookback": hq.Param(
            "int", 20, min=2, max=250, label="Entry lookback", help="Bars in the entry channel."
        ),
        "exit_lookback": hq.Param(
            "int", 10, min=2, max=250, label="Exit lookback", help="Bars in the exit channel."
        ),
        "allow_shorts": hq.Param(
            "bool",
            False,
            label="Allow shorts",
            help="Also trade breakdowns, where the market allows shorting.",
        ),
        "percent_of_cash": hq.Param(
            "decimal",
            Decimal("50"),
            min=1,
            max=100,
            label="Cash per entry (%)",
            help="Share of available cash used for each entry.",
        ),
    }

    @classmethod
    def check_params(cls, params):
        if params["exit_lookback"] > params["lookback"]:
            return ["Exit lookback must not be longer than Entry lookback."]
        return []

    def on_start(self, ctx):
        self.warmup_bars = ctx.params["lookback"] + 1

    def on_bar(self, ctx):
        p = ctx.params
        for symbol in ctx.symbols:
            bars = ctx.bars(symbol, p["lookback"] + 1)
            # The channels are the bars before the latest one, so a breakout means the latest
            # close got beyond everything that came earlier.
            earlier, close = bars[:-1], bars[-1].close
            entry_high = max(b.high for b in earlier)
            entry_low = min(b.low for b in earlier)
            exit_high = max(b.high for b in earlier[-p["exit_lookback"] :])
            exit_low = min(b.low for b in earlier[-p["exit_lookback"] :])
            held = ctx.position(symbol).quantity
            if held > 0 and close < exit_low:
                ctx.sell(symbol)
            elif held < 0 and close > exit_high:
                for trade in ctx.open_trades(symbol):
                    ctx.exit(trade.id)
            elif held == 0 and close > entry_high:
                ctx.buy(symbol, percent_of_cash=p["percent_of_cash"])
            elif held == 0 and p["allow_shorts"] and close < entry_low:
                ctx.short(symbol, percent_of_cash=p["percent_of_cash"])
