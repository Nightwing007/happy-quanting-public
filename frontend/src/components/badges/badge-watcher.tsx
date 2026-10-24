"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { useAcknowledgeBadgeSummary, useBadgeCatalog, useMarkBadgesSeen, useMe, useMyBadges } from "@/lib/queries";
import type { BadgeInfo } from "@/lib/types";
import { BadgeIcon } from "./badge-icon";

function UnlockToast({ badge }: { badge: BadgeInfo }) {
  const title = badge.id === "champion" ? "You are the Champion!" : `You earned the ${badge.name} Badge!`;
  return (
    <div className="flex w-full items-center gap-3 rounded-lg border bg-popover p-3 text-popover-foreground shadow-lg sm:w-[356px]">
      <BadgeIcon id={badge.id} name={badge.name} size="lg" />
      <div className="grid min-w-0 gap-0.5">
        <p className="text-sm font-semibold">{title}</p>
        <p className="text-xs text-muted-foreground">{badge.hint}</p>
      </div>
    </div>
  );
}

function SummaryToast({ count, dismiss }: { count: number; dismiss: () => void }) {
  return (
    <div className="flex w-full items-center justify-between gap-3 rounded-lg border bg-popover p-3 text-popover-foreground shadow-lg sm:w-[356px]">
      <p className="text-sm font-medium">
        You&apos;ve earned {count} {count === 1 ? "badge" : "badges"} from your past activity
      </p>
      <Link href="/badges" onClick={dismiss} className="shrink-0 text-sm font-medium underline underline-offset-2">
        View badges
      </Link>
    </div>
  );
}

/** Mounted once in the layout: toasts each new badge, and one summary for past activity. Renders nothing.
 *  It starts a moment after load so its first request never races a page still hydrating from the
 *  same cached `me` (a page that reads `isPending` would see data too early and mismatch). */
export function BadgeWatcher() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setReady(true), 1500);
    return () => clearTimeout(t);
  }, []);
  return ready ? <Watching /> : null;
}

function Watching() {
  const me = useMe();
  const signedIn = !!me.data;
  const catalog = useBadgeCatalog();
  const badges = useMyBadges(signedIn);
  const markSeen = useMarkBadgesSeen();
  const ack = useAcknowledgeBadgeSummary();
  // Ids already toasted this page load: a refetch can land before the "seen" write does.
  const shown = useRef(new Set<string>());
  const summaryShown = useRef(false);
  const { mutate: markSeenNow } = markSeen;
  const { mutate: ackSummary } = ack;

  const data = badges.data;
  const regions = catalog.data?.regions;
  useEffect(() => {
    if (!signedIn || !data || !regions) return;
    const byId = new Map(regions.flatMap((r) => r.badges).map((b) => [b.id, b]));
    const fresh = data.new.filter((id) => !shown.current.has(id) && byId.has(id));
    for (const id of fresh) {
      shown.current.add(id);
      toast.custom(() => <UnlockToast badge={byId.get(id)!} />, { duration: 8000 });
    }
    if (fresh.length > 0) markSeenNow(fresh);

    if (data.backfill_summary && !summaryShown.current) {
      summaryShown.current = true;
      const count = data.backfill_summary;
      toast.custom((t) => <SummaryToast count={count} dismiss={() => toast.dismiss(t)} />, { duration: 12000 });
      ackSummary();
    }
  }, [signedIn, data, regions, markSeenNow, ackSummary]);

  return null;
}
