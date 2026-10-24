"use client";

import "@xyflow/react/dist/style.css";
import { useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
  type OnConnectEnd,
} from "@xyflow/react";
import { BlocksIcon, ChevronDownIcon, CodeIcon, MaximizeIcon, SlidersHorizontalIcon, Trash2Icon, XIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import { QueryError } from "@/components/query-error";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Preview, SymbolPicker } from "@/components/create/upload-flow";
import { SaveAlgoDialog } from "@/components/editor/save-dialog";
import { SimPanel } from "@/components/editor/sim-panel";
import type { ParamValue } from "@/lib/algo-format";
import { marketWord } from "@/lib/marketplace-format";
import {
  useBlockCatalog,
  useCompileBlocks,
  useCreateCustomBlock,
  useCreateMyAlgo,
  useMyAlgos,
  useUpdateMyAlgo,
} from "@/lib/queries";
import type { BlockSpec, UserAlgo } from "@/lib/types";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";
import { BlockNode, BlocksContext } from "./block-node";
import { CodeBlockDialog } from "./code-block-dialog";
import {
  SIGNAL_COLOR,
  TRIGGER_COLOR,
  compileKey,
  defaultParams,
  edgeKey,
  fromFlow,
  metaOf,
  newNodeId,
  storedValue,
  toFlow,
  wouldLoop,
  type BlockFlowNode,
  type Graph,
} from "./graph";
import { GroupDialog } from "./group-dialog";
import { Inspector } from "./inspector";
import { DRAG_TYPE, Palette } from "./palette";
import { ProblemsPanel } from "./problems-panel";
import { TEMPLATES, type Template } from "./templates";

// Monaco is large and needs the browser: load it only when the code is first shown.
const CodeEditor = dynamic(() => import("@/components/editor/code-editor"), {
  ssr: false,
  loading: () => <Skeleton className="h-72 w-full" />,
});

const nodeTypes = { block: BlockNode };
const COMPILE_NAME = "Block algorithm";
const COMPILE_MS = 800;

type Saved = { id: number; name: string; description: string; json: string };

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

/** A side column on wide screens; a slide-in drawer on small ones. */
function Drawer({
  side,
  open,
  title,
  onClose,
  children,
}: {
  side: "left" | "right";
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={onClose} aria-hidden />}
      <aside
        aria-label={title}
        className={cn(
          open
            ? "fixed inset-y-0 z-50 block w-[min(20rem,88vw)] overflow-y-auto bg-background p-4 shadow-xl"
            : "hidden",
          side === "left" ? "left-0" : "right-0",
          "lg:static lg:z-auto lg:block lg:max-h-[34rem] lg:w-auto lg:overflow-y-auto lg:bg-transparent lg:p-0 lg:shadow-none",
        )}
      >
        <div className="mb-3 flex items-center justify-between lg:hidden">
          <h2 className="font-medium">{title}</h2>
          <Button type="button" variant="ghost" size="icon-sm" aria-label={`Close ${title}`} onClick={onClose}>
            <XIcon />
          </Button>
        </div>
        {children}
      </aside>
    </>
  );
}

