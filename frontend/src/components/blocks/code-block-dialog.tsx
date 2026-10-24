"use client";

import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { PlusIcon, XIcon } from "lucide-react";
import { RulesPanel } from "@/components/create/rules-panel";
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
import { Skeleton } from "@/components/ui/skeleton";
import type { CodeProblem, CustomBlockIn } from "@/lib/types";

const CodeEditor = dynamic(() => import("@/components/editor/code-editor"), {
  ssr: false,
  loading: () => <Skeleton className="h-56 w-full" />,
});

type Mode = "signal" | "act";
type Row = { name: string; label: string; kind: "int" | "decimal" | "bool" | "choice"; default: string; min: string; max: string; choices: string };

const TEMPLATES: Record<Mode, string> = {
  signal: `def signal(ctx, symbol, params):
    # Return True when this block is "on" for the symbol on the latest bar.
    closes = ctx.close_series(symbol, 20)
    return len(closes) >= 20 and closes[-1] > closes[0]
`,
  act: `def act(ctx, symbol, params):
    # Runs when the connected signal is on. Place orders here.
    if ctx.position(symbol).quantity <= 0:
        ctx.buy(symbol, percent_of_cash=10)
`,
};

const EMPTY_ROW: Row = { name: "", label: "", kind: "int", default: "10", min: "", max: "", choices: "" };

