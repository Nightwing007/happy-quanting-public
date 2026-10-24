"use client";

import { BadgeCase } from "@/components/badges/badge-case";
import { useMe } from "@/lib/queries";

export default function BadgesPage() {
  const { data: user, isPending } = useMe();
  if (isPending) return <p className="text-sm text-muted-foreground">Loading...</p>;
  if (!user) return <p className="text-sm text-muted-foreground">Please log in to see your badges.</p>;
  return (
    <div className="grid min-w-0 gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Your badges</h1>
        <p className="text-sm text-muted-foreground">
          Rewards for protecting your trades and exploring new markets. Hover or tap a badge to see how it is earned.
        </p>
      </div>
      <BadgeCase />
    </div>
  );
}
