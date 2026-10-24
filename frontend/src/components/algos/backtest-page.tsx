"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { QueryError } from "@/components/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import { useBacktest } from "@/lib/queries";
import { BacktestOutcome } from "./backtest-outcome";

/** /algos/backtests/[id]: one stored backtest, with the same results view as the lab. */
export function BacktestPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const valid = Number.isInteger(id) && id > 0;
  const { data, error, refetch } = useBacktest(valid ? id : null);

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <div className="grid gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Backtest {valid ? `#${id}` : ""}</h1>
        <p className="text-xs text-muted-foreground">
          <Link href="/algos/backtests" className="underline underline-offset-2">
            Backtest history
          </Link>
        </p>
      </div>
      {!valid && <p className="text-sm text-destructive">That is not a backtest number.</p>}
      {error && !data && <QueryError error={error} title="Couldn't load this backtest" onRetry={() => refetch()} />}
      {valid && !data && !error && <Skeleton className="h-64 w-full" />}
      {data && <BacktestOutcome detail={data} />}
    </div>
  );
}
