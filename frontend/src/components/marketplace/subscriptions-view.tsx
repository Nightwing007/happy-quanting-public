"use client";

import { Term } from "@/components/term";
import type { TermId } from "@/lib/glossary";
import { useState } from "react";
import Link from "next/link";
import { QueryError } from "@/components/query-error";
import { Pnl } from "@/components/pnl";
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
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney, formatRatio } from "@/lib/format";
import { useListing, useStopSubscription, useSubscriptions, useUpgradeSubscription } from "@/lib/queries";
import type { Subscription } from "@/lib/types";
import { PageHeader } from "@/components/motion/page-header";

const STATUS_BADGE: Record<Subscription["status"], { label: string; variant: "default" | "secondary" | "outline" }> = {
  active: { label: "Running", variant: "default" },
  stopping: { label: "Stopping", variant: "secondary" },
  stopped: { label: "Stopped", variant: "outline" },
};

function Figure({ label, children, term }: { label: string; children: React.ReactNode; term?: TermId }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{term ? <Term id={term}>{label}</Term> : label}</dt>
      <dd className="font-medium tabular-nums">{children}</dd>
    </div>
  );
}

function StopButton({ sub }: { sub: Subscription }) {
  const stop = useStopSubscription();
  const [open, setOpen] = useState(false);
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) stop.reset();
      }}
    >
      <AlertDialogTrigger render={<Button variant="outline" size="sm" />}>Stop</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Stop {sub.listing_name}?</AlertDialogTitle>
          <AlertDialogDescription>
            Any open trades are exited at market, and the cash returns to your account, less any fee due to the creator.
            If the markets are closed, it waits for them to open first.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {stop.error && (
          <Alert variant="destructive">
            <AlertDescription>{stop.error.message}</AlertDescription>
          </Alert>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>Keep it running</AlertDialogCancel>
          <AlertDialogAction variant="destructive" disabled={stop.isPending} onClick={(e) => {
              e.preventDefault(); // stay open until the server answers, so a refusal can be shown
              stop.mutate(sub.id, { onSuccess: () => setOpen(false) });
            }}>
            {stop.isPending ? "Stopping…" : "Stop subscription"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function UpgradeNotice({ sub, changelog }: { sub: Subscription; changelog: string | null | undefined }) {
  const upgrade = useUpgradeSubscription();
  const [open, setOpen] = useState(false);
  return (
    <div className="grid gap-2 rounded-lg border border-primary/40 bg-primary/5 p-3 text-sm">
      <p className="font-medium">Version {sub.latest_version} available</p>
      <p className="text-muted-foreground">{changelog ? changelog : "The creator didn't add notes for this version."}</p>
      <div>
        <AlertDialog
          open={open}
          onOpenChange={(next) => {
            setOpen(next);
            if (!next) upgrade.reset();
          }}
        >
          <AlertDialogTrigger render={<Button size="sm" />}>Upgrade</AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                Upgrade {sub.listing_name} to version {sub.latest_version}?
              </AlertDialogTitle>
              <AlertDialogDescription>
                From the next bar this subscription trades with the new code instead of version {sub.listing_version}.
                Open trades stay open, the strategy&apos;s own memory starts fresh, and the fee stays{" "}
                {formatRatio(sub.fee_percent, "%")}.
              </AlertDialogDescription>
            </AlertDialogHeader>
            {upgrade.error && (
              <Alert variant="destructive">
                <AlertDescription>{upgrade.error.message}</AlertDescription>
              </Alert>
            )}
            <AlertDialogFooter>
              <AlertDialogCancel>Stay on version {sub.listing_version}</AlertDialogCancel>
              <AlertDialogAction
                disabled={upgrade.isPending}
                onClick={(e) => {
                  e.preventDefault(); // stay open until the server answers, so a refusal can be shown
                  upgrade.mutate(sub.id, { onSuccess: () => setOpen(false) });
                }}
              >
                {upgrade.isPending ? "Upgrading..." : "Upgrade"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  );
}

function SubscriptionCard({ sub }: { sub: Subscription }) {
  // The listing is already cached from the marketplace pages in most visits; this gives the creator's name.
  const listing = useListing(sub.listing_id).data;
  const badge = STATUS_BADGE[sub.status];
  return (
    <Card>
      <CardHeader className="gap-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>
            <Link href={`/marketplace/${sub.listing_id}`} className="hover:underline">
              {sub.listing_name}
            </Link>
          </CardTitle>
          <Badge variant={badge.variant}>{badge.label}</Badge>
        </div>
        {listing && (
          <p className="text-sm text-muted-foreground">
            by{" "}
            <Link href={`/creators/${listing.creator.username}`} className="underline-offset-2 hover:underline">
              {listing.creator.display_name}
            </Link>
          </p>
        )}
      </CardHeader>
      <CardContent className="grid min-w-0 gap-3">
        <div className="flex flex-wrap gap-1.5">
          {sub.symbols.map((s) => (
            <Badge key={s} variant="secondary">
              {s}
            </Badge>
          ))}
        </div>
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          <Figure label="Capital">{formatMoney(sub.capital, sub.currency)}</Figure>
          <Figure label={sub.status === "stopped" ? "Returned" : "Equity now"}>{formatMoney(sub.equity, sub.currency)}</Figure>
          <Figure label="Realized P&L" term="realized_pnl">
            <Pnl value={sub.realized_pnl} currency={sub.currency} />
          </Figure>
          <Figure label="Unrealized P&L" term="unrealized_pnl">
            <Pnl value={sub.unrealized_pnl} currency={sub.currency} />
          </Figure>
          <Figure label={`Fees paid (${formatRatio(sub.fee_percent, "%")})`} term="performance_fee">{formatMoney(sub.fees_paid, sub.currency)}</Figure>
          <Figure label="High-water mark" term="high_water_mark">{formatMoney(sub.high_water_mark, sub.currency)}</Figure>
        </dl>
        <p className="text-xs text-muted-foreground">Running version {sub.listing_version}.</p>
        {sub.status === "active" && sub.upgrade_available && (
          <UpgradeNotice sub={sub} changelog={listing?.versions.find((v) => v.version === sub.latest_version)?.changelog} />
        )}
        {sub.status === "stopping" && (
          <p className="text-sm text-muted-foreground">
            Waiting for markets to open so the open trades can be exited. The cash returns once it is flat.
          </p>
        )}
        {sub.status === "active" && (
          <div>
            <StopButton sub={sub} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function SubscriptionsView() {
  const { data, isPending, error, refetch } = useSubscriptions();
  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <PageHeader
        title="My subscriptions"
        eyebrow="HFT · Market"
        actions={
          <Button variant="outline" nativeButton={false} render={<Link href="/marketplace" />}>
            Browse the marketplace
          </Button>
        }
      />
      {error && !data && <QueryError error={error} title="Couldn't load your subscriptions" onRetry={() => refetch()} />}
      {isPending && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      )}
      {data && data.length === 0 && (
        <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          You aren&apos;t subscribed to anything yet.{" "}
          <Link href="/marketplace" className="underline underline-offset-2">
            Browse the marketplace
          </Link>
          .
        </p>
      )}
      {data && data.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {data.map((s) => (
            <SubscriptionCard key={s.id} sub={s} />
          ))}
        </div>
      )}
    </div>
  );
}
