"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2Icon, TriangleAlertIcon } from "lucide-react";
import { toast } from "sonner";
import { QueryError } from "@/components/query-error";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ProblemsList } from "@/components/create/problems-list";
import { RulesPanel } from "@/components/create/rules-panel";
import { Preview, SymbolPicker } from "@/components/create/upload-flow";
import { algoIntervalWords } from "@/lib/algo-format";
import { marketWord } from "@/lib/marketplace-format";
import { useCreateMyAlgo, useMyAlgos, useUpdateMyAlgo, useValidateCode } from "@/lib/queries";
import type { StrategyMeta, UserAlgo, ValidationReport } from "@/lib/types";
import type { CodeEditorHandle } from "./code-editor";
import { SaveAlgoDialog } from "./save-dialog";
import { SimPanel } from "./sim-panel";
import { STARTER_TEMPLATE } from "./starter";

// Monaco is large and needs the browser: load it only when the page is opened.
const CodeEditor = dynamic(() => import("./code-editor"), {
  ssr: false,
  loading: () => <Skeleton className="h-[28rem] w-full" />,
});

const IDLE_MS = 1500;

type Saved = { id: number; name: string; description: string; source: string };

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {hint && <CardDescription>{hint}</CardDescription>}
      </CardHeader>
      <CardContent className="grid min-w-0 gap-4">{children}</CardContent>
    </Card>
  );
}

function Workspace({ saved: initialSaved }: { saved: UserAlgo | null }) {
  const router = useRouter();
  const validate = useValidateCode();
  const create = useCreateMyAlgo();
  const update = useUpdateMyAlgo();
  const editor = useRef<CodeEditorHandle>(null);
  const requested = useRef<string | null>(null);

  const [source, setSource] = useState(initialSaved?.source ?? STARTER_TEMPLATE);
  const [report, setReport] = useState<{ for: string; value: ValidationReport } | null>(null);
  const [meta, setMeta] = useState<StrategyMeta | null>(null);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [saved, setSaved] = useState<Saved | null>(
    initialSaved?.source
      ? { id: initialSaved.id, name: initialSaved.name, description: initialSaved.description, source: initialSaved.source }
      : null,
  );
  const [dialog, setDialog] = useState<{ publishing: boolean } | null>(null);

  const { mutate: validateCode } = validate;
  const check = useCallback(
    (text: string) => {
      requested.current = text;
      validateCode(text, {
        onSuccess: (value) => {
          if (requested.current !== text) return; // a newer check is on its way
          setReport({ for: text, value });
          if (value.ok && value.meta) setMeta(value.meta);
        },
      });
    },
    [validateCode],
  );

  // Check once the person pauses typing (and once on load); the Validate button forces one.
  useEffect(() => {
    if (!source.trim() || requested.current === source) return;
    const timer = setTimeout(() => check(source), IDLE_MS);
    return () => clearTimeout(timer);
  }, [source, check]);

  const problems = report && !report.value.ok ? report.value.problems : [];
  const passes = !!report?.value.ok && report.for === source;
  const dirty = saved === null || saved.source !== source;
  const saving = create.isPending || update.isPending;
  const saveError = (create.error ?? update.error)?.message ?? null;

  function save(name: string, description: string, then: "publish" | null) {
    const done = (row: UserAlgo) => {
      setSaved({ id: row.id, name: row.name, description: row.description, source });
      setDialog(null);
      if (then === "publish") router.push(`/create/upload?mine=${row.id}`);
      else toast.success(`Saved "${row.name}" to My algorithms.`);
    };
    if (saved) update.mutate({ id: saved.id, name, description, source }, { onSuccess: done });
    else create.mutate({ name, description, source }, { onSuccess: done });
  }

  function publish() {
    if (saved && !dirty) return router.push(`/create/upload?mine=${saved.id}`);
    if (saved) return save(saved.name, saved.description, "publish");
    setDialog({ publishing: true });
  }

  function pick(line: number) {
    editor.current?.reveal(line, problems.find((p) => p.line === line)?.col ?? 1);
  }

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)] lg:items-start">
      <div className="grid min-w-0 gap-4">
        <Section
          title="Your code"
          hint="Write a strategy in Python. Problems are marked on the line they are on; type ctx. for the strategy API."
        >
          <CodeEditor ref={editor} value={source} onChange={setSource} problems={problems} />
          {validate.error && (
            <Alert variant="destructive">
              <TriangleAlertIcon />
              <AlertDescription>{validate.error.message}</AlertDescription>
            </Alert>
          )}
          {problems.length > 0 && <ProblemsList problems={problems} onPick={pick} />}
          {passes && meta && (
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <span className="flex items-center gap-1.5 font-medium text-emerald-700 dark:text-emerald-400">
                <CheckCircle2Icon className="size-4" />
                Your code passes every check.
              </span>
              <span className="text-muted-foreground">
                {meta.name} · {algoIntervalWords(meta.interval)} bars · {meta.markets.map(marketWord).join(", ")} ·{" "}
                {meta.warmup_bars} warmup bars
              </span>
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" onClick={() => check(source)} disabled={!source.trim() || validate.isPending}>
              {validate.isPending ? "Checking..." : "Validate"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDialog({ publishing: false })}
              disabled={!source.trim() || saving}
            >
              {saved ? "Save changes" : "Save"}
            </Button>
            <Button type="button" variant="outline" onClick={publish} disabled={!source.trim() || saving}>
              Publish
            </Button>
            <span className="text-xs text-muted-foreground" aria-live="polite">
              {saved ? (dirty ? `Unsaved changes to "${saved.name}"` : `Saved as "${saved.name}"`) : "Not saved yet"}
              {validate.isPending ? " · running your code on made-up prices..." : ""}
            </span>
          </div>
        </Section>

        <Section title="Test it" hint="Choose symbols, then backtest the code or watch it trade in the virtual sim.">
          {meta ? (
            <>
              <div className="grid content-start gap-1.5">
                <Label>Symbols (up to 10)</Label>
                <SymbolPicker symbols={symbols} setSymbols={setSymbols} meta={meta} />
                <p className="text-xs text-muted-foreground">
                  Only symbols in the markets your code names: {meta.markets.map(marketWord).join(", ")}.
                </p>
              </div>
              <h3 className="font-medium">Backtest</h3>
              <Preview source={source} meta={meta} symbols={symbols} setSymbols={setSymbols} showSymbols={false} />
              <h3 className="font-medium">Run in the virtual sim</h3>
              <SimPanel source={source} meta={meta} symbols={symbols} />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Available once your code passes the checks.</p>
          )}
        </Section>
      </div>
      <div className="min-w-0 lg:sticky lg:top-20">
        <RulesPanel />
      </div>

      {dialog && (
        <SaveAlgoDialog
          initialName={saved?.name ?? meta?.name ?? ""}
          initialDescription={saved?.description ?? meta?.description ?? ""}
          publishing={dialog.publishing}
          pending={saving}
          error={saveError}
          onSave={(name, description) => save(name, description, dialog.publishing ? "publish" : null)}
          onClose={() => {
            setDialog(null);
            create.reset();
            update.reset();
          }}
        />
      )}
    </div>
  );
}

