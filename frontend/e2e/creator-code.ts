// Strategy code used by the marketplace specs. The marker strings must never reach a subscriber.
export const SECRET_LINE = 'secret_marker = "E2E_SECRET_LINE_4f9a2c"';
export const SECRET_PARAM = "47.3159265";
export const SECRET_V2_LINE = 'secret_marker_two = "E2E_SECRET_V2_LINE_81d3b7"';

export function creatorCode(opts: { name: string; extra?: string; bad?: boolean }): string {
  return `${opts.bad ? "import os\n" : ""}from decimal import Decimal

import hq


class ${opts.name.replace(/\W/g, "")}(hq.Strategy):
    name = "${opts.name}"
    description = "Buys a little bitcoin once and holds it."
    markets = ("crypto",)
    interval = "1d"
    warmup_bars = 1
    PARAMETERS = {
        "percent_of_cash": hq.Param("decimal", Decimal("${SECRET_PARAM}"), min=1, max=100, label="Cash per entry (%)"),
    }

    def on_bar(self, ctx):
        ${SECRET_LINE}
${opts.extra ? `        ${opts.extra}\n` : ""}        for symbol in ctx.symbols:
            if ctx.position(symbol).quantity == 0:
                ctx.buy(symbol, percent_of_cash=ctx.params["percent_of_cash"])
`;
}
