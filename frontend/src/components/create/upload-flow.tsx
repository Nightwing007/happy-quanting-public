"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2Icon, PlusIcon, TriangleAlertIcon, XIcon } from "lucide-react";
import { BacktestOutcome } from "@/components/algos/backtest-outcome";
import { QueryError } from "@/components/query-error";
import { SymbolSearch } from "@/components/symbol-search";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { algoIntervalWords, historyLimitsText, yearBefore } from "@/lib/algo-format";
import { allowedBy, marketWord } from "@/lib/marketplace-format";
import {
  useAlgoRules,
  useBacktest,
  useCreateListing,
  useHistoryLimits,
  useMyAlgos,
  useMyListings,
  usePublishListing,
  useRunBacktest,
  useUpdateListing,
  useValidateCode,
} from "@/lib/queries";
import { formatDay } from "@/lib/sim-format";
import type { ListingOwner, StrategyMeta, ValidationReport } from "@/lib/types";
import { CodeInput, type CodeInputHandle } from "./code-input";
import { ProblemsList } from "./problems-list";
import { RulesPanel } from "./rules-panel";
import { PageHeader } from "@/components/motion/page-header";

const MAX_SYMBOLS = 10;

function Stage({
  n,
  title,
  hint,
  locked,
  children,
}: {
  n: string;
  title: string;
  hint?: string;
  locked?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Card className={locked ? "opacity-60" : undefined}>
      <CardHeader>
        <CardTitle>
          {n}. {title}
        </CardTitle>
        {hint && <CardDescription>{hint}</CardDescription>}
      </CardHeader>
      <CardContent className="min-w-0">
        {/* A disabled fieldset disables every control inside it, so a locked stage cannot be used by accident. */}
        <fieldset disabled={locked} className="grid min-w-0 gap-4">
          {children}
        </fieldset>
      </CardContent>
    </Card>
  );
}

export function SymbolPicker({
  symbols,
  setSymbols,
  meta,
}: {
  symbols: string[];
  setSymbols: (next: string[]) => void;
  meta: StrategyMeta;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {symbols.map((s) => (
        <Badge key={s} variant="secondary" className="gap-1 pr-1">
          {s}
          <button
            type="button"
            aria-label={`Remove ${s}`}
            onClick={() => setSymbols(symbols.filter((x) => x !== s))}
            className="rounded-full p-0.5 hover:bg-foreground/10"
          >
            <XIcon className="size-3" />
          </button>
        </Badge>
      ))}
      {symbols.length < MAX_SYMBOLS && (
        <SymbolSearch
          filter={(i) => allowedBy(meta.markets, i)}
          onSelect={(symbol) => {
            const clean = symbol.trim().toUpperCase();
            if (!symbols.includes(clean)) setSymbols([...symbols, clean]);
          }}
          label={
            <>
              <PlusIcon />
              <span>{symbols.length ? "Add another" : "Add a symbol"}</span>
            </>
          }
        />
      )}
    </div>
  );
}

/** Preview backtest of the code as written. The editor page shows its own symbol picker (`showSymbols={false}`). */
export function Preview({
  source,
  meta,
  symbols,
  setSymbols,
  showSymbols = true,
}: {
  source: string;
  meta: StrategyMeta;
  symbols: string[];
  setSymbols: (s: string[]) => void;
  showSymbols?: boolean;
}) {
  const limits = useHistoryLimits();
  const run = useRunBacktest();
  const [runId, setRunId] = useState<number | null>(null);
  const [start, setStart] = useState<string | null>(null);
  const [end, setEnd] = useState<string | null>(null);
  const backtest = useBacktest(runId);

  const today = limits.data?.today ?? null;
  const earliest = limits.data?.limits.find((l) => l.interval === meta.interval)?.earliest ?? null;
  const endDay = end ?? today ?? "";
  const startDay = useMemo(() => {
    if (start !== null) return start;
    if (!today) return "";
    const year = yearBefore(today);
    return earliest && year < earliest ? earliest : year;
  }, [start, today, earliest]);

  const rangeProblem =
    !startDay || !endDay || !today
      ? null
      : earliest && startDay < earliest
        ? `${algoIntervalWords(meta.interval)} data only goes back to ${formatDay(earliest)}.`
        : endDay < startDay
          ? "The last day cannot be before the first day."
          : endDay > today
            ? "The last day cannot be in the future."
            : null;
  const status = backtest.data?.status;
  const busy = run.isPending || status === "queued" || status === "running";
  const canRun = symbols.length > 0 && !rangeProblem && !!startDay && !busy;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canRun) return;
    run.mutate(
      { source, symbols, interval: meta.interval, start_date: startDay, end_date: endDay },
      { onSuccess: (b) => setRunId(b.id) },
    );
  }

  return (
    <>
      <form onSubmit={submit} className="grid min-w-0 gap-4">
        {showSymbols && (
          <div className="grid content-start gap-1.5">
            <Label>Symbols (up to {MAX_SYMBOLS})</Label>
            <SymbolPicker symbols={symbols} setSymbols={setSymbols} meta={meta} />
            <p className="text-xs text-muted-foreground">
              Only symbols in the markets your code names: {meta.markets.map(marketWord).join(", ")}.
            </p>
          </div>
        )}
        <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="grid content-start gap-1.5">
            <Label htmlFor="up-start">First day</Label>
            <Input
              id="up-start"
              type="date"
              value={startDay}
              min={earliest ?? undefined}
              max={today ?? undefined}
              onChange={(e) => setStart(e.target.value)}
            />
          </div>
          <div className="grid content-start gap-1.5">
            <Label htmlFor="up-end">Last day</Label>
            <Input
              id="up-end"
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
        </div>
        {run.error && (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertDescription>{run.error.message}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!canRun}>
            {busy ? "Running..." : "Run preview backtest"}
          </Button>
          {symbols.length === 0 && <span className="text-xs text-muted-foreground">Add at least one symbol.</span>}
        </div>
      </form>
      {backtest.error && !backtest.data && (
        <QueryError error={backtest.error} title="Couldn't load the backtest" onRetry={() => backtest.refetch()} />
      )}
      {backtest.data && <BacktestOutcome detail={backtest.data} actions={false} />}
    </>
  );
}

