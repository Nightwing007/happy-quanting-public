"use client";

import { PageHeader } from "@/components/motion/page-header";
import { BadgeCase } from "@/components/badges/badge-case";
import { useMe } from "@/lib/queries";

export default function BadgesPage() {
  const { data: user, isPending } = useMe();
  if (isPending) return <p className="text-sm text-muted-foreground">Loading...</p>;
  if (!user) return <p className="text-sm text-muted-foreground">Please log in to see your badges.</p>;
  return (
    <div className="grid min-w-0 gap-4">
      <PageHeader
        title="Your badges"
        eyebrow="Rewards"
        description="Rewards for protecting your trades and exploring new markets. Hover or tap a badge to see how it is earned."
      />
      <BadgeCase />
    </div>
  );
}
