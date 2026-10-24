"use client";

import { useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useBars } from "@/lib/queries";
import { buildFillMarkers, MARKER_STYLES } from "@/lib/chart-markers";
import { formatPrice, toNumber } from "@/lib/format";
import type { Order } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PriceChart, indicatorColor, type ChartPriceLine, type HoverBar } from "./price-chart";

// Every pair is one the backend allows (see the interval/range table).
const TIMEFRAMES = [
  { id: "1D", interval: "5m", range: "1d" },
  { id: "5D", interval: "15m", range: "5d" },
  { id: "1M", interval: "1h", range: "1mo" },
  { id: "6M", interval: "1d", range: "6mo" },
  { id: "1Y", interval: "1d", range: "1y" },
  { id: "MAX", interval: "1wk", range: "max" },
] as const;

const INDICATORS = [
  { id: "sma:20", label: "SMA 20" },
  { id: "sma:50", label: "SMA 50" },
  { id: "ema:20", label: "EMA 20" },
  { id: "rsi:14", label: "RSI 14" },
] as const;

const INTRADAY = new Set(["1m", "5m", "15m", "30m", "1h"]);

type Props = {
  symbol: string;
  currency: string;
  /** This symbol's orders; the filled ones become arrows on the bar they filled in. */
  orders?: Order[];
  /** IANA zone of the exchange, which the bars' clock and the fill times are read in. */
  timeZone?: string;
  priceLines?: ChartPriceLine[];
};

