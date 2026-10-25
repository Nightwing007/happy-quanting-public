"use client";

import { SplitFlap } from "@/components/motion/split-flap";
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { FlaskConicalIcon } from "lucide-react";
import { OrdersTable } from "@/components/orders-table";
import { PayoutsPanel } from "@/components/payouts-panel";
import { Pnl } from "@/components/pnl";
import { QueryError } from "@/components/query-error";
import { SummaryCards } from "@/components/dashboard/summary-cards";
import { TradesTable } from "@/components/trades-table";
import { OrderTicket } from "@/components/trade/order-ticket";
import { PriceChart, type ChartPriceLine } from "@/components/trade/price-chart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { simBase } from "@/lib/api";
import { buildFillMarkers, MARKER_STYLES } from "@/lib/chart-markers";
import { protectionLines } from "@/lib/chart-protection";
import { formatMoney, formatPrice, toNumber } from "@/lib/format";
import { invalidateAccount, useOrders, usePayouts, usePortfolio, useQuote, useSimState } from "@/lib/queries";
import { formatDayRange, intervalWords } from "@/lib/sim-format";
import { TradingScope } from "@/lib/trading-scope";
import type { Quote } from "@/lib/types";
import { PlayerBar } from "./player-bar";
import { StrategyPanel } from "./strategy-panel";

