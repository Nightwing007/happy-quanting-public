"use client";

import { useHealth } from "@/lib/queries";

/** Always visible: the data is delayed and nothing here is advice. */
export function DataNotice() {
  const { data } = useHealth();
  const source = data?.data_source === "fake" ? "Offline demo data" : "Prices delayed ~15 minutes, via Yahoo Finance";
  return (
    <footer className="mx-auto w-full max-w-7xl px-4 py-4 text-xs text-muted-foreground">
      {source}. Paper trading only — not financial advice.
    </footer>
  );
}
