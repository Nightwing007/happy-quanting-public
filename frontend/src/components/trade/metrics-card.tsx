"use client";

import { QueryError } from "@/components/query-error";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatLargeAmount, formatPrice, formatRatio } from "@/lib/format";
import { useMetrics } from "@/lib/queries";
import type { Metric } from "@/lib/types";

function displayValue(m: Metric, currency: string): string {
  switch (m.display_hint) {
    case "amount":
      return formatLargeAmount(m.value, currency);
    case "count":
      return formatLargeAmount(m.value);
    default:
      return formatRatio(m.value, m.unit);
  }
}

const BETTER: Record<Metric["better"], string> = {
  lower: "Lower is usually the more comfortable side.",
  higher: "Higher is usually the more comfortable side.",
  depends: "Neither high nor low is simply better; it depends on the company.",
};

function Help({ m, currency }: { m: Metric; currency: string }) {
  const range = m.range;
  return (
    <div className="grid gap-1.5 py-0.5">
      <p>{m.explanation}</p>
      {m.assessment && range && (
        <p>
          <span className="font-medium">
            {range.label === "All sectors" ? "Across all sectors" : range.label}:
          </span>{" "}
          usually {formatRatio(range.low, "").trim()}–{formatRatio(range.high, m.unit)}
        </p>
      )}
      {m.display_hint === "position" && range && (
        <p>
          52-week low {formatPrice(range.low, currency)}, high {formatPrice(range.high, currency)}
        </p>
      )}
      {m.assessment && (
        <>
          <p>
            <span className="font-medium">Below that:</span> {m.if_below}
          </p>
          <p>
            <span className="font-medium">Above that:</span> {m.if_above}
          </p>
          <p className="opacity-80">{BETTER[m.better]}</p>
        </>
      )}
      {!m.assessment && <p className="opacity-80">{m.meaning}</p>}
    </div>
  );
}

function MetricRow({ m, currency }: { m: Metric; currency: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <dt className="text-muted-foreground">
        <Tooltip>
          <TooltipTrigger
            render={<span tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-4" />}
          >
            {m.label}
          </TooltipTrigger>
          <TooltipContent className="block max-w-sm">
            <Help m={m} currency={currency} />
          </TooltipContent>
        </Tooltip>
      </dt>
      <dd className="flex items-center gap-2">
        <span className="text-base font-medium tabular-nums">{displayValue(m, currency)}</span>
        {/* Neutral colours on purpose: outside the range is information, not a verdict. */}
        {m.assessment && (
          <Badge variant={m.assessment === "typical" ? "secondary" : "outline"}>{m.assessment}</Badge>
        )}
      </dd>
      {m.display_hint === "position" && m.range && (
        <div className="basis-full">
          <div className="h-1.5 w-full rounded-full bg-muted">
            <div
              className="h-1.5 rounded-full bg-foreground/60"
              style={{ width: `${Math.min(100, Math.max(0, Number(m.value)))}%` }}
            />
          </div>
          <div className="mt-1 flex justify-between text-xs text-muted-foreground tabular-nums">
            <span>{formatPrice(m.range.low, currency)}</span>
            <span>{formatPrice(m.range.high, currency)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

export function MetricsCard({ symbol }: { symbol: string }) {
  const { data, isPending, error, refetch } = useMetrics(symbol);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{data?.kind === "crypto" ? "Coin metrics" : "Company metrics"}</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        {isPending && <Skeleton className="h-32 w-full" />}
        {error && !data && <QueryError error={error} title="Couldn't load the metrics" onRetry={() => refetch()} />}
        {data && (
          <div className="grid gap-3 text-sm">
            {data.metrics.length === 0 && data.omitted.length === 0 && (
              <p className="text-muted-foreground">
                {data.kind === "other"
                  ? data.note
                  : `No company figures are available for ${data.symbol} right now.`}
              </p>
            )}
            {data.metrics.length > 0 && (
              <dl className="grid gap-2.5">
                {data.metrics.map((m) => (
                  <MetricRow key={m.key} m={m} currency={data.currency} />
                ))}
              </dl>
            )}
            {data.omitted.map((o) => (
              <p key={o.key} className="text-xs text-muted-foreground">
                <span className="font-medium">{o.label}</span> isn&apos;t shown: {o.reason}
              </p>
            ))}
            {data.kind !== "other" && <p className="text-xs text-muted-foreground">{data.note}</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