/** The server joins a snippet's problems into one sentence ("Line 3: ... Line 5: ..."); split it back for markers. */
export function problemsFromMessage(message: string | null): CodeProblem[] {
  if (!message) return [];
  const body = message.replace(/^[^:]*can't be saved:\s*/, "");
  const parts = body.split(/(?=Line \d+: )/).filter((s) => s.trim());
  return parts.map((text) => {
    const m = /^Line (\d+): /.exec(text);
    return { line: m ? Number(m[1]) : 0, col: 1, code: "bad_block", message: text.trim() };
  });
}

/** A small Python editor for a custom block, written against the same code rules as uploaded strategies. */
export function CodeBlockDialog({
  pending,
  error,
  onSave,
  onClose,
}: {
  pending: boolean;
  error: string | null;
  onSave: (body: CustomBlockIn) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<Mode>("signal");
  const [code, setCode] = useState(TEMPLATES.signal);
  const [lookback, setLookback] = useState("20");
  const [rows, setRows] = useState<Row[]>([]);
  const problems = useMemo(() => problemsFromMessage(error), [error]);
  const lineProblems = problems.filter((p) => p.line > 0);

  function changeMode(next: Mode) {
    if (code === TEMPLATES[mode]) setCode(TEMPLATES[next]);
    setMode(next);
  }
  const setRow = (i: number, patch: Partial<Row>) => setRows(rows.map((r, k) => (k === i ? { ...r, ...patch } : r)));

  function save() {
    onSave({
      name: name.trim(),
      kind: "code",
      definition: {
        mode,
        code,
        lookback: Number(lookback),
        params: rows.map((r) => ({
          name: r.name.trim(),
          label: r.label.trim() || undefined,
          kind: r.kind,
          ...(r.kind === "bool" ? { default: r.default === "true" } : {}),
          ...(r.kind === "int" || r.kind === "decimal"
            ? {
                default: r.default.trim(),
                ...(r.min.trim() ? { min: r.min.trim() } : {}),
                ...(r.max.trim() ? { max: r.max.trim() } : {}),
              }
            : {}),
          ...(r.kind === "choice"
            ? { choices: r.choices.split(",").map((c) => c.trim()).filter(Boolean) }
            : {}),
        })),
      },
    });
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && !pending) save();
          }}
          className="grid min-w-0 gap-4"
        >
          <DialogHeader>
            <DialogTitle>New code block</DialogTitle>
            <DialogDescription>
              Write your own signal or action in Python. It follows the same code rules as uploaded strategies, and
              then appears under My blocks.
            </DialogDescription>
          </DialogHeader>
          <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="grid content-start gap-1.5 sm:col-span-2">
              <Label htmlFor="cb-name">Name</Label>
              <Input id="cb-name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} autoFocus />
            </div>
            <div className="grid content-start gap-1.5">
              <Label htmlFor="cb-lookback">Bars of history needed</Label>
              <Input
                id="cb-lookback"
                type="number"
                min={0}
                max={1000}
                value={lookback}
                onChange={(e) => setLookback(e.target.value)}
              />
            </div>
            <div className="grid content-start gap-1.5 sm:col-span-3">
              <Label htmlFor="cb-mode">What it does</Label>
              <select
                id="cb-mode"
                value={mode}
                onChange={(e) => changeMode(e.target.value as Mode)}
                className="h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30"
              >
                <option value="signal">A signal: gives true or false for a symbol</option>
                <option value="act">An action: places orders when a signal is on</option>
              </select>
            </div>
          </div>
          <div className="grid min-w-0 gap-1.5">
            <Label>Code</Label>
            <CodeEditor value={code} onChange={setCode} problems={lineProblems} heightClass="h-56" />
            <p className="text-xs text-muted-foreground">
              Only imports and one function go here. Add <code>params</code> as the third argument to read the
              settings below as <code>params[&quot;name&quot;]</code>.
            </p>
          </div>
          <fieldset className="grid min-w-0 gap-2">
            <legend className="text-sm font-medium">Settings (optional)</legend>
            {rows.map((r, i) => (
              <div key={i} className="grid min-w-0 grid-cols-2 gap-2 rounded-lg border p-2 sm:grid-cols-4">
                <Input
                  aria-label="Setting name"
                  placeholder="name, e.g. bars"
                  value={r.name}
                  onChange={(e) => setRow(i, { name: e.target.value })}
                />
                <select
                  aria-label="Setting type"
                  value={r.kind}
                  onChange={(e) => setRow(i, { kind: e.target.value as Row["kind"] })}
                  className="h-8 min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30"
                >
                  <option value="int">Whole number</option>
                  <option value="decimal">Number</option>
                  <option value="bool">Yes or no</option>
                  <option value="choice">One of a list</option>
                </select>
                {r.kind === "bool" ? (
                  <select
                    aria-label="Default"
                    value={r.default}
                    onChange={(e) => setRow(i, { default: e.target.value })}
                    className="h-8 min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30"
                  >
                    <option value="false">No</option>
                    <option value="true">Yes</option>
                  </select>
                ) : r.kind === "choice" ? (
                  <Input
                    aria-label="Choices"
                    placeholder="a, b, c"
                    value={r.choices}
                    onChange={(e) => setRow(i, { choices: e.target.value })}
                    className="col-span-2"
                  />
                ) : (
                  <>
                    <Input
                      aria-label="Default"
                      placeholder="default"
                      value={r.default}
                      onChange={(e) => setRow(i, { default: e.target.value })}
                    />
                    <Input aria-label="Smallest" placeholder="min" value={r.min} onChange={(e) => setRow(i, { min: e.target.value })} />
                    <Input aria-label="Largest" placeholder="max" value={r.max} onChange={(e) => setRow(i, { max: e.target.value })} />
                  </>
                )}
                <Input
                  aria-label="Label shown"
                  placeholder="label shown (optional)"
                  value={r.label}
                  onChange={(e) => setRow(i, { label: e.target.value })}
                  className="col-span-2"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label="Remove this setting"
                  onClick={() => setRows(rows.filter((_, k) => k !== i))}
                  className="justify-self-start"
                >
                  <XIcon /> Remove
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setRows([...rows, { ...EMPTY_ROW }])}
              disabled={rows.length >= 12}
              className="justify-self-start"
            >
              <PlusIcon /> Add a setting
            </Button>
          </fieldset>
          <details className="rounded-lg border p-2 text-sm">
            <summary className="cursor-pointer font-medium">The code rules (they apply here too)</summary>
            <div className="mt-2 max-h-72 overflow-y-auto">
              <RulesPanel />
            </div>
          </details>
          {problems.length > 0 && (
            <ul role="alert" className="grid gap-1 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
              {problems.map((p, i) => (
                <li key={i}>{p.message}</li>
              ))}
            </ul>
          )}
          {error && problems.length === 0 && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={!name.trim() || pending}>
              {pending ? "Checking..." : "Check and save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
