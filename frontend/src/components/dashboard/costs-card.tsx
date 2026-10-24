"use client";

import { QueryError } from "@/components/query-error";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Term } from "@/components/term";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { CHARGE_CATEGORIES } from "@/lib/charges";
import { formatMoney, isZero } from "@/lib/format";
import type { TermId } from "@/lib/glossary";
import { usePortfolio } from "@/lib/queries";

// Categories that are one glossary term; the broader ones (taxes, regulatory) keep their own help text.
const CATEGORY_TERM: Record<string, TermId> = {
  brokerage: "brokerage",
  exchange: "exchange_charge",
  depository: "dp_charge",
  gst: "gst",
  fx: "fx_markup",
};

export function CostsCard() {
  const { data: p, isPending, error, refetch } = usePortfolio();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Trading costs</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        {error && !p && <QueryError error={error} title="Couldn't load your costs" onRetry={() => refetch()} />}
        {isPending && <Skeleton className="h-24 w-full" />}
        {p && isZero(p.charges_paid.total) && (
          <p className="text-sm text-muted-foreground">
            You haven&apos;t paid any charges yet — every trade will show its costs before you place it.
          </p>
        )}
        {p && !isZero(p.charges_paid.total) && (
          <dl className="grid gap-1.5 text-sm">
            <div className="flex justify-between gap-2 pb-1 text-base font-medium">
              <dt>Total paid</dt>
              <dd className="tabular-nums">{formatMoney(p.charges_paid.total, p.currency)}</dd>
            </div>
            {CHARGE_CATEGORIES.filter((c) => !isZero(p.charges_paid.by_category[c.id])).map((c) => (
              <div key={c.id} className="flex justify-between gap-2">
                <dt className="text-muted-foreground">
                  {CATEGORY_TERM[c.id] ? (
                    <Term id={CATEGORY_TERM[c.id]}>{c.label}</Term>
                  ) : (
                    <Tooltip>
                      <TooltipTrigger
                        render={<span tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-4" />}
                      >
                        {c.label}
                      </TooltipTrigger>
                      <TooltipContent>{c.help}</TooltipContent>
                    </Tooltip>
                  )}
                </dt>
                <dd className="tabular-nums">{formatMoney(p.charges_paid.by_category[c.id], p.currency)}</dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}
