"use client";

import { useEffect, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { ChartPanel } from "@/components/trade/chart-panel";
import { MetricsCard } from "@/components/trade/metrics-card";
import { OrderTicket } from "@/components/trade/order-ticket";
import { QuoteHeader } from "@/components/trade/quote-header";
import { TradeHome } from "@/components/trade/trade-home";
import { PageHeader } from "@/components/motion/page-header";
import { pushRecent } from "@/lib/recent-symbols";
import { OrdersTable } from "@/components/orders-table";
import { TradesTable } from "@/components/trades-table";
import { QueryError } from "@/components/query-error";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { protectionLines } from "@/lib/chart-protection";
import { toNumber } from "@/lib/format";
import { useOrders, usePortfolio, useQuote } from "@/lib/queries";
import type { ChartPriceLine } from "@/components/trade/price-chart";

function SymbolOrders({ symbol }: { symbol: string }) {
  const { data: orders, isPending, error, refetch } = useOrders({ symbol, limit: 20 });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your orders for {symbol}</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        {isPending && <Skeleton className="h-16 w-full" />}
        {error && <QueryError error={error} title="Couldn't load your orders" onRetry={() => refetch()} />}
        {orders && orders.length === 0 && (
          <p className="text-sm text-muted-foreground">No orders for {symbol} yet.</p>
        )}
        {orders && orders.length > 0 && <OrdersTable orders={orders} showSymbol={false} />}
      </CardContent>
    </Card>
  );
}

function SymbolTrades({ symbol }: { symbol: string }) {
  const { data: portfolio, isPending, error, refetch } = usePortfolio();
  const trades = portfolio?.trades.filter((t) => t.symbol === symbol) ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your open trades in {symbol}</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        {isPending && <Skeleton className="h-16 w-full" />}
        {error && !portfolio && <QueryError error={error} title="Couldn't load your trades" onRetry={() => refetch()} />}
        {portfolio && trades.length === 0 && (
          <p className="text-sm text-muted-foreground">No open trades in {symbol}.</p>
        )}
        {trades.length > 0 && <TradesTable trades={trades} showSymbol={false} />}
      </CardContent>
    </Card>
  );
}

export function TradeView() {
  const symbol = useSearchParams().get("symbol")?.trim() || null;
  const { data: quote, isPending, error, refetch } = useQuote(symbol);
  const portfolio = usePortfolio();
  const fills = useOrders({ symbol: symbol ?? undefined, status: "filled", limit: 200 }, !!symbol);
  const position = portfolio.data?.holdings.find((p) => p.symbol === symbol && p.direction === "long");

  // Hooks must run before the early returns below, so this sits up here.
  const openTrades = portfolio.data?.trades;
  const currentPrice = quote ? toNumber(quote.price) : null;
  const priceLines = useMemo<ChartPriceLine[]>(() => {
    const lines: ChartPriceLine[] = [];
    if (position) {
      lines.push({ price: toNumber(position.avg_price), title: "Avg entry", color: "#a855f7", dashed: false });
      if (position.break_even_price) {
        lines.push({ price: toNumber(position.break_even_price), title: "Break-even", color: "#f59e0b", dashed: true });
      }
    }
    lines.push(...protectionLines((openTrades ?? []).filter((t) => t.symbol === symbol), currentPrice));
    return lines;
  }, [position, openTrades, symbol, currentPrice]);

  // A symbol that loaded is remembered for the "recently viewed" tiles on this page without a symbol.
  const loadedSymbol = quote?.symbol;
  useEffect(() => {
    if (loadedSymbol) pushRecent(loadedSymbol);
  }, [loadedSymbol]);

  if (!symbol) return <TradeHome />;

  if (error && !quote) {
    return (
      <div className="grid grid-cols-1 gap-4">
        <PageHeader title={symbol} />
        <QueryError error={error} title={`Couldn't load ${symbol}`} onRetry={() => refetch()} />
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="grid min-w-0 grid-cols-1 content-start gap-4">
        {isPending || !quote ? <Skeleton className="h-32 w-full" /> : <QuoteHeader quote={quote} />}
        <ChartPanel
          symbol={symbol}
          currency={quote?.currency ?? "USD"}
          orders={fills.data}
          timeZone={quote?.market?.timezone}
          priceLines={priceLines}
        />
        <MetricsCard symbol={symbol} />
        <SymbolTrades symbol={symbol} />
        <SymbolOrders symbol={symbol} />
      </div>
      <div className="min-w-0">
        {quote ? <OrderTicket key={quote.symbol} quote={quote} /> : <Skeleton className="h-96 w-full" />}
      </div>
    </div>
  );
}
