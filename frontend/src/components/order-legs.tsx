import { Pnl } from "@/components/pnl";
import { Term } from "@/components/term";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatMoney, formatQuantity, isZero, toNumber } from "@/lib/format";
import type { OrderLeg } from "@/lib/types";

export const productLabel = (product: string) => product.charAt(0).toUpperCase() + product.slice(1);

/** The product name, explained when the glossary knows it. */
export function ProductLabel({ product }: { product: string }) {
  const label = productLabel(product);
  return product === "delivery" || product === "intraday" ? <Term id={product}>{label}</Term> : <>{label}</>;
}

/** Plain-language title of one leg, e.g. "Closes 5 shares you hold (delivery)". */
export function legTitle(leg: OrderLeg, unit: string): string {
  const qty = formatQuantity(leg.quantity);
  const product = leg.product;
  switch (leg.kind) {
    case "close_long":
      return `Closes ${qty} ${unit} you hold (${product})`;
    case "open_short":
      return `Opens a short of ${qty} (${product})`;
    case "close_short":
      return `Buys back ${qty} ${unit} you are short (${product})`;
    case "open_long":
      return `Buys ${qty} ${unit} (${product})`;
  }
}

/** One leg with its own charges. Every figure is the server's. */
export function LegBreakdown({ leg, unit, currency }: { leg: OrderLeg; unit: string; currency: string }) {
  return (
    <div className="grid gap-1.5 rounded-md border p-2.5">
      <div className="flex justify-between gap-2 font-medium">
        <span className="min-w-0">{legTitle(leg, unit)}</span>
        <span className="tabular-nums">{formatMoney(leg.value, currency)}</span>
      </div>
      {leg.charges.map((c) => (
        <div key={`${c.category}:${c.name}`} className="flex justify-between gap-2">
          <dt className="min-w-0 text-muted-foreground">
            <Tooltip>
              <TooltipTrigger
                render={<span tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-4" />}
              >
                {c.name}
              </TooltipTrigger>
              <TooltipContent>{c.description}</TooltipContent>
            </Tooltip>
          </dt>
          <dd className="tabular-nums">{formatMoney(c.amount, currency)}</dd>
        </div>
      ))}
      <div className="flex justify-between gap-2 border-t pt-1.5">
        <dt className="text-muted-foreground">Charges</dt>
        <dd className="tabular-nums">{formatMoney(leg.charges_total, currency)}</dd>
      </div>
      {!isZero(leg.margin_change) && (
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">{toNumber(leg.margin_change) > 0 ? "Margin blocked" : "Margin released"}</dt>
          <dd className="tabular-nums">{formatMoney(Math.abs(toNumber(leg.margin_change)), currency)}</dd>
        </div>
      )}
      {leg.realized_pnl !== null && leg.realized_pnl !== undefined && (
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Realized P&amp;L</dt>
          <dd>
            <Pnl value={leg.realized_pnl} currency={currency} />
          </dd>
        </div>
      )}
    </div>
  );
}

/** What the thing being traded is called in a sentence. */
export const unitFor = (marketCode: string | null | undefined) => (marketCode === "CRYPTO" ? "coins" : "shares");
