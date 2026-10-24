"use client";

import { useMemo, useState } from "react";
import type { Edge } from "@xyflow/react";
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
import type { BlockSpec, CustomBlockIn } from "@/lib/types";
import type { BlockFlowNode } from "./graph";

type Exposed = { on: boolean; label: string };

const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");

/** Turns the selected Signal and Combine blocks into one reusable block: a name, its answer and the settings it shows. */
export function GroupDialog({
  nodes,
  edges,
  specs,
  pending,
  error,
  onSave,
  onClose,
}: {
  nodes: BlockFlowNode[];
  edges: Edge[];
  specs: Map<string, BlockSpec>;
  pending: boolean;
  error: string | null;
  onSave: (body: CustomBlockIn) => void;
  onClose: () => void;
}) {
  const ids = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes]);
  const inner = useMemo(() => edges.filter((e) => ids.has(e.source) && ids.has(e.target)), [edges, ids]);
  // The natural answer is the block nothing else in the selection reads from.
  const sinks = nodes.filter((n) => !inner.some((e) => e.source === n.id));
  const [name, setName] = useState("");
  const [output, setOutput] = useState((sinks[0] ?? nodes[0]).id);
  const [exposed, setExposed] = useState<Record<string, Exposed>>({});

  const key = (nodeId: string, param: string) => `${nodeId}.${param}`;
  const labelOf = (n: BlockFlowNode) => specs.get(n.data.blockType)?.label ?? n.data.blockType;

  function save() {
    const items = nodes.flatMap((n) =>
      (specs.get(n.data.blockType)?.params ?? []).flatMap((p) => {
        const e = exposed[key(n.id, p.name)];
        if (!e?.on) return [];
        return [
          {
            name: slug(`${n.id}_${p.name}`).slice(0, 40),
            label: e.label.trim() || `${labelOf(n)} ${p.label}`,
            help: p.help,
            targets: [{ node: n.id, param: p.name }],
          },
        ];
      }),
    );
    onSave({
      name: name.trim(),
      kind: "group",
      definition: {
        nodes: nodes.map((n) => ({ id: n.id, type: n.data.blockType, params: n.data.params, position: n.position })),
        edges: inner.map((e) => ({
          source: e.source,
          source_port: e.sourceHandle ?? "",
          target: e.target,
          target_port: e.targetHandle ?? "",
        })),
        output,
        exposed: items,
      },
    });
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && !pending) save();
          }}
          className="grid gap-4"
        >
          <DialogHeader>
            <DialogTitle>Make a block</DialogTitle>
            <DialogDescription>
              Packs the {nodes.length} selected {nodes.length === 1 ? "block" : "blocks"} into one block you can use
              again. It then appears under My blocks.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="grp-name">Name</Label>
            <Input
              id="grp-name"
              value={name}
              maxLength={60}
              placeholder="e.g. Oversold and trending up"
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="grp-output">Which block gives the answer?</Label>
            <select
              id="grp-output"
              value={output}
              onChange={(e) => setOutput(e.target.value)}
              className="h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30"
            >
              {nodes.map((n) => (
                <option key={n.id} value={n.id}>
                  {labelOf(n)} ({n.id})
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              The new block is on while this one is on. Every selected block must lead to it.
            </p>
          </div>
          <fieldset className="grid gap-2">
            <legend className="text-sm font-medium">Settings people can change</legend>
            <p className="text-xs text-muted-foreground">Tick the ones to show on the new block; the rest stay fixed.</p>
            {nodes.map((n) => {
              const params = specs.get(n.data.blockType)?.params ?? [];
              if (params.length === 0) return null;
              return (
                <div key={n.id} className="grid gap-1 rounded-lg border p-2">
                  <p className="text-xs font-medium">
                    {labelOf(n)} <span className="font-normal text-muted-foreground">({n.id})</span>
                  </p>
                  {params.map((p) => {
                    const k = key(n.id, p.name);
                    const e = exposed[k] ?? { on: false, label: "" };
                    return (
                      <div key={k} className="flex min-w-0 flex-wrap items-center gap-2">
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={e.on}
                            onChange={(ev) => setExposed({ ...exposed, [k]: { ...e, on: ev.target.checked } })}
                          />
                          {p.label}
                        </label>
                        {e.on && (
                          <Input
                            aria-label={`Name shown for ${p.label}`}
                            value={e.label}
                            placeholder={`${labelOf(n)} ${p.label}`}
                            onChange={(ev) => setExposed({ ...exposed, [k]: { ...e, label: ev.target.value } })}
                            className="h-7 min-w-0 flex-1 basis-40"
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </fieldset>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={!name.trim() || pending}>
              {pending ? "Saving..." : "Save block"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
