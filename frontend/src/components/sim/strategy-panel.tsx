"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { algoIntervalWords } from "@/lib/algo-format";
import type { SimSessionState } from "@/lib/types";

const KIND_WORDS = {
  library: "Ready-made algorithm",
  mine: "My algorithm",
  source: "Your code",
  listing: "Marketplace algorithm",
} as const;

/** The algorithm trading this simulation and what it has logged (the server sends no log for listings). */
export function StrategyPanel({ session }: { session: SimSessionState }) {
  const strategy = session.strategy;
  if (!strategy) return null;
  const log = session.strategy_log;
  return (
    <Card>
      <CardContent className="grid min-w-0 gap-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h2 className="font-semibold">{strategy.name}</h2>
          <Badge variant="secondary">{KIND_WORDS[strategy.kind]}</Badge>
          <span className="text-xs text-muted-foreground">
            {algoIntervalWords(strategy.interval)} bars{strategy.creator ? ` · by ${strategy.creator}` : ""}
          </span>
        </div>
        {strategy.kind === "listing" ? (
          <p className="text-xs text-muted-foreground">The creator keeps the code and its log private.</p>
        ) : (
          <details>
            <summary className="cursor-pointer text-sm font-medium">Strategy log ({log.length} lines)</summary>
            {log.length === 0 ? (
              <p className="mt-2 text-sm text-muted-foreground">The strategy has not written to its log yet.</p>
            ) : (
              <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-muted/50 p-3 text-xs whitespace-pre-wrap">
                {log.map((l) => `${l.at.slice(0, 16).replace("T", " ")}  ${l.text}`).join("\n")}
              </pre>
            )}
          </details>
        )}
      </CardContent>
    </Card>
  );
}
