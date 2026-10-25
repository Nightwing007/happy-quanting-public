"use client";

import { useMemo, useState } from "react";
import { QueryError } from "@/components/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Term } from "@/components/term";
import { REGION_LABEL } from "@/lib/badge-art";
import { useBadgeCatalog, useMyBadges, useUserBadges } from "@/lib/queries";
import type { BadgeInfo, EarnedBadge } from "@/lib/types";
import { BadgeIcon } from "./badge-icon";
import { BadgeTip, earnedDate } from "./badge-tip";

function Tile({ badge, earnedAt }: { badge: BadgeInfo; earnedAt?: string }) {
  const earned = earnedAt !== undefined;
  return (
    <li className="min-w-0">
      <BadgeTip
        name={badge.name}
        hint={badge.hint}
        earnedAt={earnedAt}
        locked={!earned}
        testId={`badge-${badge.id}`}
        className="flex h-full w-full flex-col items-center gap-1.5 border p-3 text-center hover:bg-muted/50"
      >
        <span data-state={earned ? "earned" : "locked"} className="contents">
          <BadgeIcon id={badge.id} name={badge.name} size="md" locked={!earned} />
          <span className="text-sm font-medium">{badge.name}</span>
          <span className="text-xs leading-snug text-muted-foreground">
            {earned ? `Earned ${earnedDate(earnedAt)}` : badge.hint}
          </span>
        </span>
      </BadgeTip>
    </li>
  );
}

/** A user's badges by region. Without `username` it is the signed-in user's own case. */
export function BadgeCase({ username }: { username?: string }) {
  const catalog = useBadgeCatalog();
  const mine = useMyBadges(username === undefined);
  const theirs = useUserBadges(username ?? "");
  const [picked, setPicked] = useState("kanto");

  const earnedList: EarnedBadge[] | undefined = username === undefined ? mine.data?.earned : theirs.data?.earned;
  const earnedAt = useMemo(() => new Map((earnedList ?? []).map((e) => [e.id, e.earned_at])), [earnedList]);

  const error = catalog.error ?? (username === undefined ? mine.error : theirs.error);
  if (error && !(catalog.data && earnedList)) {
    return (
      <QueryError
        error={error}
        title="Couldn't load the badges"
        onRetry={() => {
          catalog.refetch();
          (username === undefined ? mine : theirs).refetch();
        }}
      />
    );
  }
  if (!catalog.data || !earnedList) return <Skeleton className="h-64 w-full" />;

  const all = catalog.data.regions.flatMap((r) => r.badges);
  const champion = all.find((b) => b.id === "champion");
  const countEarned = all.filter((b) => earnedAt.has(b.id)).length;

  return (
    <section className="grid min-w-0 gap-3" aria-label="Badge case">
      <p className="text-sm" data-testid="badge-count">
        <span className="font-semibold">
          {countEarned} of {all.length} <Term id="badge">badges</Term>
        </span>
        {champion && earnedAt.has("champion") && (
          <span className="ml-2 font-semibold text-warn">
            · <Term id="champion">Champion</Term>
          </span>
        )}
      </p>
      <Tabs value={picked} onValueChange={(v) => setPicked(String(v))} className="min-w-0">
        <TabsList className="h-auto w-full flex-wrap justify-start">
          {catalog.data.regions.map((r) => (
            <TabsTrigger key={r.id} value={r.id} className="h-7 flex-none px-2 text-xs sm:text-sm">
              {REGION_LABEL[r.id] ?? r.name}
            </TabsTrigger>
          ))}
        </TabsList>
        {catalog.data.regions.map((r) => {
          const own = r.badges.filter((b) => b.id !== "champion");
          const done = own.filter((b) => earnedAt.has(b.id)).length;
          return (
            <TabsContent key={r.id} value={r.id} className="grid min-w-0 gap-3">
              <p className="text-xs text-muted-foreground">
                {done} of {own.length} in {r.id === "elite" ? "the Elite Four" : <Term id="region">{r.name}</Term>}
              </p>
              <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {own.map((b) => (
                  <Tile key={b.id} badge={b} earnedAt={earnedAt.get(b.id)} />
                ))}
              </ul>
              {r.id === "elite" && champion && (
                <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Tile badge={champion} earnedAt={earnedAt.get("champion")} />
                </ul>
              )}
            </TabsContent>
          );
        })}
      </Tabs>
    </section>
  );
}
