"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { InfoIcon, TriangleAlertIcon } from "lucide-react";
import { DirectionBadge } from "@/components/trades-table";
import { Pnl } from "@/components/pnl";
import { Term } from "@/components/term";
import { PriceChart } from "@/components/trade/price-chart";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  algoIntervalWords,
  categoryLabel,
  chartRangeFor,
  closedHowLabel,
  formatPlain,
  isIntraday,
} from "@/lib/algo-format";
import { buildFillMarkers, MARKER_STYLES } from "@/lib/chart-markers";
import {
  formatMoney,
  formatPercent,
  formatPrice,
  formatQuantity,
  formatRatio,
  isZero,
  parseApiTime,
  toNumber,
} from "@/lib/format";
import type { TermId } from "@/lib/glossary";
import { useBars, useHistoryLimits, useQuote } from "@/lib/queries";
import { formatDay } from "@/lib/sim-format";
import type { BacktestDetail, BacktestResults, BacktestTrade } from "@/lib/types";
import { QueryError } from "@/components/query-error";
import { ResultsActions } from "./results-actions";
import { SeriesChart, type ChartLine } from "./series-chart";

const EMPTY: never[] = [];
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

function ChargesCard({ results }: { results: BacktestResults }) {
  const m = results.metrics;
  const currency = results.account_currency;
  const categories = Object.entries(m.charges_by_category).filter(([, v]) => !isZero(v));
  return (
    <Card className="border-primary/40 bg-primary/5">
      <CardHeader>
        <CardTitle>What trading cost</CardTitle>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <p className="text-sm text-muted-foreground">Total charges</p>
            <p className="text-3xl font-semibold tabular-nums" data-testid="total-charges">
              {formatMoney(m.total_charges, currency)}
            </p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Charges as % of gross profit</p>
            <p className="text-3xl font-semibold tabular-nums" data-testid="charges-pct">
              {m.charges_pct_of_gross_profit === null ? "—" : formatRatio(m.charges_pct_of_gross_profit, "%")}
            </p>
            <p className="text-xs text-muted-foreground">
              {m.gross_profit === null
                ? "No winning trades, so there is no gross profit to compare against."
                : `Gross profit from winning trades: ${formatMoney(m.gross_profit, currency)}`}
            </p>
          </div>
        </div>
        {(categories.length > 0 || !isZero(m.financing_paid)) && (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3 lg:grid-cols-4">
            {categories.map(([key, v]) => (
              <div key={key} className="flex justify-between gap-2 border-b py-1">
                <dt className="text-muted-foreground">{categoryLabel(key)}</dt>
                <dd className="tabular-nums">{formatMoney(v, currency)}</dd>
              </div>
            ))}
            {!isZero(m.financing_paid) && (
              <div className="flex justify-between gap-2 border-b py-1">
                <dt className="text-muted-foreground">Financing</dt>
                <dd className="tabular-nums">{formatMoney(m.financing_paid, currency)}</dd>
              </div>
            )}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function MetricCards({ results }: { results: BacktestResults }) {
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
      <Stat
        label="Trades"
        value={m.trades_closed}
        note={m.trades_open > 0 ? `${m.trades_open} still open at the end` : "All closed"}
      />
      <Stat label="Exposure" term="exposure" value={formatRatio(m.exposure_pct, "%")} note="Share of bars with a position open" />
    </div>
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

function Curves({ results }: { results: BacktestResults }) {
  const intraday = isIntraday(results.interval);
  const equity = useMemo<ChartLine[]>(
    () => [
      {
        name: "Buy and hold",
        color: COLOR_HOLD,
        points: results.equity_curve.map((p) => ({ at: p.at, value: toNumber(p.buy_hold_equity) })),
      },
      {
        name: "Strategy",
        color: COLOR_STRATEGY,
        points: results.equity_curve.map((p) => ({ at: p.at, value: toNumber(p.equity) })),
      },
    ],
    [results],
  );
  const drawdown = useMemo<ChartLine[]>(
    () => [
      {
        name: "Buy and hold",
        color: COLOR_HOLD,
        points: results.drawdown.map((p) => ({ at: p.at, value: toNumber(p.buy_hold_pct) })),
      },
      {
        name: "Strategy",
        color: COLOR_DRAWDOWN,
        area: true,
        points: results.drawdown.map((p) => ({ at: p.at, value: toNumber(p.strategy_pct) })),
      },
    ],
    [results],
  );
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Equity: strategy against buy and hold</CardTitle>
        </CardHeader>
        <CardContent className="grid min-w-0 gap-2">
          <Legend
            items={[
              { label: "Strategy", color: COLOR_STRATEGY },
              { label: "Buy and hold (same symbols, equal weight, real charges)", color: COLOR_HOLD },
            ]}
          />
          <SeriesChart lines={equity} intraday={intraday} format={formatEquity} className="h-72 w-full" />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Drawdown</CardTitle>
        </CardHeader>
        <CardContent className="grid min-w-0 gap-2">
          <Legend
            items={[
              { label: "Strategy", color: COLOR_DRAWDOWN },
              { label: "Buy and hold", color: COLOR_HOLD },
            ]}
          />
          <SeriesChart lines={drawdown} intraday={intraday} format={formatDrawdown} className="h-72 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}

function SymbolChart({ results, symbol, today }: { results: BacktestResults; symbol: string; today: string }) {
  const intraday = isIntraday(results.interval);
  const first = results.first_bar.slice(0, 10);
  const last = results.last_bar.slice(0, 10);
  const range = chartRangeFor(results.interval, first, today);
  const barsQuery = useBars(symbol, results.interval, range);
  const quote = useQuote(symbol);
  const bars = useMemo(() => {
    const all = barsQuery.data?.bars ?? [];
    // Daily bars are keyed by date, so the run's own window can be cut out exactly.
    return intraday ? all : all.filter((b) => String(b.time) >= first && String(b.time) <= last);
  }, [barsQuery.data, intraday, first, last]);
  const markers = useMemo(
    () =>
      buildFillMarkers(
        results.orders.filter((o) => o.symbol === symbol),
        bars,
        intraday,
        quote.data?.market?.timezone,
      ),
    [results.orders, bars, intraday, quote.data?.market?.timezone, symbol],
  );

  if (barsQuery.error && !barsQuery.data) {
    return <QueryError error={barsQuery.error} title="Couldn't load the price chart" onRetry={() => barsQuery.refetch()} />;
  }
  if (!barsQuery.data) return <Skeleton className="h-80 w-full" />;
  return (
    <div className="grid min-w-0 gap-2">
      <div className="flex min-h-5 flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {Object.values(MARKER_STYLES).map((m) => (
          <span key={m.label} className="inline-flex items-center gap-1.5">
            <span className="inline-block size-2 rounded-full" style={{ backgroundColor: m.color }} />
            {m.label}
          </span>
        ))}
        {markers.length === 0 && <span>No fills on this symbol.</span>}
      </div>
      <PriceChart bars={bars} indicators={EMPTY} intraday={intraday} markers={markers} className="h-80 w-full" />
    </div>
  );
}

function PriceSection({ results }: { results: BacktestResults }) {
  const limits = useHistoryLimits();
  const symbols = results.instruments.map((i) => i.symbol);
  const [picked, setPicked] = useState<string | null>(null);
  const symbol = picked && symbols.includes(picked) ? picked : symbols[0];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Price and fills</CardTitle>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-3">
        {symbols.length > 1 && (
          <ToggleGroup
            variant="outline"
            size="sm"
            spacing={0}
            aria-label="Symbol"
            value={[symbol]}
            onValueChange={(v) => v[0] && setPicked(v[0])}
            className="flex-wrap"
          >
            {symbols.map((s) => (
              <ToggleGroupItem key={s} value={s}>
                {s}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
        {limits.data ? <SymbolChart key={symbol} results={results} symbol={symbol} today={limits.data.today} /> : <Skeleton className="h-80 w-full" />}
      </CardContent>
    </Card>
  );
}

function formatWhen(iso: string, intraday: boolean): string {
  const d = parseApiTime(iso);
  if (!intraday) return formatDay(d.toISOString().slice(0, 10));
  return `${new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "UTC" }).format(d)} UTC`;
}

function TradeRow({ t, currency, intraday }: { t: BacktestTrade; currency: string; intraday: boolean }) {
  const cats = Object.entries(t.charges_by_category).filter(([, v]) => !isZero(v));
  return (
    <TableRow>
      <TableCell className="whitespace-nowrap font-medium">{t.symbol}</TableCell>
      <TableCell>
        <DirectionBadge direction={t.direction} />
      </TableCell>
      <TableCell className="text-right tabular-nums">{formatQuantity(t.quantity)}</TableCell>
      <TableCell className="whitespace-nowrap">
        <div>{formatWhen(t.entry_at, intraday)}</div>
        <div className="text-xs text-muted-foreground tabular-nums">{formatPrice(t.entry_price, t.currency)}</div>
      </TableCell>
      <TableCell className="whitespace-nowrap">
        {t.exit_at && t.exit_price ? (
          <>
            <div>{formatWhen(t.exit_at, intraday)}</div>
            <div className="text-xs text-muted-foreground tabular-nums">{formatPrice(t.exit_price, t.currency)}</div>
          </>
        ) : (
          "—"
        )}
      </TableCell>
      <TableCell>
        <Badge variant={t.status === "open" ? "secondary" : "outline"}>{closedHowLabel(t.closed_how)}</Badge>
      </TableCell>
      <TableCell className="text-right">{t.gross_pnl === null ? "—" : <Pnl value={t.gross_pnl} currency={currency} />}</TableCell>
      <TableCell className="text-right">
        <div className="tabular-nums">{formatMoney(t.charges_total, currency)}</div>
        {cats.length > 0 && (
          <div className="ml-auto max-w-56 text-xs whitespace-normal text-muted-foreground">
            {cats.map(([k, v]) => `${categoryLabel(k)} ${formatMoney(v, currency)}`).join(" · ")}
          </div>
        )}
      </TableCell>
      <TableCell className="text-right">
        {t.realized_pnl !== null ? (
          <Pnl value={t.realized_pnl} currency={currency} />
        ) : t.unrealized_pnl !== null ? (
          <span title="Open: marked at the last price">
            <Pnl value={t.unrealized_pnl} currency={currency} /> open
          </span>
        ) : (
          "—"
        )}
      </TableCell>
    </TableRow>
  );
}

function TradesSection({ results }: { results: BacktestResults }) {
  const intraday = isIntraday(results.interval);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Trades ({results.trades.length})</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        {results.trades.length === 0 ? (
          <p className="text-sm text-muted-foreground">The strategy placed no trades in this range.</p>
        ) : (
          <div className="max-h-[32rem] min-w-0 overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead>Entered</TableHead>
                  <TableHead>Exited</TableHead>
                  <TableHead>Closed how</TableHead>
                  <TableHead className="text-right">Gross P&amp;L</TableHead>
                  <TableHead className="text-right">Charges</TableHead>
                  <TableHead className="text-right">Net P&amp;L</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.trades.map((t) => (
                  <TradeRow key={t.id} t={t} currency={results.account_currency} intraday={intraday} />
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function LogSection({ results }: { results: BacktestResults }) {
  return (
    <Card>
      <CardContent className="min-w-0">
        <details>
          <summary className="cursor-pointer text-sm font-medium">Strategy log ({results.logs.length} lines)</summary>
          {results.logs.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">The strategy wrote nothing to its log.</p>
          ) : (
            <pre className="mt-2 max-h-96 overflow-auto rounded-lg bg-muted/50 p-3 text-xs whitespace-pre-wrap">
              {results.logs.map((l) => `${l.at.slice(0, 16).replace("T", " ")}  ${l.text}`).join("\n")}
            </pre>
          )}
        </details>
      </CardContent>
    </Card>
  );
}

/** `actions={false}` hides the save / run-in-sim buttons (they need a library strategy, not code). */
export function ResultsView({ detail, actions = true }: { detail: BacktestDetail; actions?: boolean }) {
  const results = detail.results;
  if (!results) return null;
  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 basis-60">
          <h2 className="text-xl font-semibold tracking-tight">{results.strategy_name}</h2>
          <p className="text-sm text-muted-foreground">
            {results.instruments.map((i) => i.symbol).join(", ")} · {algoIntervalWords(results.interval)} bars ·{" "}
            {formatDay(detail.start_date)} to {formatDay(detail.end_date)} · {results.bars} bars played ·{" "}
            starting cash {formatMoney(detail.starting_cash, results.account_currency)}
          </p>
        </div>
        {actions && <ResultsActions results={results} />}
      </div>

      {results.notes.length > 0 && (
        <Alert>
          <InfoIcon />
          <AlertTitle>Worth knowing</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {results.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {results.errors.length > 0 && (
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertTitle>The strategy raised errors</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {results.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      <ChargesCard results={results} />
      <MetricCards results={results} />
      <Curves results={results} />
      <PriceSection results={results} />
      <TradesSection results={results} />
      <LogSection results={results} />
      <p className="text-xs text-muted-foreground">
        <Link href="/algos/backtests" className="underline underline-offset-2">
          All backtests
        </Link>
      </p>
    </div>
  );
}