function Workspace({ saved: initialSaved, blocks }: { saved: UserAlgo | null; blocks: BlockSpec[] }) {
  const router = useRouter();
  const flow = useReactFlow();
  const { resolvedTheme } = useTheme();
  const create = useCreateMyAlgo();
  const update = useUpdateMyAlgo();
  const createGroup = useCreateCustomBlock();
  const createCode = useCreateCustomBlock();
  const wrapper = useRef<HTMLDivElement>(null);

  const initial = useMemo(
    () => (initialSaved?.graph ? toFlow(initialSaved.graph as unknown as Graph) : { nodes: [], edges: [] }),
    [initialSaved],
  );
  // Definitions of custom blocks a saved graph carries stay with it, so it still compiles if one is deleted.
  const [customBlocks] = useState<unknown[] | undefined>(
    (initialSaved?.graph as { custom_blocks?: unknown[] } | null | undefined)?.custom_blocks,
  );
  const [nodes, setNodes] = useState<BlockFlowNode[]>(initial.nodes);
  const [edges, setEdges] = useState<Edge[]>(initial.edges);
  const [drawer, setDrawer] = useState<"palette" | "inspector" | null>(null);
  const [dialog, setDialog] = useState<"save" | "publish" | "group" | "code" | null>(null);
  const [pendingTemplate, setPendingTemplate] = useState<Template | null>(null);
  const [codeOpen, setCodeOpen] = useState(false);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [saved, setSaved] = useState<Saved | null>(
    initialSaved?.graph
      ? {
          id: initialSaved.id,
          name: initialSaved.name,
          description: initialSaved.description,
          json: JSON.stringify(fromFlow(initial.nodes, initial.edges, customBlocks)),
        }
      : null,
  );

  const specs = useMemo(() => new Map(blocks.map((b) => [b.type, b])), [blocks]);
  const graph = useMemo(() => fromFlow(nodes, edges, customBlocks), [nodes, edges, customBlocks]);
  const graphJson = useMemo(() => JSON.stringify(graph), [graph]);

  // Compile once the person pauses. Moving a block changes nothing the compiler reads, so it never recompiles.
  const compileJson = useMemo(() => JSON.stringify(compileKey(graph)), [graph]);
  const settledJson = useDebounced(compileJson, COMPILE_MS);
  const body = useMemo(
    () => ({ graph: JSON.parse(settledJson) as Record<string, unknown>, name: COMPILE_NAME, description: "" }),
    [settledJson],
  );
  const compile = useCompileBlocks(body, nodes.length > 0);
  const checking = nodes.length > 0 && (settledJson !== compileJson || compile.isFetching);
  const result = nodes.length > 0 ? compile.data : undefined;
  const problems = useMemo(() => result?.problems ?? [], [result]);
  const problemNodes = useMemo(
    () => new Set(problems.flatMap((p) => (p.node_id ? [p.node_id] : []))),
    [problems],
  );
  const passes = !!result?.ok && !checking;
  const meta = useMemo(() => metaOf(graph, COMPILE_NAME), [graph]);

  const context = useMemo(() => ({ specs, problemNodes }), [specs, problemNodes]);
  const shownEdges = useMemo(
    () =>
      edges.map((e) => ({
        ...e,
        style: { stroke: e.sourceHandle === "trigger" ? TRIGGER_COLOR : SIGNAL_COLOR, strokeWidth: 2 },
      })),
    [edges],
  );

  const selectedNodes = nodes.filter((n) => n.selected);
  const selectedNode = selectedNodes.length === 1 ? selectedNodes[0] : null;
  const selectedEdges = edges.filter((e) => e.selected);
  const groupable =
    selectedNodes.length > 0 &&
    selectedNodes.every((n) => ["signal", "combine"].includes(specs.get(n.data.blockType)?.category ?? ""));

  const dirty = saved === null || saved.json !== graphJson;
  const saving = create.isPending || update.isPending;
  const saveError = (create.error ?? update.error)?.message ?? null;

  const onNodesChange = (c: NodeChange[]) => setNodes((ns) => applyNodeChanges(c, ns) as BlockFlowNode[]);
  const onEdgesChange = (c: EdgeChange[]) => setEdges((es) => applyEdgeChanges(c, es));

  function portOf(nodeId: string, handle: string | null | undefined, side: "outputs" | "inputs") {
    const node = nodes.find((n) => n.id === nodeId);
    return node ? specs.get(node.data.blockType)?.[side].find((p) => p.name === handle) : undefined;
  }

  // Refused while dragging: a signal only goes into a signal input, a trigger only into a risk block.
  function isValidConnection(c: Connection | Edge) {
    const from = portOf(c.source, c.sourceHandle, "outputs");
    const to = portOf(c.target, c.targetHandle, "inputs");
    if (!from || !to || from.type !== to.type) return false;
    if (wouldLoop(edges, c.source, c.target)) return false;
    return !edges.some(
      (e) =>
        e.source === c.source && e.sourceHandle === c.sourceHandle && e.target === c.target && e.targetHandle === c.targetHandle,
    );
  }

  function onConnect(c: Connection) {
    const to = portOf(c.target, c.targetHandle, "inputs");
    setEdges((es) => {
      // A single-input port takes one connection: a new one replaces the old.
      const kept = to?.multi ? es : es.filter((e) => !(e.target === c.target && e.targetHandle === c.targetHandle));
      return addEdge(
        {
          id: edgeKey({ source: c.source, source_port: c.sourceHandle ?? "", target: c.target, target_port: c.targetHandle ?? "" }),
          source: c.source,
          sourceHandle: c.sourceHandle,
          target: c.target,
          targetHandle: c.targetHandle,
        },
        kept,
      );
    });
  }

  const onConnectEnd: OnConnectEnd = (_, state) => {
    if (state.toHandle && state.isValid === false)
      toast.error("Those can't connect. Signals go into a signal input; risk blocks attach to a Buy or Short block.");
  };

  function add(type: string, at?: { x: number; y: number }) {
    if (type === "universe" && nodes.some((n) => n.data.blockType === "universe")) {
      toast.info("You already have a Universe block. Change its settings instead.");
      return;
    }
    const spec = specs.get(type);
    if (!spec) return;
    let position = at;
    if (!position) {
      const rect = wrapper.current?.getBoundingClientRect();
      const jitter = (nodes.length % 6) * 24;
      position = rect
        ? flow.screenToFlowPosition({ x: rect.left + rect.width / 2 - 104 + jitter, y: rect.top + rect.height / 2 - 40 + jitter })
        : { x: jitter, y: jitter };
    }
    const id = newNodeId(type, nodes.map((n) => n.id));
    setNodes((ns) => [
      ...ns.map((n) => ({ ...n, selected: false })),
      { id, type: "block", position, selected: true, data: { blockType: type, params: defaultParams(spec) } },
    ]);
    setDrawer(null);
  }

  function onDrop(e: React.DragEvent) {
    const type = e.dataTransfer.getData(DRAG_TYPE);
    if (!type) return;
    e.preventDefault();
    add(type, flow.screenToFlowPosition({ x: e.clientX - 104, y: e.clientY - 20 }));
  }

  function fit() {
    flow.fitView({ padding: 0.2, maxZoom: 1, duration: 200 });
  }

  function applyTemplate(t: Template) {
    const next = toFlow(structuredClone(t.graph));
    setNodes(next.nodes);
    setEdges(next.edges);
    setPendingTemplate(null);
    setDrawer(null);
    setTimeout(fit, 50);
  }
  function chooseTemplate(t: Template) {
    if (nodes.length === 0) applyTemplate(t);
    else setPendingTemplate(t);
  }

  function changeParam(name: string, value: ParamValue) {
    if (!selectedNode) return;
    const param = specs.get(selectedNode.data.blockType)?.params.find((p) => p.name === name);
    if (!param) return;
    const stored = storedValue(param, value);
    setNodes((ns) =>
      ns.map((n) =>
        n.id === selectedNode.id ? { ...n, data: { ...n.data, params: { ...n.data.params, [name]: stored } } } : n,
      ),
    );
  }

  function removeSelected() {
    const gone = new Set(selectedNodes.map((n) => n.id));
    setNodes((ns) => ns.filter((n) => !gone.has(n.id)));
    setEdges((es) => es.filter((e) => !e.selected && !gone.has(e.source) && !gone.has(e.target)));
  }

  function pickProblem(nodeId: string) {
    setNodes((ns) => ns.map((n) => ({ ...n, selected: n.id === nodeId })));
    flow.fitView({ nodes: [{ id: nodeId }], maxZoom: 1, duration: 300 });
  }

  function save(name: string, description: string, then: "publish" | null) {
    const done = (row: UserAlgo) => {
      setSaved({ id: row.id, name: row.name, description: row.description, json: graphJson });
      setDialog(null);
      if (then === "publish") router.push(`/create/upload?mine=${row.id}`);
      else toast.success(`Saved "${row.name}" to My algorithms.`);
    };
    const payload = { name, description, graph: graph as unknown as Record<string, unknown> };
    if (saved) update.mutate({ id: saved.id, ...payload }, { onSuccess: done });
    else create.mutate(payload, { onSuccess: done });
  }

  function publish() {
    if (saved && !dirty) return router.push(`/create/upload?mine=${saved.id}`);
    if (saved) return save(saved.name, saved.description, "publish");
    setDialog("publish");
  }

  const closeSave = () => {
    setDialog(null);
    create.reset();
    update.reset();
  };

  const empty = nodes.length === 0;
  const testBlocked = !passes || !meta;

  return (
    <BlocksContext.Provider value={context}>
      <div className="grid min-w-0 gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="sm" className="lg:hidden" onClick={() => setDrawer("palette")}>
            <BlocksIcon /> Blocks
          </Button>
          <Button type="button" variant="outline" size="sm" className="lg:hidden" onClick={() => setDrawer("inspector")}>
            <SlidersHorizontalIcon /> Settings{selectedNode ? `: ${specs.get(selectedNode.data.blockType)?.label ?? ""}` : ""}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!groupable}
            title={groupable ? undefined : "Select Signal or Combine blocks first (Shift-click, or drag a box)."}
            onClick={() => setDialog("group")}
          >
            Make a block
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => setDialog("code")}>
            <CodeIcon /> New code block
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={fit} disabled={empty}>
            <MaximizeIcon /> Fit to view
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={removeSelected}
            disabled={selectedNodes.length === 0 && selectedEdges.length === 0}
          >
            <Trash2Icon /> Delete selected
          </Button>
        </div>

        <div className="grid min-w-0 gap-4 lg:grid-cols-[15rem_minmax(0,1fr)_17rem] lg:items-start">
          <Drawer side="left" open={drawer === "palette"} title="Blocks" onClose={() => setDrawer(null)}>
            <Palette blocks={blocks} onAdd={add} onTemplate={chooseTemplate} />
          </Drawer>

          <div
            ref={wrapper}
            className="relative h-[30rem] min-w-0 overflow-hidden rounded-lg border bg-muted/20 lg:h-[34rem]"
          >
            <ReactFlow
              nodes={nodes}
              edges={shownEdges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onConnectEnd={onConnectEnd}
              isValidConnection={isValidConnection}
              onDrop={onDrop}
              onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "copy";
              }}
              deleteKeyCode={["Backspace", "Delete"]}
              multiSelectionKeyCode="Shift"
              connectionRadius={28}
              minZoom={0.2}
              fitView
              fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
              colorMode={resolvedTheme === "dark" ? "dark" : "light"}
            >
              <Background gap={20} />
              <Controls showInteractive={false} />
            </ReactFlow>
            {empty && (
              <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-4">
                <div className="pointer-events-auto grid max-w-sm gap-3 rounded-lg border bg-background/95 p-4 text-center shadow-sm">
                  <p className="font-medium">Start from a template, or drag a Universe block in.</p>
                  <div className="flex flex-wrap justify-center gap-2">
                    {TEMPLATES.map((t) => (
                      <Button key={t.key} type="button" size="sm" variant="outline" onClick={() => chooseTemplate(t)}>
                        {t.name}
                      </Button>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Blocks are in the list on the left. Click one to add it, then drag from one block&rsquo;s coloured
                    dot to another&rsquo;s to connect them.
                  </p>
                </div>
              </div>
            )}
          </div>

          <Drawer side="right" open={drawer === "inspector"} title="Block settings" onClose={() => setDrawer(null)}>
            <Inspector
              node={selectedNode}
              spec={selectedNode ? (specs.get(selectedNode.data.blockType) ?? null) : null}
              onChange={changeParam}
              onDelete={removeSelected}
            />
          </Drawer>
        </div>

        <ProblemsPanel
          problems={problems}
          checking={checking}
          empty={empty}
          labelOf={(id) => specs.get(nodes.find((n) => n.id === id)?.data.blockType ?? "")?.label ?? "Block"}
          onPick={pickProblem}
        />
        {compile.error && (
          <Alert variant="destructive">
            <AlertDescription>{compile.error.message}</AlertDescription>
          </Alert>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" onClick={() => setDialog("save")} disabled={empty || !passes || saving}>
            {saved ? "Save changes" : "Save"}
          </Button>
          <Button type="button" variant="outline" onClick={publish} disabled={empty || !passes || saving}>
            Publish
          </Button>
          <span className="text-xs text-muted-foreground" aria-live="polite">
            {saved ? (dirty ? `Unsaved changes to "${saved.name}"` : `Saved as "${saved.name}"`) : "Not saved yet"}
            {!empty && !passes && !checking ? " · fix the problems above to save or test" : ""}
          </span>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>
              <button
                type="button"
                aria-expanded={codeOpen}
                onClick={() => setCodeOpen(!codeOpen)}
                className="flex w-full items-center gap-2 text-left"
              >
                <ChevronDownIcon className={cn("size-4 transition-transform", !codeOpen && "-rotate-90")} />
                View code
              </button>
            </CardTitle>
            <CardDescription>The Python your blocks turn into. Read it to learn how a strategy is written.</CardDescription>
          </CardHeader>
          {codeOpen && (
            <CardContent className="min-w-0">
              {result?.ok && result.source ? (
                <CodeEditor value={result.source} onChange={() => {}} problems={[]} readOnly heightClass="h-80" />
              ) : (
                <p className="text-sm text-muted-foreground">
                  {empty ? "Add some blocks first." : "The code appears once the blocks have no problems."}
                </p>
              )}
            </CardContent>
          )}
        </Card>

        <Section title="Test it" hint="Choose symbols, then backtest your blocks or watch them trade in the virtual sim.">
          {testBlocked || !meta || !result ? (
            <p className="text-sm text-muted-foreground">Available once your blocks have no problems.</p>
          ) : (
            <>
              <div className="grid content-start gap-1.5">
                <Label>Symbols (up to 10)</Label>
                <SymbolPicker symbols={symbols} setSymbols={setSymbols} meta={meta} />
                <p className="text-xs text-muted-foreground">
                  Only symbols in the markets your Universe block names: {meta.markets.map(marketWord).join(", ")}.
                </p>
              </div>
              <h3 className="font-medium">Backtest</h3>
              <Preview source={result.source} meta={meta} symbols={symbols} setSymbols={setSymbols} showSymbols={false} />
              <h3 className="font-medium">Run in the virtual sim</h3>
              <SimPanel source={result.source} meta={meta} symbols={symbols} />
            </>
          )}
        </Section>

        <p className="text-xs text-muted-foreground">
          Code blocks follow the same code rules as uploaded strategies. They are listed in &ldquo;The rules&rdquo; on the{" "}
          <Link href="/algos/editor" className="underline underline-offset-2">
            code editor page
          </Link>{" "}
          and in the New code block window.
        </p>
      </div>

      {(dialog === "save" || dialog === "publish") && (
        <SaveAlgoDialog
          initialName={saved?.name ?? ""}
          initialDescription={saved?.description ?? ""}
          publishing={dialog === "publish"}
          what="blocks"
          pending={saving}
          error={saveError}
          onSave={(name, description) => save(name, description, dialog === "publish" ? "publish" : null)}
          onClose={closeSave}
        />
      )}
      {dialog === "group" && groupable && (
        <GroupDialog
          nodes={selectedNodes}
          edges={edges}
          specs={specs}
          pending={createGroup.isPending}
          error={createGroup.error?.message ?? null}
          onSave={(b) =>
            createGroup.mutate(b, {
              onSuccess: (row) => {
                setDialog(null);
                createGroup.reset();
                toast.success(`"${row.name}" is now under My blocks.`);
              },
            })
          }
          onClose={() => {
            setDialog(null);
            createGroup.reset();
          }}
        />
      )}
      {dialog === "code" && (
        <CodeBlockDialog
          pending={createCode.isPending}
          error={createCode.error?.message ?? null}
          onSave={(b) =>
            createCode.mutate(b, {
              onSuccess: (row) => {
                setDialog(null);
                createCode.reset();
                toast.success(`"${row.name}" is now under My blocks.`);
              },
            })
          }
          onClose={() => {
            setDialog(null);
            createCode.reset();
          }}
        />
      )}
      <AlertDialog open={pendingTemplate !== null} onOpenChange={(open) => !open && setPendingTemplate(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Replace what is on the canvas?</AlertDialogTitle>
            <AlertDialogDescription>
              Loading &ldquo;{pendingTemplate?.name}&rdquo; removes the blocks you have now. Your saved algorithm is
              not changed until you save.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep my blocks</AlertDialogCancel>
            <AlertDialogAction onClick={() => pendingTemplate && applyTemplate(pendingTemplate)}>Replace</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </BlocksContext.Provider>
  );
}

export function BlockEditorView() {
  const params = useSearchParams();
  const raw = params.get("mine");
  const mineId = raw === null ? null : Number(raw);
  const mine = useMyAlgos();
  const catalog = useBlockCatalog();
  const found = mineId !== null ? (mine.data?.find((a) => a.id === mineId) ?? null) : null;
  const waiting = (mineId !== null && mine.isPending) || catalog.isPending;
  const notBlocks = mineId !== null && !mine.isPending && !mine.error && (!found || !found.graph);

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <div className="grid gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">{found?.graph ? found.name : "Block editor"}</h1>
        <p className="text-sm text-muted-foreground">
          Build an algorithm by connecting big blocks, no code needed. Check it, test it, then save or publish it.
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
      {catalog.error && <QueryError error={catalog.error} title="Couldn't load the blocks" onRetry={() => catalog.refetch()} />}
      {waiting && !mine.error && !catalog.error && <Skeleton className="h-96 w-full" />}
      {notBlocks && (
        <Alert>
          <AlertDescription>
            {found
              ? "That saved algorithm wasn't built with blocks, so it opens somewhere else."
              : `You have no saved algorithm ${raw}.`}{" "}
            <Link
              href={!found ? "/algos" : found.source !== null ? `/algos/editor?mine=${found.id}` : `/algos/lab?mine=${found.id}`}
              className="underline underline-offset-2"
            >
              {!found ? "Back to algorithms" : found.source !== null ? "Open in the code editor" : "Open in the lab"}
            </Link>
          </AlertDescription>
        </Alert>
      )}
      {!waiting && !mine.error && !catalog.error && catalog.data && !notBlocks && (
        <ReactFlowProvider>
          <Workspace key={found?.id ?? "new"} saved={found} blocks={catalog.data.blocks} />
        </ReactFlowProvider>
      )}
    </div>
  );
}
