"use client";

import { useState } from "react";
import Link from "next/link";
import { QueryError } from "@/components/query-error";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { algoIntervalWords, MARKET_LABELS } from "@/lib/algo-format";
import { useAlgoLibrary, useDeleteMyAlgo, useMyAlgos } from "@/lib/queries";

function Markets({ markets }: { markets: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {markets.map((m) => (
        <Badge key={m} variant="secondary">
          {MARKET_LABELS[m] ?? m}
        </Badge>
      ))}
    </div>
  );
}

function Library() {
  const { data, isPending, error, refetch } = useAlgoLibrary();
  return (
    <section className="grid min-w-0 gap-3" aria-labelledby="library-heading">
      <h2 id="library-heading" className="text-lg font-semibold tracking-tight">
        Ready-made algorithms
      </h2>
      {error && !data && <QueryError error={error} title="Couldn't load the algorithms" onRetry={() => refetch()} />}
      {isPending && <Skeleton className="h-40 w-full" />}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data?.map((a) => (
          <Card key={a.key}>
            <CardHeader>
              <CardTitle>{a.name}</CardTitle>
            </CardHeader>
            <CardContent className="flex min-w-0 flex-1 flex-col gap-3">
              <p className="text-sm text-muted-foreground">{a.description}</p>
              <div className="mt-auto grid gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Markets markets={a.markets} />
                  <Badge variant="outline">{algoIntervalWords(a.interval)} bars</Badge>
                </div>
                <div>
                  <Button size="sm" nativeButton={false} render={<Link href={`/algos/lab?algo=${a.key}`} />}>
                    Open in lab
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

function Mine() {
  const { data, isPending, error, refetch } = useMyAlgos();
  const remove = useDeleteMyAlgo();
  const [confirming, setConfirming] = useState<number | null>(null);
  return (
    <section className="grid min-w-0 gap-3" aria-labelledby="mine-heading">
      <h2 id="mine-heading" className="text-lg font-semibold tracking-tight">
        My algorithms
      </h2>
      {error && !data && <QueryError error={error} title="Couldn't load your algorithms" onRetry={() => refetch()} />}
      {isPending && <Skeleton className="h-24 w-full" />}
      {data && data.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Nothing saved yet. Tune an algorithm in the lab and choose &ldquo;Save as my algorithm&rdquo; on the
          results, or write your own in the editor.
        </p>
      )}
      {remove.error && (
        <p role="alert" className="text-sm text-destructive">
          {remove.error.message}
        </p>
      )}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data?.map((a) => (
          <Card key={a.id}>
            <CardHeader>
              <CardTitle>{a.name}</CardTitle>
            </CardHeader>
            <CardContent className="grid min-w-0 gap-3">
              <p className="text-xs text-muted-foreground">
                {a.source !== null ? "Your own code" : `Built on ${a.strategy_name}`}
              </p>
              {a.description && <p className="text-sm text-muted-foreground">{a.description}</p>}
              <div className="flex flex-wrap items-center gap-2">
                <Markets markets={a.markets} />
                <Badge variant="outline">{algoIntervalWords(a.interval)} bars</Badge>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {a.source !== null ? (
                  <Button size="sm" nativeButton={false} render={<Link href={`/algos/editor?mine=${a.id}`} />}>
                    Edit in editor
                  </Button>
                ) : (
                  <Button size="sm" nativeButton={false} render={<Link href={`/algos/lab?mine=${a.id}`} />}>
                    Open in lab
                  </Button>
                )}
                {confirming === a.id ? (
                  <>
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(a.id, { onSettled: () => setConfirming(null) })}
                    >
                      Delete for good
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                      Keep
                    </Button>
                  </>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => setConfirming(a.id)}>
                    Delete
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

export function AlgoGallery() {
  return (
    <div className="grid min-w-0 grid-cols-1 gap-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="grid gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Algorithms</h1>
          <p className="text-sm text-muted-foreground">
            Choose one, change its settings, and test it on past prices with the real charges your broker would
            take.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" nativeButton={false} render={<Link href="/algos/editor" />}>
            Code editor
          </Button>
          <Button variant="outline" size="sm" nativeButton={false} render={<Link href="/algos/backtests" />}>
            Backtest history
          </Button>
        </div>
      </div>
      <Library />
      <Mine />
    </div>
  );
}
