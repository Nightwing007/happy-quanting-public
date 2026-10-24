"use client";

import { QueryError } from "@/components/query-error";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { CHARGE_CATEGORIES } from "@/lib/charges";
import { formatMoney, isZero } from "@/lib/format";
import { usePortfolio } from "@/lib/queries";

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
                  <Tooltip>
                    <TooltipTrigger
                      render={<span tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-4" />}
                    >
                      {c.label}
                    </TooltipTrigger>
                    <TooltipContent>{c.help}</TooltipContent>
                  </Tooltip>
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
