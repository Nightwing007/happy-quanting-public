"use client";

import Link from "next/link";
import { StatusLamp } from "@/components/deployments/deployment-controls";
import { Pnl } from "@/components/pnl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toNumber } from "@/lib/format";
import { useDeployments } from "@/lib/queries";

/** Your running deployments with their P&L; nothing at all when there are none. */
export function DeploymentsCard() {
  const live = useDeployments().data?.filter((d) => d.status === "active" || d.status === "paused");
  if (!live || live.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <Link href="/deployments" className="hover:underline">
            Deployments
          </Link>
        </CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        <ul className="grid gap-2 text-sm">
          {live.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
              <Link href={`/deployments/${d.id}`} className="min-w-0 font-medium hover:underline">
                {d.name}
              </Link>
              <span className="flex items-center gap-3">
                <StatusLamp status={d.status} />
                <Pnl value={toNumber(d.realized_pnl) + toNumber(d.unrealized_pnl)} currency={d.currency} />
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
