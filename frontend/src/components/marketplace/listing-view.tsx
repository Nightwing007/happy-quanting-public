"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { InfoIcon } from "lucide-react";
import { QueryError } from "@/components/query-error";
import { Term } from "@/components/term";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SeriesChart, type ChartLine } from "@/components/algos/series-chart";
import { algoIntervalWords, formatPlain, isIntraday } from "@/lib/algo-format";
import { formatMoney, formatPercent, formatRatio, toNumber } from "@/lib/format";
import type { TermId } from "@/lib/glossary";
import { feeShort, feeTerms, marketWord, WINDOW_WORDS } from "@/lib/marketplace-format";
import { useListing, useMe } from "@/lib/queries";
import type { ListingDetail, ListingPerformance, PerformanceResults } from "@/lib/types";
import { CreatorLink } from "./listing-card";
import { SubscribeDialog } from "./subscribe-dialog";

const COLOR_STRATEGY = "#a855f7";
const COLOR_HOLD = "#9ca3af";
const COLOR_DRAWDOWN = "#dc2626";

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });
const formatEquity = (v: number) => compact.format(v);
const formatDrawdown = (v: number) => `${v.toFixed(1)}%`;

function Stat({
  label,
  value,
  note,
  tone,
  term,
}: {
  label: string;
  value: React.ReactNode;
  note?: React.ReactNode;
  tone?: string;
  term?: TermId;
}) {
  return (
    <Card size="sm">
      <CardContent className="grid min-w-0 gap-0.5">
        <p className="text-xs text-muted-foreground">{term ? <Term id={term}>{label}</Term> : label}</p>
        <p className={`text-xl font-semibold tabular-nums ${tone ?? ""}`}>{value}</p>
        {note && <p className="text-xs text-muted-foreground">{note}</p>}
      </CardContent>
    </Card>
  );
}

function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4" style={{ backgroundColor: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}

function Charges({ results }: { results: PerformanceResults }) {
  const m = results.metrics;
  const currency = results.account_currency;
  return (
    <Card className="border-primary/40 bg-primary/5">
      <CardHeader>
        <CardTitle>What trading cost</CardTitle>
      </CardHeader>
      <CardContent className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <p className="text-sm text-muted-foreground">Total charges paid by the algorithm</p>
          <p className="text-3xl font-semibold tabular-nums" data-testid="total-charges">
            {formatMoney(m.total_charges, currency)}
          </p>
          <p className="text-xs text-muted-foreground">Brokerage, taxes and fees are already taken out of every figure below.</p>
        </div>
        <div>
          <p className="text-sm text-muted-foreground">Charges paid by buy and hold</p>
          <p className="text-3xl font-semibold tabular-nums">{formatMoney(results.buy_and_hold.total_charges, currency)}</p>
          <p className="text-xs text-muted-foreground">Same symbols, equal weight, for comparison.</p>
        </div>
      </CardContent>
    </Card>
  );
}

