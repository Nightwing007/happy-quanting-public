"use client";

import { Term } from "@/components/term";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { paramProblem, sliderStep, type ParamValue } from "@/lib/algo-format";
import type { TermId } from "@/lib/glossary";
import type { Algo, AlgoParam } from "@/lib/types";
import { cn } from "@/lib/utils";

export type ParamValues = Record<string, ParamValue>;

/** The form's starting values: the saved settings over the algorithm's defaults. */
export function initialValues(algo: Algo, saved?: Record<string, unknown>): ParamValues {
  const out: ParamValues = {};
  for (const p of algo.parameters) {
    const v = saved && p.name in saved ? saved[p.name] : p.default;
    out[p.name] = typeof v === "boolean" || typeof v === "string" ? v : String(v);
  }
  return out;
}

// Param labels that are a glossary term. Anything else keeps just the server's help text.
const LABEL_TERMS: Record<string, TermId> = {
  "RSI period": "rsi",
  "ATR period": "atr",
  "Oversold level": "oversold",
  "Band period": "bollinger",
  "Band width (k)": "bollinger",
  "Stop-loss (%)": "stop_loss",
  "Allow shorts": "short",
};

function ParamLabel({ label }: { label: string }) {
  const term = LABEL_TERMS[label];
  return term ? <Term id={term}>{label}</Term> : <>{label}</>;
}

function Field({
  param,
  value,
  onChange,
}: {
  param: AlgoParam;
  value: ParamValue;
  onChange: (v: ParamValue) => void;
}) {
  const id = `param-${param.name}`;
  const helpId = `${id}-help`;
  const problem = paramProblem(param, value);
  const hasRange = param.min !== null && param.max !== null;
  const typed = Number(value);
  const sliderValue = String(value).trim() !== "" && Number.isFinite(typed) ? typed : Number(param.default);

  return (
    <div className="grid content-start gap-1.5">
      {param.kind === "bool" ? (
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor={id}><ParamLabel label={param.label} /></Label>
          <button
            id={id}
            type="button"
            role="switch"
            aria-checked={value === true}
            aria-describedby={helpId}
            onClick={() => onChange(value !== true)}
            className={cn(
              "relative h-5 w-9 shrink-0 rounded-full border transition-colors focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
              value === true ? "border-primary bg-primary" : "bg-muted",
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 left-0.5 size-3.5 rounded-full bg-background shadow transition-transform",
                value === true && "translate-x-4",
              )}
            />
          </button>
        </div>
      ) : param.kind === "choice" ? (
        <>
          <Label htmlFor={id}><ParamLabel label={param.label} /></Label>
          <select
            id={id}
            value={String(value)}
            aria-describedby={helpId}
            onChange={(e) => onChange(e.target.value)}
            className="h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30"
          >
            {param.choices.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </>
      ) : (
        <>
          <Label htmlFor={id}><ParamLabel label={param.label} /></Label>
          <div className="flex min-w-0 items-center gap-3">
            {hasRange && (
              <input
                type="range"
                aria-label={`${param.label} slider`}
                min={Number(param.min)}
                max={Number(param.max)}
                step={sliderStep(param)}
                value={Math.min(Math.max(sliderValue, Number(param.min)), Number(param.max))}
                onChange={(e) => onChange(e.target.value)}
                className="min-w-0 flex-1 accent-primary"
              />
            )}
            <Input
              id={id}
              type="number"
              inputMode="decimal"
              step={sliderStep(param)}
              min={param.min ?? undefined}
              max={param.max ?? undefined}
              value={String(value)}
              aria-invalid={problem ? true : undefined}
              aria-describedby={helpId}
              onChange={(e) => onChange(e.target.value)}
              className="w-24 shrink-0 tabular-nums"
            />
          </div>
        </>
      )}
      <p id={helpId} className="text-xs text-muted-foreground">
        {param.help}
        {hasRange && param.kind !== "bool" && ` (${param.min} to ${param.max})`}
      </p>
      {problem && (
        <p role="alert" className="text-xs text-destructive">
          {problem}
        </p>
      )}
    </div>
  );
}

/** The settings of one algorithm, generated from the schema the server publishes. */
export function ParamForm({
  algo,
  values,
  onChange,
  narrow = false,
}: {
  algo: Pick<Algo, "parameters">;
  values: ParamValues;
  onChange: (name: string, value: ParamValue) => void;
  /** One column always (a side panel), instead of two from the `sm` breakpoint. */
  narrow?: boolean;
}) {
  return (
    <div className={cn("grid grid-cols-1 gap-4", !narrow && "sm:grid-cols-2")}>
      {algo.parameters.map((p) => (
        <Field key={p.name} param={p} value={values[p.name] ?? p.default} onChange={(v) => onChange(p.name, v)} />
      ))}
    </div>
  );
}
