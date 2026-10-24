"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { QueryError } from "@/components/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import { useDeleteSimSession, useSimSessions } from "@/lib/queries";
import { formatDayRange, intervalWords, STATUS_WORDS } from "@/lib/sim-format";

export function SimList() {
  const { data, isPending, error, refetch } = useSimSessions();
  const remove = useDeleteSimSession();
  const [confirming, setConfirming] = useState<number | null>(null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your simulations</CardTitle>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-2">
        {error && !data && <QueryError error={error} title="Couldn't load your simulations" onRetry={() => refetch()} />}
        {isPending && <Skeleton className="h-16 w-full" />}
        {data && data.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No simulations yet. Pick a past day below and practise on it: every simulation has its own cash and trades,
            separate from your real paper account.
          </p>
        )}
        {remove.error && (
          <p role="alert" className="text-sm text-destructive">
            {remove.error.message}
          </p>
        )}
        {data?.map((s) => (
          <div key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border p-3">
            <div className="min-w-0 flex-1 basis-40">
              <p className="truncate font-medium">{s.symbols.join(", ")}</p>
              <p className="text-xs text-muted-foreground">
                {intervalWords(s.interval)} bars · {formatDayRange(s)} · {s.progress_percent}% played
              </p>
            </div>
            <Badge variant={s.status === "running" ? "default" : "secondary"}>{STATUS_WORDS[s.status]}</Badge>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" nativeButton={false} render={<Link href={`/sim/${s.id}`} />}>
                Open
              </Button>
              {confirming === s.id ? (
                <>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(s.id, { onSettled: () => setConfirming(null) })}
                  >
                    Delete for good
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                    Keep
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="outline" onClick={() => setConfirming(s.id)}>
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
