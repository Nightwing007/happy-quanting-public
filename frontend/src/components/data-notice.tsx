"use client";

import { usePathname } from "next/navigation";
import { useHealth } from "@/lib/queries";

/** Always visible: the data is delayed and nothing here is advice. */
export function DataNotice() {
  const { data } = useHealth();
  const pathname = usePathname();
  // A simulation replays history, so "delayed ~15 minutes" would be wrong there.
  const replay = pathname.startsWith("/sim/");
  const source = replay
    ? "Replayed historical data"
    : data?.data_source === "fake"
      ? "Offline demo data"
      : "Prices delayed ~15 minutes, via Yahoo Finance";
  return (
    <footer className="mx-auto w-full max-w-7xl px-4 py-4 text-xs text-muted-foreground">
      {source}. Paper trading only — not financial advice.
    </footer>
  );
}
