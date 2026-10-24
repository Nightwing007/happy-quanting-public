"use client";

import { TriangleAlertIcon } from "lucide-react";
import type { CodeProblem } from "@/lib/types";

/** Each problem as "Line N: message"; clicking one jumps to that line in the code box. */
export function ProblemsList({ problems, onPick }: { problems: CodeProblem[]; onPick: (line: number) => void }) {
  return (
    <div role="alert" className="grid gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
      <p className="flex items-center gap-2 text-sm font-medium text-destructive">
        <TriangleAlertIcon className="size-4" />
        {problems.length === 1 ? "1 problem to fix" : `${problems.length} problems to fix`}
      </p>
      <ul className="grid gap-1 text-sm">
        {problems.map((p, i) => (
          <li key={`${p.line}-${p.col}-${p.code}-${i}`}>
            <button
              type="button"
              disabled={p.line < 1}
              onClick={() => onPick(p.line)}
              className="w-full rounded-md px-2 py-1 text-left hover:bg-destructive/10 disabled:cursor-default disabled:hover:bg-transparent"
            >
              <span className="font-medium tabular-nums">{p.line < 1 ? "File" : `Line ${p.line}`}:</span> {p.message.replace(/^Line \d+:\s*/, "")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
