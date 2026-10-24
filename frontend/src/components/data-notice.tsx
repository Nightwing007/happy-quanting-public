"use client";

import { useSyncExternalStore } from "react";
import { usePathname } from "next/navigation";
import { useHealth } from "@/lib/queries";

const noSubscribe = () => () => {};

/** Always visible: the data is delayed and nothing here is advice. */
export function DataNotice() {
  const { data } = useHealth();
  const pathname = usePathname();
  // The server never has the health result, but the browser's query cache can on its first
  // render; reading it only after mount keeps the two renders identical (no hydration error).
  const mounted = useSyncExternalStore(noSubscribe, () => true, () => false);
  // A simulation replays history, so "delayed ~15 minutes" would be wrong there.
  const replay = pathname.startsWith("/sim/");
  const source = replay
    ? "Replayed historical data"
    : mounted && data?.data_source === "fake"
      ? "Offline demo data"
      : "Prices delayed ~15 minutes, via Yahoo Finance";
  return (
    <footer className="mx-auto w-full max-w-7xl px-4 py-4 text-xs text-muted-foreground">
      {source}. Paper trading only — not financial advice.
    </footer>
  );
}