export function EditorView() {
  const params = useSearchParams();
  const raw = params.get("mine");
  const mineId = raw === null ? null : Number(raw);
  const mine = useMyAlgos();
  const found = mineId !== null ? (mine.data?.find((a) => a.id === mineId) ?? null) : null;
  const waiting = mineId !== null && mine.isPending;

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <div className="grid gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">{found ? found.name : "Code editor"}</h1>
        <p className="text-sm text-muted-foreground">
          Write your own algorithm, check it against the rules, test it, and save or publish it.
        </p>
        <p className="text-xs text-muted-foreground">
          <Link href="/algos" className="underline underline-offset-2">
            All algorithms
          </Link>
        </p>
      </div>
      {mineId !== null && mine.error && (
        <QueryError error={mine.error} title="Couldn't load your algorithms" onRetry={() => mine.refetch()} />
      )}
      {waiting && !mine.error && <Skeleton className="h-96 w-full" />}
      {mineId !== null && !mine.isPending && !mine.error && (!found || found.source === null) && (
        <Alert>
          <AlertDescription>
            {found
              ? "That saved algorithm is built on a ready-made one, so it opens in the lab."
              : `You have no saved algorithm ${raw}.`}{" "}
            <Link href={found ? `/algos/lab?mine=${found.id}` : "/algos"} className="underline underline-offset-2">
              {found ? "Open in the lab" : "Back to algorithms"}
            </Link>
          </AlertDescription>
        </Alert>
      )}
      {!waiting && !mine.error && (mineId === null || (found && found.source !== null)) && (
        <Workspace key={found?.id ?? "new"} saved={found} />
      )}
    </div>
  );
}
