"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { PlusIcon, TriangleAlertIcon, XIcon } from "lucide-react";
import { QueryError } from "@/components/query-error";
import { SymbolSearch } from "@/components/symbol-search";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { algoIntervalWords, historyLimitsText, MARKET_LABELS, paramPayload, paramProblem } from "@/lib/algo-format";
import {
  useAlgoLibrary,
  useBacktest,
  useBrokers,
  useHistoryLimits,
  useMyAlgos,
  useRunBacktest,
  useSettings,
} from "@/lib/queries";
import { formatDay } from "@/lib/sim-format";
import type { Algo, BacktestIn, UserAlgo } from "@/lib/types";
import { BacktestOutcome } from "./backtest-outcome";
import { initialValues, ParamForm, type ParamValues } from "./param-form";

const MAX_SYMBOLS = 10;
const SEGMENT_FIELD = { india: "broker_india", international: "broker_international", crypto: "broker_crypto" } as const;

const yearBefore = (day: string) => {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCFullYear(d.getUTCFullYear() - 1);
  return d.toISOString().slice(0, 10);
};

type Chosen = Partial<Record<keyof typeof SEGMENT_FIELD, string>>;

function LabForm({ algo, mine }: { algo: Algo; mine: UserAlgo | null }) {
  const limits = useHistoryLimits();
  const brokerGroups = useBrokers();
  const settings = useSettings();
  const run = useRunBacktest();
  const [values, setValues] = useState<ParamValues>(() => initialValues(algo, mine?.params));
  const [symbols, setSymbols] = useState<string[]>([]);
  const [start, setStart] = useState<string | null>(null);
  const [end, setEnd] = useState<string | null>(null);
  const [cash, setCash] = useState("");
  const [chosen, setChosen] = useState<Chosen>({});
  const [runId, setRunId] = useState<number | null>(null);
  const backtest = useBacktest(runId);

  const today = limits.data?.today ?? null;
  const earliest = limits.data?.limits.find((l) => l.interval === algo.interval)?.earliest ?? null;
  const endDay = end ?? today ?? "";
  const startDay = useMemo(() => {
    if (start !== null) return start;
    if (!today) return "";
    const year = yearBefore(today);
    return earliest && year < earliest ? earliest : year;
  }, [start, today, earliest]);

  const fieldProblems = algo.parameters.filter((p) => paramProblem(p, values[p.name] ?? p.default) !== null);
  const rangeProblem =
    !startDay || !endDay || !today
      ? null
      : earliest && startDay < earliest
        ? `${algoIntervalWords(algo.interval)} data only goes back to ${formatDay(earliest)}.`
        : endDay < startDay
          ? "The last day cannot be before the first day."
          : endDay > today
            ? "The last day cannot be in the future."
            : null;
  const cashProblem = cash.trim() !== "" && !(Number(cash) > 0) ? "Starting cash must be above zero." : null;
  const status = backtest.data?.status;
  const busy = run.isPending || status === "queued" || status === "running";
  const canRun = symbols.length > 0 && !fieldProblems.length && !rangeProblem && !cashProblem && !!startDay && !busy;

  function addSymbol(symbol: string) {
    const clean = symbol.trim().toUpperCase();
    setSymbols((cur) => (cur.includes(clean) || cur.length >= MAX_SYMBOLS ? cur : [...cur, clean]));
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canRun) return;
    const params: BacktestIn["params"] = {};
    for (const p of algo.parameters) params[p.name] = paramPayload(p, values[p.name] ?? p.default);
    const brokers = Object.fromEntries(Object.entries(chosen).filter(([, v]) => v));
    run.mutate(
      {
        ...(mine ? { algo_id: mine.id } : { strategy: algo.key }),
        params,
        symbols,
        interval: algo.interval,
        start_date: startDay,
        end_date: endDay,
        starting_cash: cash.trim() === "" ? null : cash.trim(),
        brokers: Object.keys(brokers).length ? brokers : null,
      },
      { onSuccess: (b) => setRunId(b.id) },
    );
  }

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <form onSubmit={submit} className="grid min-w-0 grid-cols-1 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Settings</CardTitle>
          </CardHeader>
          <CardContent className="grid min-w-0 gap-4">
            <ParamForm algo={algo} values={values} onChange={(name, v) => setValues((cur) => ({ ...cur, [name]: v }))} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>What to test it on</CardTitle>
          </CardHeader>
          <CardContent className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="grid content-start gap-1.5 sm:col-span-2">
              <Label>Symbols (up to {MAX_SYMBOLS})</Label>
              <div className="flex flex-wrap items-center gap-2">
                {symbols.map((s) => (
                  <Badge key={s} variant="secondary" className="gap-1 pr-1">
                    {s}
                    <button
                      type="button"
                      aria-label={`Remove ${s}`}
                      onClick={() => setSymbols((cur) => cur.filter((x) => x !== s))}
                      className="rounded-full p-0.5 hover:bg-foreground/10"
                    >
                      <XIcon className="size-3" />
                    </button>
                  </Badge>
                ))}
                {symbols.length < MAX_SYMBOLS && (
                  <SymbolSearch
                    onSelect={addSymbol}
                    label={
                      <>
                        <PlusIcon />
                        <span>{symbols.length ? "Add another" : "Add a symbol"}</span>
                      </>
                    }
                  />
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Markets this algorithm was written for: {algo.markets.map((m) => MARKET_LABELS[m] ?? m).join(", ")}.
              </p>
            </div>

            <div className="grid content-start gap-1.5">
              <Label htmlFor="lab-interval">Bar size</Label>
              <Input id="lab-interval" value={algoIntervalWords(algo.interval)} readOnly disabled />
              <p className="text-xs text-muted-foreground">Fixed: this algorithm is built for {algo.interval} bars.</p>
            </div>

            <div className="grid content-start gap-1.5">
              <Label htmlFor="lab-cash">Starting cash</Label>
              <Input
                id="lab-cash"
                type="number"
                inputMode="decimal"
                min="0"
                placeholder="Default starting cash"
                value={cash}
                aria-invalid={cashProblem ? true : undefined}
                onChange={(e) => setCash(e.target.value)}
              />
              {cashProblem && (
                <p role="alert" className="text-xs text-destructive">
                  {cashProblem}
                </p>
              )}
            </div>

            <div className="grid content-start gap-1.5">
              <Label htmlFor="lab-start">First day</Label>
              <Input
                id="lab-start"
                type="date"
                value={startDay}
                min={earliest ?? undefined}
                max={today ?? undefined}
                onChange={(e) => setStart(e.target.value)}
              />
            </div>
            <div className="grid content-start gap-1.5">
              <Label htmlFor="lab-end">Last day</Label>
              <Input
                id="lab-end"
                type="date"
                value={endDay}
                min={startDay || undefined}
                max={today ?? undefined}
                onChange={(e) => setEnd(e.target.value)}
              />
            </div>
            <p
              className={`text-xs sm:col-span-2 ${rangeProblem ? "text-destructive" : "text-muted-foreground"}`}
              role={rangeProblem ? "alert" : undefined}
            >
              {rangeProblem ?? (limits.data ? historyLimitsText(limits.data, formatDay) : "Loading the history limits...")}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Brokers</CardTitle>
          </CardHeader>
          <CardContent className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-3">
            {brokerGroups.data?.map((group) => {
              const field = SEGMENT_FIELD[group.segment as keyof typeof SEGMENT_FIELD];
              const mineCode = field ? settings.data?.[field] : undefined;
              const mineName = group.brokers.find((b) => b.code === mineCode)?.name;
              return (
                <div key={group.segment} className="grid content-start gap-1.5">
                  <Label htmlFor={`lab-broker-${group.segment}`}>{group.label}</Label>
                  <select
                    id={`lab-broker-${group.segment}`}
                    value={chosen[group.segment as keyof Chosen] ?? ""}
                    onChange={(e) => setChosen((cur) => ({ ...cur, [group.segment]: e.target.value }))}
                    className="h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30"
                  >
                    <option value="">Your setting{mineName ? ` (${mineName})` : ""}</option>
                    {group.brokers.map((b) => (
                      <option key={b.code} value={b.code}>
                        {b.name}
                      </option>
                    ))}
                  </select>
                </div>
              );
            })}
            {brokerGroups.isPending && <Skeleton className="h-12 w-full sm:col-span-3" />}
            <p className="text-xs text-muted-foreground sm:col-span-3">
              Charges in the results use these brokers&apos; fee tables, the same ones your paper account pays.
            </p>
          </CardContent>
        </Card>

        {run.error && (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertDescription>{run.error.message}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!canRun}>
            {busy ? "Running..." : "Run backtest"}
          </Button>
          {symbols.length === 0 && <span className="text-xs text-muted-foreground">Add at least one symbol.</span>}
          {runId !== null && (
            <Link href={`/algos/backtests/${runId}`} className="text-xs underline underline-offset-2">
              Open this run on its own page
            </Link>
          )}
        </div>
      </form>

      {backtest.error && !backtest.data && (
        <QueryError error={backtest.error} title="Couldn't load the backtest" onRetry={() => backtest.refetch()} />
      )}
      {backtest.data && <BacktestOutcome detail={backtest.data} />}
    </div>
  );
}

export function LabView() {
  const params = useSearchParams();
  const library = useAlgoLibrary();
  const mineList = useMyAlgos();
  const algoKey = params.get("algo");
  const mineId = Number(params.get("mine"));
  const wantsMine = params.has("mine") && Number.isInteger(mineId);

  const mine = wantsMine ? (mineList.data?.find((a) => a.id === mineId) ?? null) : null;
  const key = wantsMine ? mine?.strategy : algoKey;
  const algo = key ? library.data?.find((a) => a.key === key) : undefined;

  const error = library.error ?? (wantsMine ? mineList.error : null);
  const waiting = library.isPending || (wantsMine && mineList.isPending);

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <div className="grid gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">{mine ? mine.name : (algo?.name ?? "Algo lab")}</h1>
        {algo && (
          <p className="text-sm text-muted-foreground">
            {mine ? `${algo.name}, with your saved settings. ` : ""}
            {mine?.description || algo.description}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          <Link href="/algos" className="underline underline-offset-2">
            All algorithms
          </Link>
        </p>
      </div>
      {error && <QueryError error={error} title="Couldn't load the algorithms" />}
      {waiting && !error && <Skeleton className="h-64 w-full" />}
      {!waiting && !error && !algo && (
        <Alert>
          <AlertDescription>
            {wantsMine && !mine
              ? "That saved algorithm no longer exists."
              : "Pick an algorithm to open in the lab."}{" "}
            <Link href="/algos" className="underline underline-offset-2">
              Choose one
            </Link>
          </AlertDescription>
        </Alert>
      )}
      {algo && <LabForm key={`${algo.key}-${mine?.id ?? "library"}`} algo={algo} mine={mine} />}
    </div>
  );
}
