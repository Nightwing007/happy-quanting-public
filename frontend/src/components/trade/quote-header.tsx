"use client";

import { Eye, EyeOff } from "lucide-react";
import { Term } from "@/components/term";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useAddToWatchlist, useRemoveFromWatchlist, useWatchlist } from "@/lib/queries";
import { article, formatPercent, formatPrice, formatPriceChange, isZero, toNumber } from "@/lib/format";
import type { Quote } from "@/lib/types";
import { cn } from "@/lib/utils";

// Green open, amber lunch break, grey closed, outline when the hours are unknown.
function MarketBadge({ market }: { market: NonNullable<Quote["market"]> }) {
  const variant = market.state === "unknown" ? "outline" : "secondary";
  const tone =
    market.state === "open"
      ? "bg-green-600/15 text-green-700 dark:text-green-400"
      : market.state === "closed" && market.reason === "lunch break"
        ? "bg-amber-500/15 text-amber-700 dark:text-amber-400"
        : market.state === "closed"
          ? "text-muted-foreground"
          : "";
  return (
    <Badge variant={variant} className={cn("h-auto whitespace-normal py-0.5", tone)}>
      {market.state === "closed" ? <Term id="amo">{market.label}</Term> : market.label}
    </Badge>
  );
}

export function QuoteHeader({ quote }: { quote: Quote }) {
  const watchlist = useWatchlist();
  const add = useAddToWatchlist();
  const remove = useRemoveFromWatchlist();

  const watching = watchlist.data?.some((w) => w.symbol === quote.symbol) ?? false;
  const busy = add.isPending || remove.isPending;
  const mutationError = add.error ?? remove.error;

  const hasChange = quote.change !== null && quote.change_percent !== null;
  const direction = !hasChange || isZero(quote.change) ? 0 : toNumber(quote.change) > 0 ? 1 : -1;
  const asOf = new Date(quote.as_of * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <Card>
      <CardContent className="grid min-w-0 gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">{quote.symbol}</h1>
              <Badge variant="secondary">{quote.type}</Badge>
              {quote.market && <MarketBadge market={quote.market} />}
            </div>
            <p className="truncate text-sm text-muted-foreground">
              {quote.name} · {quote.exchange}
            </p>
          </div>
          <Button
            variant={watching ? "secondary" : "outline"}
            disabled={busy || watchlist.isPending}
            onClick={() => (watching ? remove.mutate(quote.symbol) : add.mutate(quote.symbol))}
          >
            {watching ? <Eye /> : <EyeOff />}
            {watching ? "Watching" : "Watch"}
          </Button>
        </div>

        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-3xl font-semibold tabular-nums">{formatPrice(quote.price, quote.currency)}</span>
          {hasChange && (
            <span
              className={cn(
                "tabular-nums",
                direction === 0 && "text-muted-foreground",
                direction > 0 && "text-green-600 dark:text-green-400",
                direction < 0 && "text-red-600 dark:text-red-400",
              )}
            >
              {formatPriceChange(quote.change, quote.currency, quote.price)} ({formatPercent(quote.change_percent)})
            </span>
          )}
          <span className="text-xs text-muted-foreground">as of {asOf}</span>
        </div>

        {mutationError && <p className="text-sm text-destructive">{mutationError.message}</p>}
        {!quote.tradable && (
          <p className="text-sm text-muted-foreground">
            {quote.name} is {article(quote.type)} — it can be charted but not traded.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
