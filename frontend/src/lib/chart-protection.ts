import { toNumber } from "@/lib/format";
import type { Trade } from "@/lib/types";
import type { ChartPriceLine } from "@/components/trade/price-chart";

/**
 * The price closest to `current`, by distance. Not the smallest: a long's stop sits below the
 * price and its target above, so the one that fires first is the one nearest today's price.
 */
export function nearestPrice(prices: number[], current: number): number | null {
  let best: number | null = null;
  for (const p of prices) {
    if (best === null || Math.abs(p - current) < Math.abs(best - current)) best = p;
  }
  return best;
}

/** A red "Stop" and a green "Target" line for a symbol's open trades: the nearest of each. */
export function protectionLines(trades: Trade[], current: number | null): ChartPriceLine[] {
  if (current === null) return [];
  const open = trades.filter((t) => t.status === "open");
  const stop = nearestPrice(
    open.flatMap((t) => (t.stop_price ? [toNumber(t.stop_price)] : [])),
    current,
  );
  const target = nearestPrice(
    open.flatMap((t) => (t.target_price ? [toNumber(t.target_price)] : [])),
    current,
  );
  const lines: ChartPriceLine[] = [];
  if (stop !== null) lines.push({ price: stop, title: "Stop", color: "#dc2626", dashed: true });
  if (target !== null) lines.push({ price: target, title: "Target", color: "#16a34a", dashed: true });
  return lines;
}
