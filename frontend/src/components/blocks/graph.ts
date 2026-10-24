import type { Edge, Node } from "@xyflow/react";
import { paramPayload, paramProblem, type ParamValue } from "@/lib/algo-format";
import type { AlgoParam, BlockSpec, StrategyMeta } from "@/lib/types";

/** The graph the server takes (`graph` of `/api/blocks/compile` and `/api/algos/mine`). */
export type GraphNode = {
  id: string;
  type: string;
  params: Record<string, ParamValue>;
  position: { x: number; y: number };
};
export type GraphEdge = { source: string; source_port: string; target: string; target_port: string };
export type Graph = { nodes: GraphNode[]; edges: GraphEdge[]; custom_blocks?: unknown[] };

export type BlockNodeData = { blockType: string; params: Record<string, ParamValue> } & Record<string, unknown>;
export type BlockFlowNode = Node<BlockNodeData, "block">;

export const SIGNAL_COLOR = "var(--color-sky-500)";
export const TRIGGER_COLOR = "var(--color-amber-500)";

export const CATEGORY_ORDER = ["universe", "signal", "combine", "action", "risk", "custom"] as const;
export const CATEGORY_TITLES: Record<string, string> = {
  universe: "Universe",
  signal: "Signals: when to act",
  combine: "Combine signals",
  action: "Actions: what to do",
  risk: "Risk controls",
  custom: "My blocks",
};
/** A coloured top edge per category, so the canvas reads at a glance. */
export const CATEGORY_BAR: Record<string, string> = {
  universe: "bg-slate-500",
  signal: "bg-sky-500",
  combine: "bg-violet-500",
  action: "bg-emerald-500",
  risk: "bg-amber-500",
  custom: "bg-pink-500",
};

export const defaultParams = (spec: BlockSpec): Record<string, ParamValue> =>
  Object.fromEntries(spec.params.map((p) => [p.name, p.default as ParamValue]));

/** A value ready for the graph: numbers as numbers while they parse, otherwise as typed (the server explains it). */
export const storedValue = (p: AlgoParam, raw: ParamValue): ParamValue =>
  paramProblem(p, raw) ? raw : (paramPayload(p, raw) as ParamValue);

export function newNodeId(type: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  const base = type.replace(/[^a-z0-9]+/gi, "_").replace(/^_+|_+$/g, "") || "block";
  for (let n = 1; ; n++) {
    const id = `${base}_${n}`;
    if (!used.has(id)) return id;
  }
}

export const edgeKey = (e: GraphEdge) => `${e.source}:${e.source_port}->${e.target}:${e.target_port}`;

export function toFlow(graph: Graph): { nodes: BlockFlowNode[]; edges: Edge[] } {
  return {
    nodes: graph.nodes.map((n) => ({
      id: n.id,
      type: "block" as const,
      position: n.position,
      data: { blockType: n.type, params: { ...n.params } },
    })),
    edges: graph.edges.map((e) => ({
      id: edgeKey(e),
      source: e.source,
      sourceHandle: e.source_port,
      target: e.target,
      targetHandle: e.target_port,
    })),
  };
}

export function fromFlow(nodes: BlockFlowNode[], edges: Edge[], customBlocks?: unknown[]): Graph {
  const graph: Graph = {
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.blockType,
      params: n.data.params,
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
    })),
    edges: edges.map((e) => ({
      source: e.source,
      source_port: e.sourceHandle ?? "",
      target: e.target,
      target_port: e.targetHandle ?? "",
    })),
  };
  if (customBlocks?.length) graph.custom_blocks = customBlocks;
  return graph;
}

/** What the server needs to compile: positions never matter, so moving a block does not recompile. */
export function compileKey(graph: Graph): Graph {
  return { ...graph, nodes: graph.nodes.map((n) => ({ ...n, position: { x: 0, y: 0 } })) };
}

const MARKETS_FOR: Record<string, string[]> = {
  all: ["india", "international", "crypto"],
  india: ["india"],
  international: ["international"],
  crypto: ["crypto"],
};

/** The test panels only need the bar size and markets, both set by the Universe block. */
export function metaOf(graph: Graph, name: string): StrategyMeta | null {
  const universe = graph.nodes.find((n) => n.type === "universe");
  if (!universe) return null;
  return {
    name,
    description: "",
    interval: String(universe.params.interval ?? "1d"),
    markets: MARKETS_FOR[String(universe.params.markets ?? "all")] ?? MARKETS_FOR.all,
    parameters: [],
    warmup_bars: 0,
  };
}

/** Would an edge from `source` to `target` close a loop? */
export function wouldLoop(edges: Edge[], source: string, target: string): boolean {
  if (source === target) return true;
  const next = new Map<string, string[]>();
  for (const e of edges) next.set(e.source, [...(next.get(e.source) ?? []), e.target]);
  const seen = new Set<string>();
  const todo = [target];
  while (todo.length) {
    const at = todo.pop()!;
    if (at === source) return true;
    if (seen.has(at)) continue;
    seen.add(at);
    todo.push(...(next.get(at) ?? []));
  }
  return false;
}
