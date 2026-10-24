"use client";

import { QueryError } from "@/components/query-error";
import { TradesTable } from "@/components/trades-table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePortfolio } from "@/lib/queries";

export function OpenTradesCard() {
  const { data: p, isPending, error, refetch } = usePortfolio();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Open trades</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        {error && !p && <QueryError error={error} title="Couldn't load your trades" onRetry={() => refetch()} />}
        {isPending && <Skeleton className="h-24 w-full" />}
        {p && p.trades.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No open trades. Every buy or short you place becomes a trade you can exit on its own.
          </p>
        )}
        {p && p.trades.length > 0 && <TradesTable trades={p.trades} />}
      </CardContent>
    </Card>
  );
}
