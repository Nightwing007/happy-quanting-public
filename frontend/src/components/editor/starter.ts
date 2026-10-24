// The smallest valid strategy, copied from docs/algo-rules.md ("Smallest valid strategy") plus one
// log line so a first run shows something in the log.
export const STARTER_TEMPLATE = `import hq


class BuyAndWait(hq.Strategy):
    name = "Buy and wait"
    description = "Buys once with a tenth of the cash and holds."
    markets = ("india", "international", "crypto")
    interval = "1d"
    warmup_bars = 1
    PARAMETERS = {
        "percent_of_cash": hq.Param("int", 10, min=1, max=100, label="Cash to spend (%)"),
    }

    def on_bar(self, ctx):
        for symbol in ctx.symbols:
            if ctx.position(symbol).quantity == 0:
                ctx.buy(symbol, percent_of_cash=ctx.params["percent_of_cash"])
                ctx.log(f"Buying {symbol} at {ctx.price(symbol)}")
`;
