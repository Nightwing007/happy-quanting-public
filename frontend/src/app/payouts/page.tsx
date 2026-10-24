"use client";

import { PayoutsPanel } from "@/components/payouts-panel";

export default function PayoutsPage() {
  return (
    <div className="grid grid-cols-1 gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">Payouts</h1>
      <PayoutsPanel />
    </div>
  );
}
