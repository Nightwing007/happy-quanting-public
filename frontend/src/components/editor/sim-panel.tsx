"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { TriangleAlertIcon } from "lucide-react";
import { simWindow } from "@/components/algos/results-actions";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { algoIntervalWords } from "@/lib/algo-format";
import { useCreateSimSession, useHistoryLimits } from "@/lib/queries";
import { formatDay } from "@/lib/sim-format";
import type { StrategyMeta } from "@/lib/types";

/** Starts a virtual-sim session that runs the code as written, then opens it. */
export function SimPanel({ source, meta, symbols }: { source: string; meta: StrategyMeta; symbols: string[] }) {
  const router = useRouter();
  const limits = useHistoryLimits();
  const create = useCreateSimSession();
  const [start, setStart] = useState<string | null>(null);
  const [end, setEnd] = useState<string | null>(null);

  const today = limits.data?.today ?? null;
  const earliest = limits.data?.limits.find((l) => l.interval === meta.interval)?.earliest ?? null;
  const suggested = today
    ? simWindow(meta.interval, today, earliest, meta.markets.length === 1 && meta.markets[0] === "crypto")
    : null;
  const startDay = start ?? suggested?.start ?? "";
  const endDay = end ?? suggested?.end ?? "";

  const problem =
    !startDay || !endDay || !today
      ? null
      : earliest && startDay < earliest
        ? `${algoIntervalWords(meta.interval)} data only goes back to ${formatDay(earliest)}.`
        : endDay < startDay
          ? "The last day cannot be before the first day."
          : endDay > today
            ? "The last day cannot be in the future."
            : null;
  const canRun = symbols.length > 0 && !!startDay && !!endDay && !problem && !create.isPending;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canRun) return;
    create.mutate(
      {
        symbols,
        interval: meta.interval,
        start_date: startDay,
        end_date: endDay,
        speed: 60,
        strategy: { kind: "source", source },
      },
      { onSuccess: (s) => router.push(`/sim/${s.id}`) },
    );
  }

  return (
    <form onSubmit={submit} className="grid min-w-0 gap-4">
      <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="grid content-start gap-1.5">
          <Label htmlFor="ed-sim-start">First day</Label>
          <Input
            id="ed-sim-start"
            type="date"
            value={startDay}
            min={earliest ?? undefined}
            max={today ?? undefined}
            onChange={(e) => setStart(e.target.value)}
          />
        </div>
        <div className="grid content-start gap-1.5">
          <Label htmlFor="ed-sim-end">Last day</Label>
          <Input
            id="ed-sim-end"
            type="date"
            value={endDay}
            min={startDay || undefined}
            max={today ?? undefined}
            onChange={(e) => setEnd(e.target.value)}
          />
        </div>
        <p
          className={`text-xs sm:col-span-2 ${problem ? "text-destructive" : "text-muted-foreground"}`}
          role={problem ? "alert" : undefined}
        >
          {problem ?? "Replays these days bar by bar with your code trading on the symbols chosen above."}
        </p>
      </div>
      {create.error && (
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertDescription>{create.error.message}</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={!canRun}>
          {create.isPending ? "Opening..." : "Run in the virtual sim"}
        </Button>
        {symbols.length === 0 && <span className="text-xs text-muted-foreground">Add at least one symbol.</span>}
      </div>
    </form>
  );
}
