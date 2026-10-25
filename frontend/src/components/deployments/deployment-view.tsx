"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { OrdersTable } from "@/components/orders-table";
import { Pnl } from "@/components/pnl";
import { QueryError } from "@/components/query-error";
import { TradesTable } from "@/components/trades-table";
import { PageHeader } from "@/components/motion/page-header";
import { Rise } from "@/components/motion/rise";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney, parseApiTime } from "@/lib/format";
import { useDeployment } from "@/lib/queries";
import type { DeploymentDetail } from "@/lib/types";
import { DeploymentControls, StatusLamp } from "./deployment-controls";
import { settingLabel } from "./deploy-dialog";

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <li className="p-4">
      <p className="t-meta text-dim">{label}</p>
      <p className="mt-1 text-lg tabular-nums">{children}</p>
    </li>
  );
}

/** The strategy's own log: monospace, newest at the bottom, following the end unless you scroll up. */
function LiveLog({ log }: { log: DeploymentDetail["log"] }) {
  const box = useRef<HTMLDivElement>(null);
  const follow = useRef(true);

  useEffect(() => {
    const el = box.current;
    if (el && follow.current) el.scrollTop = el.scrollHeight;
  }, [log]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Live log</CardTitle>
        <CardDescription>
          What the strategy writes as it runs. The log is kept in memory, so it is empty after the server restarts;
          trades and orders are not affected.
        </CardDescription>
      </CardHeader>
      <CardContent className="min-w-0">
        <div
          ref={box}
          role="log"
          aria-label="Live log"
          tabIndex={0}
          onScroll={(e) => {
            const el = e.currentTarget;
            follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
          }}
          className="h-64 overflow-y-auto border border-line bg-void p-3 font-mono text-xs leading-5"
        >
          {log.length === 0 ? (
            <p className="text-muted-foreground">Nothing logged yet.</p>
          ) : (
            log.map((line, i) => (
              <p key={i} className="break-words">
                <span className="text-dim">{parseApiTime(line.at).toLocaleTimeString([], { hour12: false })}</span>{" "}
                {line.text}
              </p>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Detail({ d }: { d: DeploymentDetail }) {
  const settings = Object.entries(d.params);
  return (
    <>
      <Rise i={1}>
        <ul className="ledger grid-cols-2 md:grid-cols-4" aria-label="Summary">
          <Cell label="Status">
            <StatusLamp status={d.status} />
          </Cell>
          <Cell label="Capital">{formatMoney(d.capital, d.currency)}</Cell>
          <Cell label={d.status === "stopped" ? "Returned" : "Equity"}>{formatMoney(d.equity, d.currency)}</Cell>
          <Cell label="Total P&L">
            <Pnl value={d.total_pnl} currency={d.currency} />
          </Cell>
          <Cell label="Realized P&L">
            <Pnl value={d.realized_pnl} currency={d.currency} />
          </Cell>
          <Cell label="Unrealized P&L">
            <Pnl value={d.unrealized_pnl} currency={d.currency} />
          </Cell>
          <Cell label="Charges paid">{formatMoney(d.total_charges, d.currency)}</Cell>
          <Cell label="Started">{parseApiTime(d.created_at).toLocaleDateString([], { dateStyle: "medium" })}</Cell>
        </ul>
      </Rise>

      <Rise i={2}>
        <Card>
          <CardHeader>
            <CardTitle>What is running</CardTitle>
            <CardDescription>
              {d.runs_code ? "Your own code" : d.strategy_key} · {d.user_algo_id !== null ? "copied from a saved algorithm" : "settings pinned at deploy time"}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid min-w-0 gap-3">
            <div className="flex flex-wrap gap-1.5">
              {d.symbols.map((s) => (
                <Badge key={s} variant="secondary">
                  {s}
                </Badge>
              ))}
            </div>
            {settings.length > 0 && (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-sm sm:grid-cols-[auto_1fr_auto_1fr]">
                {settings.map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted-foreground">{settingLabel(k)}</dt>
                    <dd className="tabular-nums">{String(v)}</dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="text-xs text-muted-foreground">
              A paused deployment keeps its open trades and their stops. Resuming starts the strategy fresh.
            </p>
          </CardContent>
        </Card>
      </Rise>

      <Rise i={3}>
        <Card>
          <CardHeader>
            <CardTitle>Open trades</CardTitle>
          </CardHeader>
          <CardContent className="min-w-0">
            {d.open_trades.length === 0 ? (
              <p className="text-sm text-muted-foreground">No open trades right now.</p>
            ) : (
              <TradesTable trades={d.open_trades} readOnly currency={d.currency} />
            )}
          </CardContent>
        </Card>
      </Rise>

      <Rise i={4}>
        <Card>
          <CardHeader>
            <CardTitle>Recent orders</CardTitle>
          </CardHeader>
          <CardContent className="min-w-0">
            {d.orders.length === 0 ? (
              <p className="text-sm text-muted-foreground">No orders yet. The strategy acts on each new bar while the market is open.</p>
            ) : (
              <OrdersTable orders={d.orders} readOnly currency={d.currency} />
            )}
          </CardContent>
        </Card>
      </Rise>

      <Rise i={5}>
        <LiveLog log={d.log} />
      </Rise>
    </>
  );
}

export function DeploymentRoute() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { data, isPending, error, refetch } = useDeployment(Number.isInteger(id) ? id : -1);

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <PageHeader
        title={data?.name ?? "Deployment"}
        eyebrow="HFT · Deployments"
        description={
          <Link href="/deployments" className="text-xs underline underline-offset-2">
            All deployments
          </Link>
        }
        actions={data && <DeploymentControls dep={data} />}
      />
      {error && !data && <QueryError error={error} title="Couldn't load this deployment" onRetry={() => refetch()} />}
      {isPending && !error && <Skeleton className="h-64 w-full" />}
      {data && <Detail d={data} />}
    </div>
  );
}
