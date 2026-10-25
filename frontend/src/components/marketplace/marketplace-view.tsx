"use client";

import { useState } from "react";
import Link from "next/link";
import { QueryError } from "@/components/query-error";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { MARKET_FILTERS } from "@/lib/marketplace-format";
import { useListings } from "@/lib/queries";
import { ListingCard, ListingSkeletons } from "./listing-card";
import { PageHeader } from "@/components/motion/page-header";

export function MarketplaceView() {
  const [market, setMarket] = useState<string | null>(null);
  const { data, isPending, error, refetch } = useListings(market);
  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <PageHeader
        title="Marketplace"
        eyebrow="HFT · Market"
        description="Algorithms by other people, with performance measured on real charges. You see how they performed, never how they work."
        actions={
          <Button variant="outline" nativeButton={false} render={<Link href="/marketplace/subscriptions" />}>
            My subscriptions
          </Button>
        }
      />
      <ToggleGroup
        variant="outline"
        size="sm"
        spacing={0}
        aria-label="Market"
        value={[market ?? "all"]}
        onValueChange={(v) => v[0] && setMarket(v[0] === "all" ? null : v[0])}
        className="flex-wrap"
      >
        {MARKET_FILTERS.map((f) => (
          <ToggleGroupItem key={f.label} value={f.value ?? "all"}>
            {f.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      {error && !data && <QueryError error={error} title="Couldn't load the marketplace" onRetry={() => refetch()} />}
      {isPending && <ListingSkeletons />}
      {data && data.length === 0 && (
        <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          No algorithms listed{market ? " for this market" : ""} yet.
        </p>
      )}
      {data && data.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((l) => (
            <ListingCard key={l.id} listing={l} />
          ))}
        </div>
      )}
    </div>
  );
}
