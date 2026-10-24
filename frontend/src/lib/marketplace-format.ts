import { formatPercent, formatRatio } from "./format";
import type { Instrument, Listing, ListingPerformance } from "./types";

/** The market filter. `value` is what `?market=` takes: a segment or a market code. */
export const MARKET_FILTERS: { label: string; value: string | null }[] = [
  { label: "All", value: null },
  { label: "India", value: "india" },
  { label: "US", value: "US" },
  { label: "Crypto", value: "crypto" },
  { label: "Global", value: "international" },
];

const MARKET_WORDS: Record<string, string> = { india: "India", international: "Global", crypto: "Crypto" };
export const marketWord = (m: string) => MARKET_WORDS[m] ?? m;

export const WINDOW_WORDS: Record<ListingPerformance["window"], string> = {
  "3mo": "3 months",
  "1y": "1 year",
  "3y": "3 years",
};

export const feeShort = (fee: string) => `Keeps ${formatRatio(fee, "%")} of net profit`;

export const feeTerms = (fee: string) =>
  `The creator keeps ${formatRatio(fee, "%")} of net realized profit after charges, and only on new highs: you never pay twice for recovering a loss.`;

/** The headline window when it is done, with a plain label saying which window it is. */
export function headlineStats(listing: Listing) {
  const h = listing.headline;
  if (!h?.results) return null;
  return {
    label: h.window === "1y" ? "1 year" : `Best available: ${WINDOW_WORDS[h.window]}`,
    ret: formatPercent(h.results.metrics.total_return_pct),
    returnValue: h.results.metrics.total_return_pct,
    drawdown: `-${formatRatio(h.results.metrics.max_drawdown_pct, "%")}`,
    trades: h.results.metrics.trade_count,
  };
}

/** Which segment and market code a search result trades on, from the same rule the server uses. */
function marketOf(i: Instrument): { segment: string; code: string } {
  if (i.type === "crypto") return { segment: "crypto", code: "CRYPTO" };
  if (!i.symbol.includes(".")) return { segment: "international", code: "US" };
  const suffix = i.symbol.slice(i.symbol.lastIndexOf(".")).toUpperCase();
  if (suffix === ".NS") return { segment: "india", code: "NSE" };
  if (suffix === ".BO") return { segment: "india", code: "BSE" };
  return { segment: "international", code: suffix };
}

/** A courtesy filter for the symbol picker; the server is the one that enforces markets. */
export function allowedBy(markets: string[], i: Instrument): boolean {
  if (!i.tradable) return false;
  const { segment, code } = marketOf(i);
  return markets.some((m) => m === segment || m.toUpperCase() === code);
}
