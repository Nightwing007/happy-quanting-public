"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { TriangleAlertIcon } from "lucide-react";
import { SymbolSearch } from "@/components/symbol-search";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useCreateSimSession, useHistoryLimits } from "@/lib/queries";
import { formatDay, intervalWords, SIM_INTERVALS } from "@/lib/sim-format";

/** The latest weekday before `today` ("YYYY-MM-DD"), a sensible first day to replay. */
function lastWeekday(today: string): string {
  const d = new Date(`${today}T00:00:00Z`);
  do d.setUTCDate(d.getUTCDate() - 1);
  while (d.getUTCDay() === 0 || d.getUTCDay() === 6);
  return d.toISOString().slice(0, 10);
}

export function NewSimForm() {
  const router = useRouter();
  const limits = useHistoryLimits();
  const create = useCreateSimSession();
  const [symbol, setSymbol] = useState<string | null>(null);
  const [interval, setInterval] = useState<string>("1m");
  const [start, setStart] = useState<string | null>(null);
  const [end, setEnd] = useState("");
  const [speed, setSpeed] = useState(60);

  const today = limits.data?.today ?? null;
  const earliest = limits.data?.limits.find((l) => l.interval === interval)?.earliest ?? null;
  // Until the person picks a day, suggest the last weekday, or the earliest one allowed if that is too old.
  const suggested = useMemo(() => {
    if (!today) return "";
    const day = lastWeekday(today);
    return earliest && day < earliest ? earliest : day;
  }, [today, earliest]);
  const startDay = start ?? suggested;
  const endDay = end || startDay;

  const problem =
    !startDay || !today
      ? null
      : earliest && startDay < earliest
        ? `${intervalWords(interval)} data only goes back to ${formatDay(earliest)}.`
        : endDay < startDay
          ? "The last day cannot be before the first day."
          : endDay > today
            ? "The last day cannot be in the future."
            : null;
  const canSubmit = !!symbol && !!startDay && !problem && !create.isPending;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || !symbol) return;
    create.mutate(
      { symbols: [symbol], interval, start_date: startDay, end_date: endDay, speed },
      { onSuccess: (s) => router.push(`/sim/${s.id}`) },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>New simulation</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        <form onSubmit={submit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="grid content-start gap-1.5">
            <Label>Symbol</Label>
            <SymbolSearch
              onSelect={setSymbol}
              className="w-full justify-start"
              label={<span className={symbol ? "font-medium text-foreground" : ""}>{symbol ?? "Search for a symbol..."}</span>}
            />
          </div>

          <div className="grid content-start gap-1.5">
            <Label>Bar size</Label>
            <ToggleGroup
              variant="outline"
              size="sm"
              spacing={0}
              aria-label="Bar size"
              value={[interval]}
              onValueChange={(v) => v[0] && setInterval(v[0])}
            >
              {SIM_INTERVALS.map((i) => (
                <ToggleGroupItem key={i.id} value={i.id}>
                  {i.id}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>

          <div className="grid content-start gap-1.5">
            <Label htmlFor="sim-start">First day</Label>
            <Input
              id="sim-start"
              type="date"
              value={startDay}
              min={earliest ?? undefined}
              max={today ?? undefined}
              onChange={(e) => setStart(e.target.value)}
            />
          </div>
          <div className="grid content-start gap-1.5">
            <Label htmlFor="sim-end">Last day (empty for one day)</Label>
            <Input
              id="sim-end"
              type="date"
              value={end}
              min={startDay || undefined}
              max={today ?? undefined}
              onChange={(e) => setEnd(e.target.value)}
            />
          </div>

          <p
            className={`text-xs sm:col-span-2 ${problem ? "text-destructive" : "text-muted-foreground"}`}
            role={problem ? "alert" : undefined}
          >
            {problem ??
              (earliest
                ? `${intervalWords(interval)} data only goes back to ${formatDay(earliest)}, so earlier days are disabled.`
                : `${intervalWords(interval)} data has no earliest date.`)}
          </p>

          <div className="grid gap-1.5 sm:col-span-2">
            <Label htmlFor="sim-speed">
              Speed: <span className="tabular-nums">{speed}</span> bars per second
            </Label>
            <input
              id="sim-speed"
              type="range"
              min={1}
              max={200}
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
              className="w-full accent-primary"
            />
          </div>

          {create.error && (
            <Alert variant="destructive" className="sm:col-span-2">
              <TriangleAlertIcon />
              <AlertDescription>{create.error.message}</AlertDescription>
            </Alert>
          )}

          <div className="sm:col-span-2">
            <Button type="submit" disabled={!canSubmit}>
              {create.isPending ? "Creating..." : "Start simulation"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
