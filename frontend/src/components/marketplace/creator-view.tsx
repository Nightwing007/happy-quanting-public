"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { BadgeCase } from "@/components/badges/badge-case";
import { QueryError } from "@/components/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import { UserAvatar } from "@/components/user-avatar";
import { CreatorBadges } from "@/components/badges/creator-badges";
import { useCreator, useListings, useUserBadges } from "@/lib/queries";
import { ListingCard, ListingSkeletons } from "./listing-card";

function CreatorView({ username }: { username: string }) {
  const creator = useCreator(username);
  const listings = useListings(null, username);
  const earned = useUserBadges(username);
  const shown = (earned.data?.earned ?? []).map((e) => e.id).filter((id) => ["debut", "trusted", "consistent", "craftsman", "champion"].includes(id));
  if (creator.error && !creator.data) {
    return <QueryError error={creator.error} title="Couldn't load this creator" onRetry={() => creator.refetch()} />;
  }
  if (!creator.data) return <Skeleton className="h-24 w-full" />;
  const c = creator.data;
  return (
    <div className="grid min-w-0 grid-cols-1 gap-6">
      <p className="text-sm">
        <Link href="/marketplace" className="text-muted-foreground underline-offset-2 hover:underline">
          Marketplace
        </Link>
      </p>
      <div className="flex items-center gap-4">
        <UserAvatar name={c.display_name} url={c.avatar_url} size="lg" />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">{c.display_name}</h1>
            <CreatorBadges ids={shown} />
          </div>
          <p className="text-sm text-muted-foreground">
            @{c.username} · {c.listing_count} published {c.listing_count === 1 ? "listing" : "listings"}
          </p>
        </div>
      </div>
      {c.bio && <p className="max-w-prose text-sm whitespace-pre-line">{c.bio}</p>}
      <section className="grid min-w-0 gap-3" aria-labelledby="creator-badges">
        <h2 id="creator-badges" className="text-lg font-semibold tracking-tight">
          Badges
        </h2>
        <BadgeCase username={c.username} />
      </section>
      <section className="grid min-w-0 gap-3" aria-labelledby="creator-listings">
        <h2 id="creator-listings" className="text-lg font-semibold tracking-tight">
          Listings
        </h2>
        {listings.error && !listings.data && (
          <QueryError error={listings.error} title="Couldn't load their listings" onRetry={() => listings.refetch()} />
        )}
        {listings.isPending && <ListingSkeletons />}
        {listings.data?.length === 0 && <p className="text-sm text-muted-foreground">Nothing published yet.</p>}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {listings.data?.map((l) => (
            <ListingCard key={l.id} listing={l} />
          ))}
        </div>
      </section>
    </div>
  );
}

export function CreatorRoute() {
  const { username } = useParams<{ username: string }>();
  return <CreatorView username={username} />;
}
