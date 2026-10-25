"use client";

import Link from "next/link";
import { QueryError } from "@/components/query-error";
import { Pnl } from "@/components/pnl";
import { PageHeader } from "@/components/motion/page-header";
import { Rise } from "@/components/motion/rise";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney, toNumber } from "@/lib/format";
import { useDeployment, useDeployments } from "@/lib/queries";
import type { Deployment } from "@/lib/types";
import { DeploymentControls, StatusLamp } from "./deployment-controls";

function Figure({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="t-meta text-dim">{label}</dt>
      <dd className="tabular-nums">{children}</dd>
    </div>
  );
}

function DeploymentCard({ dep }: { dep: Deployment }) {
  // Charges are only in the detail, which is polled anyway while it is on screen.
  const charges = useDeployment(dep.id).data?.total_charges;
  const total = toNumber(dep.realized_pnl) + toNumber(dep.unrealized_pnl);
  return (
    <li className="grid min-w-0 content-start gap-3 p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <Link href={`/deployments/${dep.id}`} className="t-head min-w-0 text-lg hover:underline">
          {dep.name}
        </Link>
        <StatusLamp status={dep.status} />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {dep.symbols.map((s) => (
          <Badge key={s} variant="secondary">
            {s}
          </Badge>
        ))}
      </div>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <Figure label="Capital">{formatMoney(dep.capital, dep.currency)}</Figure>
        <Figure label={dep.status === "stopped" ? "Returned" : "Equity"}>{formatMoney(dep.equity, dep.currency)}</Figure>
        <Figure label="P&L">
          <Pnl value={total} currency={dep.currency} />
        </Figure>
        <Figure label="Charges">{charges === undefined ? "—" : formatMoney(charges, dep.currency)}</Figure>
      </dl>
      <DeploymentControls dep={dep} />
    </li>
  );
}

/** /deployments: every algorithm you have running (or ran) live on paper. */
export function DeploymentsView() {
  const { data, isPending, error, refetch } = useDeployments();
  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <PageHeader
        title="My deployments"
        eyebrow="HFT · Algo"
        description="Your algorithms running live on paper accounts of their own."
        actions={
          <Button variant="outline" nativeButton={false} render={<Link href="/algos" />}>
            Algorithms
          </Button>
        }
      />
      {error && !data && <QueryError error={error} title="Couldn't load your deployments" onRetry={() => refetch()} />}
      {isPending && !error && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      )}
      {data && data.length === 0 && (
        <p className="border border-dashed border-line p-8 text-center text-sm text-muted-foreground">
          Deploy an algorithm from the{" "}
          <Link href="/algos/lab" className="underline underline-offset-2">
            lab
          </Link>{" "}
          or{" "}
          <Link href="/algos#mine-heading" className="underline underline-offset-2">
            My algorithms
          </Link>
          .
        </p>
      )}
      {data && data.length > 0 && (
        <Rise i={1}>
          <ul className="ledger grid-cols-1 md:grid-cols-2">
            {data.map((d) => (
              <DeploymentCard key={d.id} dep={d} />
            ))}
            {data.length % 2 === 1 && <li aria-hidden="true" className="hidden md:block" />}
          </ul>
        </Rise>
      )}
    </div>
  );
}
