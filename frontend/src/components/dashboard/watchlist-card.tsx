"use client";

import Link from "next/link";
import { XIcon } from "lucide-react";
import { QueryError } from "@/components/query-error";
import { pnlClass } from "@/components/pnl";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPercent, formatPrice, formatPriceChange } from "@/lib/format";
import { useRemoveFromWatchlist, useWatchlist } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function WatchlistCard() {
  const { data: items, isPending, error, refetch } = useWatchlist();
  const remove = useRemoveFromWatchlist();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Watchlist</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        {error && !items && <QueryError error={error} title="Couldn't load your watchlist" onRetry={() => refetch()} />}
        {isPending && <Skeleton className="h-24 w-full" />}
        {items && items.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nothing watched yet. Open a symbol and press Watch to keep an eye on it here.
          </p>
        )}
        {remove.error && <p className="mb-2 text-sm text-destructive">{remove.error.message}</p>}
        {items && items.length > 0 && (
          <ul className="grid gap-1">
            {items.map((w) => {
              const currency = w.currency ?? "USD";
              const hasPrice = w.price !== null && w.price !== undefined;
              const hasChange = hasPrice && w.change != null && w.change_percent != null;
              return (
                <li key={w.symbol} className="flex min-w-0 items-center gap-2">
                  <Link
                    href={`/trade?symbol=${encodeURIComponent(w.symbol)}`}
                    className="flex min-w-0 flex-1 items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-muted"
                  >
                    <span className="min-w-0">
                      <span className="block font-medium">{w.symbol}</span>
                      <span className="block truncate text-xs text-muted-foreground">{w.name}</span>
                    </span>
                    <span className="shrink-0 text-right tabular-nums">
                      <span className="block">{hasPrice ? formatPrice(w.price, currency) : "—"}</span>
                      <span className={cn("block text-xs", hasChange ? pnlClass(w.change) : "text-muted-foreground")}>
                        {hasChange
                          ? `${formatPriceChange(w.change, currency, w.price)} (${formatPercent(w.change_percent)})`
                          : "—"}
                      </span>
                    </span>
                  </Link>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove ${w.symbol} from watchlist`}
                    disabled={remove.isPending && remove.variables === w.symbol}
                    onClick={() => remove.mutate(w.symbol)}
                  >
                    <XIcon />
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
