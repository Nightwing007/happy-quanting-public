"use client";

import { CheckCircle2Icon, TriangleAlertIcon } from "lucide-react";
import type { BlockProblem } from "@/lib/types";

/** Plain-language problems; one that names a block selects it on the canvas when clicked. */
export function ProblemsPanel({
  problems,
  checking,
  empty,
  labelOf,
  onPick,
}: {
  problems: BlockProblem[];
  checking: boolean;
  empty: boolean;
  labelOf: (nodeId: string) => string;
  onPick: (nodeId: string) => void;
}) {
  if (empty) return null;
  if (problems.length === 0) {
    return (
      <p className="flex items-center gap-1.5 text-sm text-muted-foreground" aria-live="polite">
        {checking ? (
          "Checking your blocks..."
        ) : (
          <>
            <CheckCircle2Icon className="size-4 text-up" />
            <span className="font-medium text-up">No problems.</span> Your blocks are
            ready to test.
          </>
        )}
      </p>
    );
  }
  return (
    <div role="alert" className="grid gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
      <p className="flex items-center gap-2 text-sm font-medium text-destructive">
        <TriangleAlertIcon className="size-4" />
        {problems.length === 1 ? "1 problem to fix" : `${problems.length} problems to fix`}
        {checking && <span className="font-normal text-muted-foreground">(checking again...)</span>}
      </p>
      <ul className="grid gap-1 text-sm">
        {problems.map((p, i) => (
          <li key={`${p.node_id ?? "-"}-${p.line}-${i}`}>
            <button
              type="button"
              disabled={!p.node_id}
              onClick={() => p.node_id && onPick(p.node_id)}
              className="w-full rounded-md px-2 py-1 text-left hover:bg-destructive/10 disabled:cursor-default disabled:hover:bg-transparent"
            >
              {p.node_id && <span className="font-medium">{labelOf(p.node_id)}: </span>}
              {p.line > 0 && <span className="font-medium tabular-nums">Line {p.line}: </span>}
              {p.message.replace(/^Line \d+:\s*/, "")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