export function ChartPanel({ symbol, currency, orders, timeZone, priceLines }: Props) {
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]["id"]>("6M");
  const [active, setActive] = useState<string[]>(["sma:20"]);
  const [hover, setHover] = useState<HoverBar | null>(null);

  const tf = TIMEFRAMES.find((t) => t.id === timeframe) ?? TIMEFRAMES[3];
  // Sorted so toggling in a different order reuses the same cache entry.
  const indicatorParam = useMemo(() => [...active].sort(), [active]);
  const { data, isPending, isFetching, error } = useBars(symbol, tf.interval, tf.range, indicatorParam);

  const bars = useMemo(() => data?.bars ?? [], [data]);
  const indicators = useMemo(() => data?.indicators ?? [], [data]);
  const intraday = INTRADAY.has(data?.interval ?? tf.interval);
  const markers = useMemo(
    () => buildFillMarkers(orders ?? [], bars, intraday, timeZone),
    [orders, bars, intraday, timeZone],
  );
  const lastBar = bars.length ? bars[bars.length - 1] : null;
  const shown: HoverBar | null =
    hover ??
    (lastBar
      ? {
          open: toNumber(lastBar.open),
          high: toNumber(lastBar.high),
          low: toNumber(lastBar.low),
          close: toNumber(lastBar.close),
          volume: toNumber(lastBar.volume),
        }
      : null);

  const fmt = (n: number) => formatPrice(n, data?.currency ?? currency);

  return (
    <Card>
      <CardContent className="grid min-w-0 gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <ToggleGroup
            variant="outline"
            size="sm"
            spacing={0}
            aria-label="Timeframe"
            value={[timeframe]}
            onValueChange={(v) => {
              const next = TIMEFRAMES.find((t) => t.id === v[0]);
              if (next) setTimeframe(next.id);
            }}
          >
            {TIMEFRAMES.map((t) => (
              <ToggleGroupItem key={t.id} value={t.id}>
                {t.id}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Indicators">
            {INDICATORS.map((ind) => (
              <Toggle
                key={ind.id}
                variant="outline"
                size="sm"
                pressed={active.includes(ind.id)}
                onPressedChange={(on) =>
                  setActive((cur) => (on ? [...cur.filter((c) => c !== ind.id), ind.id] : cur.filter((c) => c !== ind.id)))
                }
              >
                {ind.label}
              </Toggle>
            ))}
          </div>
        </div>

        <div className="flex min-h-5 flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular-nums">
          {shown && (
            <span className="text-muted-foreground">
              <span className="mr-2">O {fmt(shown.open)}</span>
              <span className="mr-2">H {fmt(shown.high)}</span>
              <span className="mr-2">L {fmt(shown.low)}</span>
              <span className="mr-2">C {fmt(shown.close)}</span>
              {shown.volume !== null && <span>Vol {new Intl.NumberFormat("en-US", { notation: "compact" }).format(shown.volume)}</span>}
            </span>
          )}
          {priceLines?.some((l) => l.title === "Break-even") && (
            <span className="inline-flex items-center gap-1.5 text-muted-foreground">
              <span className="inline-block w-3 border-t-2 border-dashed border-current" />
              Break-even: the price you need to sell at to get back everything you paid, charges included.
            </span>
          )}
          {priceLines?.some((l) => l.title === "Stop" || l.title === "Target") && (
            <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
              {priceLines.some((l) => l.title === "Stop") && (
                <span className="inline-flex items-center gap-1.5">
                  <span className="inline-block w-3 border-t-2 border-dashed border-red-600" />
                  Stop: closes the trade at the market price if the price reaches it, to limit a loss.
                </span>
              )}
              {priceLines.some((l) => l.title === "Target") && (
                <span className="inline-flex items-center gap-1.5">
                  <span className="inline-block w-3 border-t-2 border-dashed border-green-600" />
                  Target: closes the trade at the market price if the price reaches it, to take a profit.
                </span>
              )}
            </span>
          )}
          {markers.length > 0 && (
            <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
              <span>Arrows mark your fills:</span>
              {Object.values(MARKER_STYLES).map((m) => (
                <span key={m.label} className="inline-flex items-center gap-1">
                  <span style={{ color: m.color }} aria-hidden>
                    {m.shape === "arrowUp" ? "▲" : "▼"}
                  </span>
                  {m.label}
                </span>
              ))}
            </span>
          )}
          {indicators.map((ind, i) => (
            <span key={`${ind.name}:${ind.period}`} className="inline-flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-3 rounded" style={{ background: indicatorColor(ind, i) }} />
              {ind.label}
            </span>
          ))}
        </div>

        {error && !data ? (
          <p role="alert" className="py-16 text-center text-sm text-destructive">
            {error.message}
          </p>
        ) : isPending ? (
          <Skeleton className="h-[420px] w-full sm:h-[480px]" />
        ) : bars.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">
            No price history is available for this timeframe.
          </p>
        ) : (
          <PriceChart
            bars={bars}
            indicators={indicators}
            intraday={intraday}
            markers={markers}
            priceLines={priceLines}
            onHover={setHover}
            className={cn("h-[420px] w-full min-w-0 transition-opacity sm:h-[480px]", isFetching && "opacity-60")}
          />
        )}

        <details className="group text-sm">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-muted-foreground hover:text-foreground">
            <ChevronRight className="size-4 transition-transform group-open:rotate-90" />
            What&apos;s a candle?
          </summary>
          <div className="mt-2 grid gap-2 text-muted-foreground">
            <p>
              Each candle shows how the price moved over one period (a day, an hour, and so on). The thick
              body runs from the price at the start of the period (open) to the price at the end (close). It
              is green when the price closed higher than it opened, and red when it closed lower. The thin
              lines above and below, the wicks, reach the highest and lowest prices reached in that period.
            </p>
            <p>
              The faint bars along the bottom are volume: how many shares traded in that period. Tall bars
              mean busy trading.
            </p>
            <ul className="grid gap-1">
              <li>
                <strong className="text-foreground">SMA</strong> (simple moving average): the average closing
                price over the last N periods, a smoothed line that shows the general direction.
              </li>
              <li>
                <strong className="text-foreground">EMA</strong> (exponential moving average): like an SMA but
                it gives more weight to recent prices, so it reacts faster.
              </li>
              <li>
                <strong className="text-foreground">RSI</strong> (relative strength index): a 0 to 100 gauge
                of how strongly the price has been rising or falling lately. As a rule of thumb, above 70 is
                often called overbought and below 30 oversold. It is a common reading, not a prediction.
              </li>
            </ul>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}
