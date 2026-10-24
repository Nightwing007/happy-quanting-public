"use client";

import { Term } from "@/components/term";
import Link from "next/link";
import { CreatorBadges } from "@/components/badges/creator-badges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { UserAvatar } from "@/components/user-avatar";
import { algoIntervalWords } from "@/lib/algo-format";
import { toNumber } from "@/lib/format";
import { feeShort, headlineStats, marketWord } from "@/lib/marketplace-format";
import type { Listing } from "@/lib/types";

export function CreatorLink({ creator }: { creator: Listing["creator"] }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Link href={`/creators/${creator.username}`} className="inline-flex min-w-0 items-center gap-2 hover:underline">
        <UserAvatar name={creator.display_name} url={creator.avatar_url} />
        <span className="truncate text-sm font-medium">{creator.display_name}</span>
      </Link>
      <CreatorBadges ids={creator.badges} />
    </div>
  );
}

export function ListingCard({ listing }: { listing: Listing }) {
  const stats = headlineStats(listing);
  return (
    <Card>
      <CardHeader className="gap-2">
        <CreatorLink creator={listing.creator} />
        <CardTitle className="text-base">
          <Link href={`/marketplace/${listing.id}`} className="hover:underline">
            {listing.name}
          </Link>
        </CardTitle>
        <p className="text-sm text-muted-foreground">{listing.tagline}</p>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-1 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {listing.markets.map((m) => (
            <Badge key={m} variant="secondary">
              {marketWord(m)}
            </Badge>
          ))}
          <Badge variant="outline">{algoIntervalWords(listing.interval)} bars</Badge>
        </div>
        {stats ? (
          <div>
            <p className="text-xs text-muted-foreground">{stats.label}</p>
            <dl className="mt-1 grid grid-cols-3 gap-2">
              <div>
                <dt className="text-xs text-muted-foreground">Return</dt>
                <dd
                  className={`font-semibold tabular-nums ${toNumber(stats.returnValue) < 0 ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400"}`}
                >
                  {stats.ret}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">
                  <Term id="max_drawdown">Max drawdown</Term>
                </dt>
                <dd className="font-semibold tabular-nums">{stats.drawdown}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Trades</dt>
                <dd className="font-semibold tabular-nums">{stats.trades}</dd>
              </div>
            </dl>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Performance is still being measured.</p>
        )}
        <div className="mt-auto flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm">{feeShort(listing.fee_percent)}</p>
          <Button size="sm" variant="outline" nativeButton={false} render={<Link href={`/marketplace/${listing.id}`} />}>
            View
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function ListingSkeletons() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Loading listings">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-56 w-full" />
      ))}
    </div>
  );
}
