"use client";

import { createContext, useContext } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { TriangleAlertIcon } from "lucide-react";
import type { BlockSpec } from "@/lib/types";
import { cn } from "@/lib/utils";
import { CATEGORY_BAR, type BlockFlowNode } from "./graph";

type Ctx = { specs: Map<string, BlockSpec>; problemNodes: Set<string> };

/** The catalog and the blocks with problems, shared with every node without threading props through React Flow. */
export const BlocksContext = createContext<Ctx>({ specs: new Map(), problemNodes: new Set() });

const portLabel = (name: string, type: string, multi: boolean, input: boolean) =>
  type === "trigger" ? (input ? "Action" : "Attach risk") : multi ? "Signals (2+)" : name === "signal" ? "Signal" : name;

const HANDLE_BASE = "!size-3.5 !border-2 !border-background";

/** One block on the canvas: its name, a one-line summary of its settings and typed handles. */
export function BlockNode({ id, data, selected }: NodeProps<BlockFlowNode>) {
  const { specs, problemNodes } = useContext(BlocksContext);
  const spec = specs.get(data.blockType);
  const bad = problemNodes.has(id);

  const summary = spec
    ? spec.params
        .map((p) => `${p.label.toLowerCase()} ${String(data.params[p.name] ?? p.default)}`)
        .join(" · ")
    : "";

  return (
    <div
      data-problem={bad || undefined}
      className={cn(
        "relative w-52 rounded-lg border bg-card text-card-foreground shadow-sm",
        selected && "ring-2 ring-primary",
        bad && "outline-2 outline-offset-2 outline-red-500",
      )}
    >
      <div className={cn("h-1.5 rounded-t-lg", CATEGORY_BAR[spec?.category ?? "custom"])} />
      <div className="grid gap-0.5 px-3 py-2">
        <p className="flex items-center gap-1.5 text-sm font-medium leading-tight">
          {bad && <TriangleAlertIcon aria-label="This block has a problem" className="size-3.5 shrink-0 text-red-500" />}
          {spec?.label ?? "Unknown block"}
        </p>
        {summary && <p className="line-clamp-2 text-[0.7rem] leading-snug text-muted-foreground">{summary}</p>}
        {!spec && <p className="text-[0.7rem] text-muted-foreground">{data.blockType} is not in your library.</p>}
      </div>
      {spec && (spec.inputs.length > 0 || spec.outputs.length > 0) && (
        <div className="grid gap-1 pb-2 text-[0.7rem] text-muted-foreground">
          {spec.inputs.map((port) => (
            <div key={`in-${port.name}`} className="relative px-3">
              <Handle
                type="target"
                position={Position.Left}
                id={port.name}
                className={cn(HANDLE_BASE, port.type === "signal" ? "bg-sky-500!" : "bg-amber-500!")}
              />
              {portLabel(port.name, port.type, port.multi, true)}
            </div>
          ))}
          {spec.outputs.map((port) => (
            <div key={`out-${port.name}`} className="relative px-3 text-right">
              <Handle
                type="source"
                position={Position.Right}
                id={port.name}
                className={cn(HANDLE_BASE, port.type === "signal" ? "bg-sky-500!" : "bg-amber-500!")}
              />
              {portLabel(port.name, port.type, port.multi, false)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
