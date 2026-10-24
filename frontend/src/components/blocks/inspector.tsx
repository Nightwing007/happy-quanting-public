"use client";

import { Trash2Icon } from "lucide-react";
import { ParamForm } from "@/components/algos/param-form";
import { Button } from "@/components/ui/button";
import type { ParamValue } from "@/lib/algo-format";
import type { BlockSpec } from "@/lib/types";
import type { BlockFlowNode } from "./graph";

/** The selected block's settings, with the bounds and help the server publishes. */
export function Inspector({
  node,
  spec,
  onChange,
  onDelete,
}: {
  node: BlockFlowNode | null;
  spec: BlockSpec | null;
  onChange: (name: string, value: ParamValue) => void;
  onDelete: () => void;
}) {
  if (!node) {
    return (
      <p className="text-sm text-muted-foreground">
        Click a block on the canvas to change its settings. Drag from a coloured dot to another block to connect
        them.
      </p>
    );
  }
  const values = Object.fromEntries(
    (spec?.params ?? []).map((p) => [p.name, node.data.params[p.name] ?? (p.default as ParamValue)]),
  );
  return (
    <div className="grid gap-3">
      <div className="grid gap-0.5">
        <h3 className="font-medium">{spec?.label ?? "Unknown block"}</h3>
        {spec && <p className="text-xs text-muted-foreground">{spec.help}</p>}
      </div>
      {spec && spec.params.length > 0 ? (
        <ParamForm algo={{ parameters: spec.params }} values={values} onChange={onChange} narrow />
      ) : (
        <p className="text-sm text-muted-foreground">This block has no settings.</p>
      )}
      <Button type="button" variant="destructive" size="sm" onClick={onDelete} className="justify-self-start">
        <Trash2Icon /> Remove this block
      </Button>
    </div>
  );
}