function Metrics({ results }: { results: PerformanceResults }) {
  const m = results.metrics;
  const hold = results.buy_and_hold;
  const currency = results.account_currency;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Stat
        label="Total return"
        term="total_return"
        value={formatPercent(m.total_return_pct)}
        tone={toNumber(m.total_return_pct) < 0 ? "text-down" : undefined}
        note={`${formatMoney(m.starting_cash, currency)} to ${formatMoney(m.final_equity, currency)} · buy and hold ${formatPercent(hold.total_return_pct)}`}
      />
      <Stat
        label="CAGR"
        term="cagr"
        value={m.cagr_pct === null ? "Under a year" : formatPercent(m.cagr_pct)}
        note={m.cagr_pct === null ? (m.cagr_note ?? "Annualised only over a year or more") : undefined}
      />
      <Stat
        label="Max drawdown"
        term="max_drawdown"
        value={`-${formatRatio(m.max_drawdown_pct, "%")}`}
        note={`Buy and hold -${formatRatio(hold.max_drawdown_pct, "%")}`}
      />
      <Stat
        label="Sharpe ratio"
        term="sharpe"
        value={m.sharpe === null ? "—" : formatPlain(m.sharpe)}
        note={m.sharpe === null ? (m.sharpe_note ?? undefined) : undefined}
      />
      <Stat
        label="Win rate"
        term="win_rate"
        value={m.win_rate_pct === null ? "—" : formatRatio(m.win_rate_pct, "%")}
        note={m.win_rate_pct === null ? "No closed trades" : undefined}
      />
      <Stat
        label="Profit factor"
        term="profit_factor"
        value={m.profit_factor === null ? "—" : formatPlain(m.profit_factor)}
        note="Gross wins over gross losses"
      />
      <Stat label="Trades" value={m.trade_count} note="Closed trades" />
      <Stat label="Exposure" term="exposure" value={formatRatio(m.exposure_pct, "%")} note="Share of bars with a position open" />
    </div>
  );
}

