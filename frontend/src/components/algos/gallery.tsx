"use client";

import { useState } from "react";
import Link from "next/link";
import { QueryError } from "@/components/query-error";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { algoIntervalWords, MARKET_LABELS } from "@/lib/algo-format";
import { useAlgoLibrary, useDeleteMyAlgo, useHosted, useMyAlgos } from "@/lib/queries";
import { DeployButton } from "@/components/deployments/deploy-dialog";
import { PageHeader } from "@/components/motion/page-header";
import { useDirectionalHover } from "@/components/motion/directional-hover";
import type { Algo } from "@/lib/types";

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
          <LibraryCard key={a.key} a={a} />
        ))}
      </div>
    </section>
  );
}

function LibraryCard({ a }: { a: Algo }) {
  const dh = useDirectionalHover({ flood: true });
  return (
    <Card className={dh.className} onPointerEnter={dh.onPointerEnter} onPointerLeave={dh.onPointerLeave}>
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
  );
}

function Mine() {
  const hosted = useHosted();
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
          results, or build one in the block editor or write your own code.
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
                {a.graph ? "Built with blocks" : a.source !== null ? "Your own code" : `Built on ${a.strategy_name}`}
              </p>
              {a.description && <p className="text-sm text-muted-foreground">{a.description}</p>}
              <div className="flex flex-wrap items-center gap-2">
                <Markets markets={a.markets} />
                <Badge variant="outline">{algoIntervalWords(a.interval)} bars</Badge>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {a.graph ? (
                  <Button size="sm" nativeButton={false} render={<Link href={`/create/blocks?mine=${a.id}`} />}>
                    Edit in block editor
                  </Button>
                ) : a.source !== null ? (
                  hosted ? (
                    <span className="text-xs text-muted-foreground">Code upload is turned off on this hosted demo</span>
                  ) : (
                    <Button size="sm" nativeButton={false} render={<Link href={`/create/editor?mine=${a.id}`} />}>
                      Edit in editor
                    </Button>
                  )
                ) : (
                  <Button size="sm" nativeButton={false} render={<Link href={`/algos/lab?mine=${a.id}`} />}>
                    Open in lab
                  </Button>
                )}
                {!(hosted && !a.graph && a.source !== null) && (
                <DeployButton
                  name={a.name}
                  markets={a.markets}
                  what={{ algo_id: a.id }}
                  source={`${a.name}, ${a.graph ? "built with blocks" : a.source !== null ? "your own code" : `built on ${a.strategy_name}`}`}
                />
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
  const hosted = useHosted();
  return (
    <div className="grid min-w-0 grid-cols-1 gap-6">
      <PageHeader
        title="Algorithms"
        eyebrow="HFT · Algo"
        description="Choose one, change its settings, and test it on past prices with the real charges your broker would take."
        actions={
          <>
            <Button size="sm" nativeButton={false} render={<Link href="/create/blocks" />}>
              Block editor
            </Button>
            {!hosted && (
              <Button variant="outline" size="sm" nativeButton={false} render={<Link href="/create/editor" />}>
                Code editor
              </Button>
            )}
            <Button variant="outline" size="sm" nativeButton={false} render={<Link href="/algos/backtests" />}>
              Backtest history
            </Button>
          </>
        }
      />
      <Library />
      <Mine />
    </div>
  );
}
