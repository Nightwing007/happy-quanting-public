import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

// Shared blocks for route-level loading.tsx. Each mirrors the grid of the real component it stands in for,
// so nothing shifts when data arrives. Heights follow the real elements (title text-2xl, stat card ~7rem).

/** Page title row: matches the h1 line height of the real pages. */
export function TitleSkeleton({ width = "w-48" }: { width?: string }) {
  return <Skeleton className={cn("h-10", width)} />;
}

/** A bordered panel with a heading line and a body of the given height. */
export function PanelSkeleton({ height = "h-48", className }: { height?: string; className?: string }) {
  return (
    <div className={cn("grid gap-3 border bg-card p-4", className)} aria-hidden="true">
      <Skeleton className="h-4 w-32" />
      <Skeleton className={cn("w-full", height)} />
    </div>
  );
}

/** Summary stat cards: 1 / 2 / 3 columns like the dashboard. */
export function StatGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="ledger grid-cols-1 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-28 w-full" />
      ))}
    </div>
  );
}

/** Header row plus hairline-separated rows. */
export function TableSkeleton({ rows = 6, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("border bg-card", className)} aria-hidden="true">
      <Skeleton className="h-9 w-full" />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex h-10 items-center gap-4 border-t px-2">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 flex-1" />
          <Skeleton className="h-3 w-16" />
        </div>
      ))}
    </div>
  );
}

/** Main column plus a 320px side column, collapsing to one column below lg (the dashboard, trade and sim shape). */
export function SplitSkeleton({
  main = [<TableSkeleton key="a" />, <TableSkeleton key="b" rows={4} />],
  side = [<PanelSkeleton key="a" height="h-32" />, <PanelSkeleton key="b" height="h-32" />],
}: {
  main?: React.ReactNode[];
  side?: React.ReactNode[];
}) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]" aria-hidden="true">
      <div className="grid min-w-0 content-start gap-4">{main}</div>
      <div className="grid min-w-0 content-start gap-4">{side}</div>
    </div>
  );
}

/** Responsive card grid (galleries, marketplace, badges). */
export function CardGridSkeleton({ count = 6, height = "h-40" }: { count?: number; height?: string }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className={cn("w-full", height)} />
      ))}
    </div>
  );
}

/** Label-over-input form fields in a narrow column. */
export function FormSkeleton({ fields = 3, className }: { fields?: number; className?: string }) {
  return (
    <div className={cn("grid max-w-sm gap-4 border bg-card p-4", className)} aria-hidden="true">
      {Array.from({ length: fields }, (_, i) => (
        <div key={i} className="grid gap-2">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-8 w-full" />
        </div>
      ))}
      <Skeleton className="h-8 w-28" />
    </div>
  );
}

/** A chart area: fixed aspect so the plot never resizes when candles arrive. */
export function ChartSkeleton({ className }: { className?: string }) {
  return <Skeleton className={cn("h-72 w-full sm:h-96", className)} />;
}

/** Wraps a loading.tsx body: same page grid as the real pages. */
export function PageSkeleton({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-4" role="status" aria-busy="true" aria-label="Loading">
      {children}
    </div>
  );
}
