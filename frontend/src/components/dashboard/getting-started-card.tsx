"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatMoney } from "@/lib/format";
import { useOrders, usePortfolio } from "@/lib/queries";

/** Shown only until the first filled order exists. */
export function GettingStartedCard() {
  const filled = useOrders({ status: "filled", limit: 1 });
  const { data: p } = usePortfolio();

  if (!filled.data || filled.data.length > 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Getting started</CardTitle>
        <CardDescription>
          {p
            ? `You have ${formatMoney(p.starting_cash, p.currency)} of paper money to play with.`
            : "You have paper money to play with."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="grid list-decimal gap-1.5 pl-5 text-sm">
          <li>
            Press <kbd className="rounded border bg-muted px-1 text-xs">Ctrl</kbd>+
            <kbd className="rounded border bg-muted px-1 text-xs">K</kbd> and search for a stock, ETF or index.
          </li>
          <li>Read the chart, and switch the interval or indicators to see the price history.</li>
          <li>Place a paper order from the ticket beside the chart. No real money is involved.</li>
        </ol>
      </CardContent>
    </Card>
  );
}