function Summary() {
  const payouts = usePayouts();
  const portfolio = usePortfolio();
  const t = payouts.data?.totals;
  const currency = payouts.data?.currency ?? portfolio.data?.currency ?? "USD";
  return (
    <Card>
      <CardHeader>
        <CardTitle>Simulation finished</CardTitle>
      </CardHeader>
      <CardContent className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-3">
        <div>
          <p className="text-xs text-muted-foreground">Trades closed</p>
          <p className="text-xl font-semibold tabular-nums">{t?.trades_closed ?? "—"}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Net profit after charges</p>
          <p className="text-xl font-semibold">{t ? <Pnl value={t.net_profit} currency={currency} /> : "—"}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Charges paid</p>
          <p className="text-xl font-semibold tabular-nums">
            {portfolio.data ? formatMoney(portfolio.data.charges_paid.total, currency) : "—"}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function SimBody({ id }: { id: number }) {
  const base = simBase(id);
  const qc = useQueryClient();
  const state = useSimState(id);
  const data = state.data;
  const [picked, setPicked] = useState<string | null>(null);
  const symbol = picked && data?.symbols.includes(picked) ? picked : (data?.symbols[0] ?? null);

  // A live quote is used only for the name, type and market rules; the price comes from the replay.
  const meta = useQuote(symbol);
  const portfolio = usePortfolio();
  const fills = useOrders({ symbol: symbol ?? undefined, status: "filled", limit: 200 }, !!symbol);
  const orders = useOrders({ limit: 50 });

  // Fills, balances and previews follow the replayed clock.
  const cursor = data?.cursor;
  const lastCursor = useRef(cursor);
  useEffect(() => {
    if (cursor && cursor !== lastCursor.current) invalidateAccount(qc, base);
    lastCursor.current = cursor;
  }, [cursor, base, qc]);

  const bars = useMemo(() => (symbol && data ? (data.bars[symbol] ?? []) : []), [symbol, data]);
  const zone = data?.exchange_times.find((t) => t.symbol === symbol)?.timezone;
  const lastBar = bars.length ? bars[bars.length - 1] : null;
  const currency = meta.data?.currency ?? portfolio.data?.currency ?? "USD";

  const quote = useMemo<Quote | null>(() => {
    if (!symbol || !lastBar) return null;
    const m = meta.data?.market;
    return {
      symbol,
      name: meta.data?.name ?? symbol,
      exchange: meta.data?.exchange ?? "",
      type: meta.data?.type ?? "",
      currency,
      tradable: meta.data?.tradable ?? true,
      price: lastBar.close,
      previous_close: null,
      change: null,
      change_percent: null,
      as_of: Math.floor(new Date(data!.cursor).getTime() / 1000),
      // Today's opening hours say nothing about the replayed day, so the ticket must not claim
      // the market is closed; the server applies the real hours at the replayed time.
      market: m ? { ...m, state: "unknown", is_open: false, label: "Replay", reason: "replayed session" } : null,
    };
  }, [symbol, lastBar, meta.data, currency, data]);

  const position = portfolio.data?.holdings.find((p) => p.symbol === symbol && p.direction === "long");
  const openTrades = portfolio.data?.trades;
  const currentPrice = lastBar ? toNumber(lastBar.close) : null;
  const priceLines = useMemo<ChartPriceLine[]>(() => {
    const lines: ChartPriceLine[] = [];
    if (position) {
      lines.push({ price: toNumber(position.avg_price), title: "Avg entry", color: "#a855f7", dashed: false });
    }
    lines.push(...protectionLines((openTrades ?? []).filter((t) => t.symbol === symbol), currentPrice));
    return lines;
  }, [position, openTrades, symbol, currentPrice]);
  const markers = useMemo(
    () => buildFillMarkers(fills.data ?? [], bars, true, zone),
    [fills.data, bars, zone],
  );

  if (state.error && !data) {
    return <QueryError error={state.error} title="Couldn't load this simulation" onRetry={() => state.refetch()} />;
  }
  if (!data || !symbol) return <Skeleton className="h-96 w-full" />;

  const closeText = lastBar ? formatPrice(lastBar.close, currency) : null;

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <div
        role="status"
        className="flex flex-wrap items-center gap-x-2 gap-y-1 border border-warn/50 bg-warn/15 px-3 py-2 text-sm font-semibold text-foreground"
      >
        <FlaskConicalIcon className="size-4 shrink-0" />
        <span>SIMULATION · replayed data · {formatDayRange(data)}</span>
        <Link href="/sim" className="ml-auto text-xs font-normal underline underline-offset-2">
          All simulations
        </Link>
      </div>

      <PlayerBar session={data} symbol={symbol} />

      <StrategyPanel session={data} />

      {data.status === "finished" && <Summary />}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid min-w-0 grid-cols-1 content-start gap-4">
          <Card>
            <CardContent className="grid min-w-0 gap-3">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <h1 className="text-[28px] leading-none sm:text-[34px]"><SplitFlap text={symbol} /></h1>
                {meta.data && <Badge variant="secondary">{meta.data.type}</Badge>}
                <span className="text-xs text-muted-foreground">
                  {meta.data?.name} · {intervalWords(data.interval)} bars
                </span>
                {closeText ? (
                  <span className="ml-auto text-2xl font-semibold tabular-nums">{closeText}</span>
                ) : (
                  <span className="ml-auto text-sm text-muted-foreground">No bar has finished yet</span>
                )}
              </div>
              {data.symbols.length > 1 && (
                <ToggleGroup
                  variant="outline"
                  size="sm"
                  spacing={0}
                  aria-label="Symbol"
                  value={[symbol]}
                  onValueChange={(v) => v[0] && setPicked(v[0])}
                >
                  {data.symbols.map((s) => (
                    <ToggleGroupItem key={s} value={s}>
                      {s}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              )}
              <div className="flex min-h-5 flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                {lastBar && (
                  <span className="tabular-nums">
                    O {formatPrice(lastBar.open, currency)} H {formatPrice(lastBar.high, currency)} L{" "}
                    {formatPrice(lastBar.low, currency)} C {formatPrice(lastBar.close, currency)}
                  </span>
                )}
                {priceLines.some((l) => l.title === "Stop") && (
                  <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block w-3 border-t-2 border-dashed border-down" />
                    Stop
                  </span>
                )}
                {priceLines.some((l) => l.title === "Target") && (
                  <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block w-3 border-t-2 border-dashed border-up" />
                    Target
                  </span>
                )}
                {markers.length > 0 &&
                  Object.values(MARKER_STYLES).map((m) => (
                    <span key={m.label} className="inline-flex items-center gap-1">
                      <span style={{ color: m.color }} aria-hidden>
                        {m.shape === "arrowUp" ? "▲" : "▼"}
                      </span>
                      {m.label}
                    </span>
                  ))}
              </div>
              {bars.length === 0 ? (
                <p className="py-16 text-center text-sm text-muted-foreground">
                  Nothing has been replayed yet. Press Play or Step 1 bar to reveal the first bar.
                </p>
              ) : (
                <PriceChart
                  bars={bars}
                  indicators={[]}
                  intraday
                  incremental
                  markers={markers}
                  priceLines={priceLines}
                  className="h-[380px] w-full min-w-0 sm:h-[460px]"
                />
              )}
            </CardContent>
          </Card>

          <SummaryCards />

          <Card>
            <CardHeader>
              <CardTitle>Open trades</CardTitle>
            </CardHeader>
            <CardContent className="min-w-0">
              {portfolio.isPending && <Skeleton className="h-16 w-full" />}
              {portfolio.data && portfolio.data.trades.length === 0 && (
                <p className="text-sm text-muted-foreground">No open trades in this simulation.</p>
              )}
              {portfolio.data && portfolio.data.trades.length > 0 && <TradesTable trades={portfolio.data.trades} />}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Orders</CardTitle>
            </CardHeader>
            <CardContent className="min-w-0">
              {orders.isPending && <Skeleton className="h-16 w-full" />}
              {orders.data && orders.data.length === 0 && (
                <p className="text-sm text-muted-foreground">No orders in this simulation yet.</p>
              )}
              {orders.data && orders.data.length > 0 && <OrdersTable orders={orders.data} />}
            </CardContent>
          </Card>

          <div className="grid min-w-0 grid-cols-1 gap-4">
            <h2 className="text-lg font-semibold tracking-tight">Payouts</h2>
            <PayoutsPanel />
          </div>
        </div>

        <div className="min-w-0">
          {quote ? (
            <OrderTicket key={quote.symbol} quote={quote} />
          ) : (
            <Card>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  The order ticket opens once the first bar has finished. Press Play or Step 1 bar.
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

export function SimView({ id }: { id: number }) {
  if (!Number.isInteger(id)) return <p className="text-sm text-muted-foreground">That simulation does not exist.</p>;
  return (
    <TradingScope base={simBase(id)}>
      <SimBody id={id} />
    </TradingScope>
  );
}

export function SimRoute() {
  const { id } = useParams<{ id: string }>();
  return <SimView id={Number(id)} />;
}
