"use client";

import { useState } from "react";
import Link from "next/link";
import { QueryError } from "@/components/query-error";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRatio } from "@/lib/format";
import { WINDOW_WORDS } from "@/lib/marketplace-format";
import { useEarnings, useMyListings, usePublishListing, useRetireListing } from "@/lib/queries";
import { formatDay } from "@/lib/sim-format";
import type { ListingEarnings, ListingOwner } from "@/lib/types";

const STATUS_BADGE: Record<ListingOwner["status"], { label: string; variant: "default" | "secondary" | "outline" }> = {
  published: { label: "Published", variant: "default" },
  draft: { label: "Draft", variant: "secondary" },
  retired: { label: "Retired", variant: "outline" },
};

const day = (iso: string) => formatDay(iso.slice(0, 10));

function RetireButton({ listing }: { listing: ListingOwner }) {
  const retire = useRetireListing();
  const [open, setOpen] = useState(false);
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) retire.reset();
      }}
    >
      <AlertDialogTrigger render={<Button variant="outline" size="sm" />}>Retire</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Retire {listing.name}?</AlertDialogTitle>
          <AlertDialogDescription>
            It disappears from the marketplace and no one new can subscribe. People already subscribed keep running
            until they stop it themselves.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {retire.error && (
          <Alert variant="destructive">
            <AlertDescription>{retire.error.message}</AlertDescription>
          </Alert>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>Keep it listed</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={retire.isPending}
            onClick={(e) => {
              e.preventDefault(); // stay open until the server answers, so a refusal can be shown
              retire.mutate(listing.id, { onSuccess: () => setOpen(false) });
            }}
          >
            {retire.isPending ? "Retiring..." : "Retire listing"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function PublishButton({ listing }: { listing: ListingOwner }) {
  const publish = usePublishListing();
  return (
    <div className="grid gap-1">
      <Button size="sm" disabled={publish.isPending} onClick={() => publish.mutate(listing.id)}>
        {publish.isPending ? "Publishing..." : "Publish"}
      </Button>
      {publish.error && (
        <p role="alert" className="text-xs text-destructive">
          {publish.error.message}
        </p>
      )}
    </div>
  );
}

function ListingCard({ listing, earnings }: { listing: ListingOwner; earnings: ListingEarnings | undefined }) {
  const badge = STATUS_BADGE[listing.status];
  const latest = listing.versions.at(-1);
  return (
    <Card>
      <CardHeader className="gap-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>{listing.name}</CardTitle>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
        {listing.tagline && <p className="text-sm text-muted-foreground">{listing.tagline}</p>}
      </CardHeader>
      <CardContent className="grid min-w-0 gap-3">
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-muted-foreground">Version</dt>
            <dd className="font-medium tabular-nums">{listing.version}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Created</dt>
            <dd className="font-medium">{day(listing.created_at)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Latest version</dt>
            <dd className="font-medium">{latest ? day(latest.created_at) : "-"}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Subscribers</dt>
            <dd className="font-medium tabular-nums">
              {earnings ? `${earnings.active_subscribers} active, ${earnings.subscribers} ever` : "-"}
            </dd>
          </div>
        </dl>
        <p className="text-xs text-muted-foreground">Fee: you keep {formatRatio(listing.fee_percent, "%")} of net profit above a high.</p>
        <div className="flex flex-wrap gap-1.5" aria-label="Performance measurements">
          {listing.performance.map((p) => (
            <Badge key={p.window} variant={p.status === "done" ? "secondary" : "outline"} title={p.note ?? undefined}>
              {WINDOW_WORDS[p.window]}: {p.status}
            </Badge>
          ))}
          {listing.performance.length === 0 && <span className="text-xs text-muted-foreground">Not measured yet.</span>}
        </div>
        <div className="flex flex-wrap items-start gap-2">
          <Button variant="outline" size="sm" nativeButton={false} render={<Link href={`/marketplace/${listing.id}`} />}>
            View
          </Button>
          {listing.status !== "retired" && (
            <Button variant="outline" size="sm" nativeButton={false} render={<Link href={`/create/upload?listing=${listing.id}`} />}>
              Upload a new version
            </Button>
          )}
          {listing.status === "draft" && <PublishButton listing={listing} />}
          {listing.status !== "retired" && <RetireButton listing={listing} />}
        </div>
      </CardContent>
    </Card>
  );
}

export function MyListings() {
  const { data, isPending, error, refetch } = useMyListings();
  const earnings = useEarnings();
  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
        <h2 className="t-head text-xl">My listings</h2>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" nativeButton={false} render={<Link href="/marketplace/earnings" />}>
            Earnings
          </Button>
          <Button nativeButton={false} render={<Link href="/create/upload" />}>
            Upload a strategy
          </Button>
        </div>
      </div>
      {error && !data && <QueryError error={error} title="Couldn't load your listings" onRetry={() => refetch()} />}
      {isPending && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-56 w-full" />
        </div>
      )}
      {data && data.length === 0 && (
        <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          You haven&apos;t listed anything yet.{" "}
          <Link href="/create/upload" className="underline underline-offset-2">
            Upload a strategy
          </Link>
          .
        </p>
      )}
      {data && data.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {data.map((l) => (
            <ListingCard key={l.id} listing={l} earnings={earnings.data?.listings.find((e) => e.listing_id === l.id)} />
          ))}
        </div>
      )}
    </div>
  );
}
