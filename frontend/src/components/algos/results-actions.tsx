"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useCreateMyAlgo, useCreateSimSession, useHistoryLimits } from "@/lib/queries";
import type { BacktestResults } from "@/lib/types";

const DAY_MS = 86_400_000;
const isoDay = (ms: number) => new Date(ms).toISOString().slice(0, 10);

/**
 * A recent stretch the strategy's bars exist for: the last 30 days for daily bars, the last 7
 * for finer ones, never before the earliest day that interval is served. Ends on the last
 * weekday before today (any day for crypto, which trades at weekends).
 */
export function simWindow(
  interval: string,
  today: string,
  earliest: string | null,
  weekends: boolean,
): { start: string; end: string } {
  let end = Date.parse(`${today}T00:00:00Z`) - DAY_MS;
  while (!weekends && [0, 6].includes(new Date(end).getUTCDay())) end -= DAY_MS;
  const length = interval === "1d" ? 30 : 7;
  let start = isoDay(end - length * DAY_MS);
  if (earliest && start < earliest) start = earliest;
  return { start, end: isoDay(end) };
}

function SaveDialog({
  results,
  open,
  onOpenChange,
}: {
  results: BacktestResults;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const save = useCreateMyAlgo();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    save.mutate(
      { name, description, strategy: results.strategy_key, params: results.params },
      {
        onSuccess: (saved) => {
          toast.success(`Saved "${saved.name}" to My algorithms.`);
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Save as my algorithm</DialogTitle>
            <DialogDescription>
              Keeps {results.strategy_name} with the settings of this run, so you can open it in the lab again.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="algo-name">Name</Label>
            <Input id="algo-name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="algo-description">Description (optional)</Label>
            <Textarea
              id="algo-description"
              value={description}
              maxLength={500}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          {save.error && (
            <p role="alert" className="text-sm text-destructive">
              {save.error.message}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={!name.trim() || save.isPending}>
              {save.isPending ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ResultsActions({ results }: { results: BacktestResults }) {
  const router = useRouter();
  const limits = useHistoryLimits();
  const createSim = useCreateSimSession();
  const [saving, setSaving] = useState(false);
  const first = results.instruments[0];

  function openInSim() {
    if (!limits.data || !first) return;
    const earliest = limits.data.limits.find((l) => l.interval === results.interval)?.earliest ?? null;
    const { start, end } = simWindow(results.interval, limits.data.today, earliest, first.market === "crypto");
    createSim.mutate(
      { symbols: [first.symbol], interval: results.interval, start_date: start, end_date: end, speed: 60 },
      { onSuccess: (s) => router.push(`/sim/${s.id}`) },
    );
  }

  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={() => setSaving(true)}>
          Save as my algorithm
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!limits.data || !first || createSim.isPending}
          onClick={openInSim}
          title={first ? `Opens the simulation with ${first.symbol} on a recent day` : undefined}
        >
          {createSim.isPending ? "Opening..." : "Run in the virtual sim"}
        </Button>
        <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/algos/backtests" />}>
          Backtest history
        </Button>
      </div>
      {createSim.error && (
        <p role="alert" className="text-sm text-destructive">
          {createSim.error.message}
        </p>
      )}
      {saving && <SaveDialog results={results} open onOpenChange={setSaving} />}
    </div>
  );
}