function MetaSummary({ meta }: { meta: StrategyMeta }) {
  return (
    <div className="grid gap-2 rounded-lg border bg-muted/30 p-3 text-sm">
      <p className="flex items-center gap-2 font-medium text-up">
        <CheckCircle2Icon className="size-4" />
        Your code passes every check.
      </p>
      <dl className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted-foreground">Name</dt>
          <dd className="font-medium">{meta.name}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Bar size</dt>
          <dd className="font-medium">
            {algoIntervalWords(meta.interval)} ({meta.interval})
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-xs text-muted-foreground">Markets</dt>
          <dd className="flex flex-wrap gap-1.5">
            {meta.markets.map((m) => (
              <Badge key={m} variant="secondary">
                {marketWord(m)}
              </Badge>
            ))}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-xs text-muted-foreground">Parameters</dt>
          <dd>
            {meta.parameters.length === 0 ? (
              <span className="text-muted-foreground">None</span>
            ) : (
              <ul className="grid gap-0.5">
                {meta.parameters.map((p) => (
                  <li key={p.name}>
                    <span className="font-medium">{p.label}</span>{" "}
                    <span className="text-muted-foreground">
                      (<code>{p.name}</code>, {p.kind}, default {String(p.default)}
                      {p.min !== null && p.max !== null ? `, ${p.min} to ${p.max}` : ""})
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
      </dl>
    </div>
  );
}

type Props = { updating: ListingOwner | null; initialSource?: string };

function Flow({ updating, initialSource }: Props) {
  const router = useRouter();
  const rules = useAlgoRules();
  const validate = useValidateCode();
  const create = useCreateListing();
  const publish = usePublishListing();
  const update = useUpdateListing();

  const [source, setSourceRaw] = useState(updating?.source ?? initialSource ?? "");
  const [report, setReport] = useState<{ for: string; value: ValidationReport } | null>(null);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [testOverride, setTestOverride] = useState<string[] | null>(null);
  const [name, setName] = useState("");
  const [tagline, setTagline] = useState("");
  const [description, setDescription] = useState("");
  const [picked, setPicked] = useState<string[] | null>(null);
  const [fee, setFee] = useState(updating?.fee_percent ?? "10");
  const [changelog, setChangelog] = useState("");
  const [touched, setTouched] = useState({ name: false, description: false });
  const [draftId, setDraftId] = useState<number | null>(null);
  const editor = useRef<CodeInputHandle>(null);

  const meta = report?.value.ok ? report.value.meta : null;
  const valid = !!meta && report?.for === source;

  function setSource(next: string) {
    setSourceRaw(next);
    validate.reset();
  }

  function check() {
    const checked = source;
    validate.mutate(checked, {
      onSuccess: (value) => {
        setReport({ for: checked, value });
        if (value.ok && value.meta) {
          if (!touched.name) setName(value.meta.name);
          if (!touched.description) setDescription(value.meta.description);
        }
      },
    });
  }

  const problems = report?.value.problems ?? [];
  const shown = report && !report.value.ok ? problems : [];
  const markets = picked ?? meta?.markets ?? [];
  const testSymbols = testOverride ?? symbols;

  const feeNumber = Number(fee);
  const feeProblem =
    fee.trim() === "" || !Number.isFinite(feeNumber) || feeNumber < 0 || feeNumber > 50 ? "Enter a fee between 0 and 50." : null;
  const formProblem = updating
    ? changelog.trim() === ""
      ? "Say what changed in this version."
      : null
    : !name.trim()
      ? "Give it a name."
      : markets.length === 0
        ? "Pick at least one market."
        : testSymbols.length === 0
          ? "Add at least one test symbol."
          : feeProblem;

  const sending = create.isPending || publish.isPending || update.isPending;
  const serverError = (draftId === null ? create.error : null) ?? publish.error ?? update.error;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid || !meta || formProblem || sending) return;
    if (updating) {
      update.mutate(
        { id: updating.id, source, changelog: changelog.trim() },
        { onSuccess: () => router.push(`/marketplace/${updating.id}`) },
      );
      return;
    }
    const goPublish = (id: number) => publish.mutate(id, { onSuccess: () => router.push(`/marketplace/${id}`) });
    // A listing made before a failed publish is reused on retry rather than created twice.
    if (draftId !== null) return goPublish(draftId);
    create.mutate(
      {
        name: name.trim(),
        tagline: tagline.trim(),
        description: description.trim(),
        markets,
        test_symbols: testSymbols,
        interval: meta.interval,
        fee_percent: fee.trim(),
        source,
      },
      {
        onSuccess: (listing) => {
          setDraftId(listing.id);
          goPublish(listing.id);
        },
      },
    );
  }

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)] lg:items-start">
      <div className="grid min-w-0 gap-4">
        <Stage
          n="1"
          title="Check your code"
          hint={updating ? `You are writing version ${updating.version + 1} of ${updating.name}.` : "Paste or upload a strategy, then check it against the rules."}
        >
          <CodeInput
            ref={editor}
            value={source}
            onChange={setSource}
            problemLines={shown.map((p) => p.line)}
            maxBytes={rules.data?.limits.MAX_SOURCE_BYTES}
          />
          {validate.error && (
            <Alert variant="destructive">
              <TriangleAlertIcon />
              <AlertDescription>{validate.error.message}</AlertDescription>
            </Alert>
          )}
          {shown.length > 0 && <ProblemsList problems={shown} onPick={(line) => editor.current?.focusLine(line)} />}
          {valid && meta && <MetaSummary meta={meta} />}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" onClick={check} disabled={!source.trim() || validate.isPending}>
              {validate.isPending ? "Checking..." : "Validate"}
            </Button>
            {validate.isPending && <span className="text-xs text-muted-foreground">This runs your code on made-up prices, so it can take a few seconds.</span>}
            {report && !valid && report.value.ok && !validate.isPending && (
              <span className="text-xs text-muted-foreground">The code changed since the last check. Validate again.</span>
            )}
          </div>
        </Stage>

        <Stage
          n="2"
          title="Preview backtest"
          hint="See how it would have done. Only you see this run; it is not what the marketplace shows."
          locked={!valid}
        >
          {valid && meta ? (
            <Preview source={source} meta={meta} symbols={symbols} setSymbols={setSymbols} />
          ) : (
            <p className="text-sm text-muted-foreground">Available once your code passes the checks.</p>
          )}
        </Stage>

        <form onSubmit={submit} className="grid min-w-0">
          <Stage
            n="3"
            title={updating ? "What changed" : "Describe your listing"}
            hint={updating ? "Subscribers stay on their version until they choose to upgrade." : undefined}
            locked={!valid}
          >
            {updating ? (
              <div className="grid content-start gap-1.5">
                <Label htmlFor="up-changelog">Changelog (required)</Label>
                <Textarea
                  id="up-changelog"
                  rows={3}
                  value={changelog}
                  maxLength={2000}
                  onChange={(e) => setChangelog(e.target.value)}
                  placeholder="What is different in this version?"
                />
                <p className="text-xs text-muted-foreground">
                  The bar size ({updating.interval}) and fee stay as they are; this makes version {updating.version + 1}.
                </p>
              </div>
            ) : (
              <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="grid content-start gap-1.5">
                  <Label htmlFor="up-name">Name</Label>
                  <Input
                    id="up-name"
                    value={name}
                    maxLength={80}
                    onChange={(e) => {
                      setName(e.target.value);
                      setTouched((t) => ({ ...t, name: true }));
                    }}
                  />
                </div>
                <div className="grid content-start gap-1.5">
                  <Label htmlFor="up-tagline">Tagline</Label>
                  <Input id="up-tagline" value={tagline} maxLength={140} onChange={(e) => setTagline(e.target.value)} placeholder="One line for the marketplace card" />
                </div>
                <div className="grid content-start gap-1.5 sm:col-span-2">
                  <Label htmlFor="up-description">Description</Label>
                  <Textarea
                    id="up-description"
                    rows={4}
                    value={description}
                    onChange={(e) => {
                      setDescription(e.target.value);
                      setTouched((t) => ({ ...t, description: true }));
                    }}
                  />
                </div>
                <div className="grid content-start gap-1.5 sm:col-span-2">
                  <Label>Markets</Label>
                  <div className="flex flex-wrap gap-2">
                    {(meta?.markets ?? []).map((m) => {
                      const on = markets.includes(m);
                      return (
                        <Button
                          key={m}
                          type="button"
                          size="sm"
                          variant={on ? "default" : "outline"}
                          aria-pressed={on}
                          onClick={() => setPicked(on ? markets.filter((x) => x !== m) : [...markets, m])}
                        >
                          {marketWord(m)}
                        </Button>
                      );
                    })}
                  </div>
                  <p className="text-xs text-muted-foreground">Chosen from the markets your code names.</p>
                </div>
                <div className="grid content-start gap-1.5 sm:col-span-2">
                  <Label>Test symbols</Label>
                  {meta && <SymbolPicker symbols={testSymbols} setSymbols={setTestOverride} meta={meta} />}
                  <p className="text-xs text-muted-foreground">
                    The marketplace measures your performance on these. They start as the symbols you previewed.
                  </p>
                </div>
                <div className="grid content-start gap-1.5">
                  <Label htmlFor="up-fee">Fee (%)</Label>
                  <Input
                    id="up-fee"
                    type="number"
                    inputMode="decimal"
                    min="0"
                    max="50"
                    step="0.5"
                    value={fee}
                    aria-invalid={feeProblem ? true : undefined}
                    onChange={(e) => setFee(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    You keep this share of subscribers&apos; net profit above their previous high.
                  </p>
                </div>
                <div className="grid content-start gap-1.5">
                  <Label htmlFor="up-interval">Bar size</Label>
                  <Input id="up-interval" value={meta ? algoIntervalWords(meta.interval) : ""} readOnly disabled />
                  <p className="text-xs text-muted-foreground">Read from your code.</p>
                </div>
              </div>
            )}

            {serverError && (
              <Alert variant="destructive">
                <TriangleAlertIcon />
                <AlertDescription>
                  {serverError.message}
                  {draftId !== null && (
                    <>
                      {" "}
                      Your listing was saved as a draft;{" "}
                      <Link href="/create" className="underline underline-offset-2">
                        find it in My listings
                      </Link>{" "}
                      or try again.
                    </>
                  )}
                </AlertDescription>
              </Alert>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={!valid || !!formProblem || sending}>
                {sending ? "Saving..." : updating ? `Publish version ${updating.version + 1}` : "Create and publish"}
              </Button>
              {valid && formProblem && <span className="text-xs text-muted-foreground">{formProblem}</span>}
            </div>
          </Stage>
        </form>
      </div>
      <div className="min-w-0 lg:sticky lg:top-20">
        <RulesPanel />
      </div>
    </div>
  );
}

export function UploadFlow() {
  const params = useSearchParams();
  const raw = params.get("listing");
  const listingId = raw === null ? null : Number(raw);
  const mine = useMyListings();
  // ?mine=<id> comes from the editor: the code of one of the person's saved algorithms.
  const algoParam = params.get("mine");
  const savedAlgos = useMyAlgos();
  const fromAlgo = algoParam !== null ? savedAlgos.data?.find((a) => a.id === Number(algoParam)) : undefined;
  const waitingForAlgo = algoParam !== null && savedAlgos.isPending;
  const updating = listingId !== null ? (mine.data?.find((l) => l.id === listingId) ?? null) : null;
  const waitingForListing = (listingId !== null && mine.isPending) || waitingForAlgo;

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <PageHeader
        title={updating ? `New version of ${updating.name}` : "Upload a strategy"}
        eyebrow="HFT · Create"
        description={
          <Link href="/create" className="text-xs underline underline-offset-2">
            My listings
          </Link>
        }
      />
      {listingId !== null && mine.error && <QueryError error={mine.error} title="Couldn't load your listings" onRetry={() => mine.refetch()} />}
      {waitingForListing && !mine.error && <Skeleton className="h-64 w-full" />}
      {listingId !== null && !mine.isPending && !mine.error && !updating && (
        <Alert>
          <AlertDescription>
            You have no listing {raw}.{" "}
            <Link href="/create" className="underline underline-offset-2">
              Back to My listings
            </Link>
          </AlertDescription>
        </Alert>
      )}
      {!waitingForListing && !mine.error && (listingId === null || updating) && (
        <Flow
          key={`${updating?.id ?? "new"}-${fromAlgo?.id ?? "paste"}`}
          updating={updating}
          initialSource={fromAlgo?.source ?? undefined}
        />
      )}
    </div>
  );
}
