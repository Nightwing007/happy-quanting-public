"use client";

import { useState } from "react";
import Link from "next/link";
import { QueryError } from "@/components/query-error";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { algoIntervalWords } from "@/lib/algo-format";
import { formatMoney } from "@/lib/format";
import { useAlgoLibrary, useBacktests, useDeleteBacktest } from "@/lib/queries";
import { formatDay } from "@/lib/sim-format";

const STATUS_WORDS = { queued: "Queued", running: "Running", done: "Done", failed: "Failed" } as const;

export function BacktestList() {
  const { data, isPending, error, refetch } = useBacktests();
  const library = useAlgoLibrary();
  const remove = useDeleteBacktest();
  const [confirming, setConfirming] = useState<number | null>(null);
  const nameOf = (key: string) => library.data?.find((a) => a.key === key)?.name ?? key;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Backtest history</CardTitle>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-2">
        {error && !data && <QueryError error={error} title="Couldn't load your backtests" onRetry={() => refetch()} />}
        {isPending && <Skeleton className="h-16 w-full" />}
        {data && data.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No backtests yet.{" "}
            <Link href="/algos" className="underline underline-offset-2">
              Pick an algorithm
            </Link>{" "}
            and run one in the lab.
          </p>
        )}
        {remove.error && (
          <p role="alert" className="text-sm text-destructive">
            {remove.error.message}
          </p>
        )}
        {data?.map((b) => (
          <div key={b.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border p-3">
            <div className="min-w-0 flex-1 basis-48">
              <p className="truncate font-medium">
                {nameOf(b.strategy_key)} · {b.symbols.join(", ")}
              </p>
              <p className="text-xs text-muted-foreground">
                {algoIntervalWords(b.interval)} bars · {formatDay(b.start_date)} to {formatDay(b.end_date)} · cash{" "}
                {formatMoney(b.starting_cash, b.account_currency)}
              </p>
              {b.status === "failed" && b.error && <p className="text-xs text-destructive">{b.error}</p>}
            </div>
            <Badge variant={b.status === "failed" ? "destructive" : b.status === "done" ? "secondary" : "default"}>
              {STATUS_WORDS[b.status]}
              {(b.status === "running" || b.status === "queued") && ` ${b.progress}%`}
            </Badge>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" nativeButton={false} render={<Link href={`/algos/backtests/${b.id}`} />}>
                Open
              </Button>
              {confirming === b.id ? (
                <>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(b.id, { onSettled: () => setConfirming(null) })}
                  >
                    Delete for good
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                    Keep
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="outline" onClick={() => setConfirming(b.id)}>
                  Delete
                </Button>
              )}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