function Curves({ results, interval }: { results: PerformanceResults; interval: string }) {
  const intraday = isIntraday(interval);
  const equity = useMemo<ChartLine[]>(
    () => [
      { name: "Buy and hold", color: COLOR_HOLD, points: results.equity_curve.map((p) => ({ at: p.at, value: toNumber(p.buy_hold_equity) })) },
      { name: "Strategy", color: COLOR_STRATEGY, points: results.equity_curve.map((p) => ({ at: p.at, value: toNumber(p.equity) })) },
    ],
    [results],
  );
  const drawdown = useMemo<ChartLine[]>(
    () => [
      { name: "Buy and hold", color: COLOR_HOLD, points: results.drawdown.map((p) => ({ at: p.at, value: toNumber(p.buy_hold_pct) })) },
      { name: "Strategy", color: COLOR_DRAWDOWN, area: true, points: results.drawdown.map((p) => ({ at: p.at, value: toNumber(p.strategy_pct) })) },
    ],
    [results],
  );
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Equity: algorithm against buy and hold</CardTitle>
        </CardHeader>
        <CardContent className="grid min-w-0 gap-2">
          <Legend items={[{ label: "Algorithm", color: COLOR_STRATEGY }, { label: "Buy and hold", color: COLOR_HOLD }]} />
          <SeriesChart lines={equity} intraday={intraday} format={formatEquity} className="h-64 w-full" />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Drawdown</CardTitle>
        </CardHeader>
        <CardContent className="grid min-w-0 gap-2">
          <Legend items={[{ label: "Algorithm", color: COLOR_DRAWDOWN }, { label: "Buy and hold", color: COLOR_HOLD }]} />
          <SeriesChart lines={drawdown} intraday={intraday} format={formatDrawdown} className="h-64 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}

function WindowPanel({ perf, interval }: { perf: ListingPerformance; interval: string }) {
  if (perf.status !== "done" || !perf.results) {
    // A retry the server has scheduled is not a failure: say so calmly, whatever status it carries.
    const retrying = perf.note?.startsWith("Measuring again soon") ?? false;
    const waiting = perf.status === "queued" || perf.status === "running";
    return (
      <Alert>
        <InfoIcon />
        <AlertTitle>
          {retrying
            ? "Being measured"
            : waiting
              ? "Still being measured"
              : perf.status === "failed"
                ? "Couldn't be measured"
                : "Not available"}
        </AlertTitle>
        <AlertDescription>
          {perf.note ?? (waiting ? "Check back in a minute." : "This window has no result.")}
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <div className="grid min-w-0 gap-4">
      <p className="text-sm text-muted-foreground">
        Measured from {perf.start} to {perf.end} on the creator&apos;s test symbols, starting with{" "}
        {formatMoney(perf.results.metrics.starting_cash, perf.results.account_currency)}.
      </p>
      <Charges results={perf.results} />
      <Metrics results={perf.results} />
      <Curves results={perf.results} interval={interval} />
    </div>
  );
}

function Performance({ listing }: { listing: ListingDetail }) {
  const windows = listing.performance;
  const firstDone = windows.find((w) => w.window === "1y" && w.status === "done") ?? windows.find((w) => w.status === "done");
  const [picked, setPicked] = useState<string | null>(null);
  const current = picked && windows.some((w) => w.window === picked) ? picked : (firstDone ?? windows[0])?.window;
  if (!current) return <p className="text-sm text-muted-foreground">Performance is still being measured.</p>;
  return (
    <Tabs value={current} onValueChange={(v) => setPicked(String(v))} className="min-w-0">
      <TabsList>
        {windows.map((w) => (
          <TabsTrigger key={w.window} value={w.window}>
            {WINDOW_WORDS[w.window]}
          </TabsTrigger>
        ))}
      </TabsList>
      {windows.map((w) => (
        <TabsContent key={w.window} value={w.window} className="min-w-0">
          <WindowPanel perf={w} interval={listing.interval} />
        </TabsContent>
      ))}
    </Tabs>
  );
}

function Sidebar({ listing }: { listing: ListingDetail }) {
  const me = useMe();
  const mine = me.data?.username === listing.creator.username;
  return (
    <div className="grid content-start gap-4">
      <Card>
        <CardHeader>
          <CardTitle>What you choose</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm">
          <p>
            <span className="text-muted-foreground">Markets it can trade: </span>
            {listing.markets.map(marketWord).join(", ")}
          </p>
          <p>The symbols to apply it to, within those markets, and how much capital to give it.</p>
          <p className="text-muted-foreground">{feeTerms(listing.fee_percent)}</p>
          {mine ? (
            <p className="text-muted-foreground">This is your own listing, so you can&apos;t subscribe to it.</p>
          ) : (
            <SubscribeDialog listing={listing} />
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>What stays private</CardTitle>
        </CardHeader>
        <CardContent className="text-sm">
          <p>The creator&apos;s code and settings are never shown — you see only how it has performed.</p>
        </CardContent>
      </Card>
    </div>
  );
}

function ListingView({ id }: { id: number }) {
  const { data: listing, isPending, error, refetch } = useListing(id);
  if (error && !listing) return <QueryError error={error} title="Couldn't load this listing" onRetry={() => refetch()} />;
  if (isPending || !listing) return <Skeleton className="h-96 w-full" />;
  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <p className="text-sm">
        <Link href="/marketplace" className="text-muted-foreground underline-offset-2 hover:underline">
          Marketplace
        </Link>
      </p>
      <div className="grid min-w-0 gap-2">
        <h1 className="t-display text-[28px] leading-tight break-words sm:text-[34px]">{listing.name}</h1>
        <p className="text-muted-foreground">{listing.tagline}</p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <CreatorLink creator={listing.creator} />
          {listing.markets.map((m) => (
            <Badge key={m} variant="secondary">
              {marketWord(m)}
            </Badge>
          ))}
          <Badge variant="outline">{algoIntervalWords(listing.interval)} bars</Badge>
          <span className="text-sm">{feeShort(listing.fee_percent)}</span>
        </div>
      </div>
      <div className="grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="grid min-w-0 content-start gap-6">
          {listing.description && <p className="max-w-prose text-sm whitespace-pre-line">{listing.description}</p>}
          <section className="grid min-w-0 gap-3" aria-labelledby="perf-heading">
            <h2 id="perf-heading" className="text-lg font-semibold tracking-tight">
              How it has performed
            </h2>
            <Performance listing={listing} />
          </section>
        </div>
        <Sidebar listing={listing} />
      </div>
    </div>
  );
}

export function ListingRoute() {
  const { id } = useParams<{ id: string }>();
  return <ListingView id={Number(id)} />;
}
