"use client";

import { PayoutsPanel } from "@/components/payouts-panel";
import { PageHeader } from "@/components/motion/page-header";

export default function PayoutsPage() {
  return (
    <div className="grid grid-cols-1 gap-4">
      <PageHeader title="Payouts" eyebrow="Account" />
      <PayoutsPanel />
    </div>
  );
}
