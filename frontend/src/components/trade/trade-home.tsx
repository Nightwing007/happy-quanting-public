"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";
import { LiveDot } from "@/components/motion/live-dot";
import { PageHeader } from "@/components/motion/page-header";
import { Rise } from "@/components/motion/rise";
import { useDirectionalHover } from "@/components/motion/directional-hover";
import { marketTone } from "@/components/trade/quote-header";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPercent, formatPrice, isZero, toNumber } from "@/lib/format";
import { usePopularQuote, useWatchlist } from "@/lib/queries";
import { parseRecent, readRecentRaw, subscribeRecent } from "@/lib/recent-symbols";
import { cn } from "@/lib/utils";

// One symbol per region stands for its market hours: the quote carries the market's own label.
const REGIONS = [
  { name: "India", symbol: "RELIANCE.NS" },
  { name: "US", symbol: "AAPL" },
  { name: "Crypto", symbol: "BTC-USD" },
  { name: "London", symbol: "VOD.L" },
  { name: "Hong Kong", symbol: "0700.HK" },
  { name: "Tokyo", symbol: "7203.T" },
  { name: "Germany", symbol: "SAP.DE" },
];

const POPULAR = [
  { title: "India", symbols: ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS"] },
  { title: "US", symbols: ["AAPL", "MSFT", "NVDA", "TSLA"] },
  { title: "Crypto", symbols: ["BTC-USD", "ETH-USD"] },
  { title: "Global", symbols: ["VOD.L", "SAP.DE", "0700.HK", "7203.T"] },
];

const tradeHref = (symbol: string) => `/trade?symbol=${encodeURIComponent(symbol)}`;

function RegionStatus({ name, symbol }: { name: string; symbol: string }) {
  const { data: quote, isPending } = usePopularQuote(symbol);
  const market = quote?.market ?? null;
  return (
    <li className="flex min-w-0 items-center gap-3 border border-line bg-panel px-3 py-2">
      <LiveDot tone={market ? marketTone(market) : "off"} pulse={market?.state === "open"} />
      <span className="min-w-0">
        <span className="block text-sm font-medium">{name}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {isPending ? "Checking..." : market ? market.label : "No data"}
        </span>
      </span>
    </li>
  );
}

/** A symbol that links to its trade page; the sheet floods in from the pointer's edge. */
function Tile({
  symbol,
  name,
  price,
  currency,
  change,
  percent,
  loading,
}: {
  symbol: string;
  name?: string;
  price?: string | null;
  currency?: string | null;
  change?: string | null;
  percent?: string | null;
  loading?: boolean;
}) {
  const dh = useDirectionalHover({ flood: true });
  const hasPrice = price !== null && price !== undefined;
  const hasChange = hasPrice && change != null && percent != null;
  return (
    <Link
      href={tradeHref(symbol)}
      className={cn(dh.className, "flex min-w-0 items-center justify-between gap-3 p-4")}
      onPointerEnter={dh.onPointerEnter}
      onPointerLeave={dh.onPointerLeave}
    >
      <span className="min-w-0">
        <span className="block font-medium">{symbol}</span>
        {name && <span className="block truncate text-xs text-muted-foreground">{name}</span>}
      </span>
      <span className="shrink-0 text-right">
        {loading ? (
          <Skeleton className="h-9 w-20" />
        ) : (
          <>
            <span className="tabular-nums block">{hasPrice ? formatPrice(price, currency ?? "USD") : "-"}</span>
            <span
              className={cn(
                "tabular-nums block text-xs",
                hasChange && !isZero(change) ? (toNumber(change) > 0 ? "text-up" : "text-down") : "text-muted-foreground",
              )}
            >
              {hasChange ? formatPercent(percent) : "-"}
            </span>
          </>
        )}
      </span>
    </Link>
  );
}

function QuoteTile({ symbol }: { symbol: string }) {
  const { data: q, isPending } = usePopularQuote(symbol);
  return (
    <Tile
      symbol={symbol}
      name={q?.name}
      price={q?.price}
      currency={q?.currency}
      change={q?.change}
      percent={q?.change_percent}
      loading={isPending}
    />
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="t-meta mb-2 text-dim">{children}</h2>;
}

function Watchlist() {
  const { data: items, isPending } = useWatchlist();
  return (
    <section aria-label="Your watchlist">
      <SectionTitle>Your watchlist</SectionTitle>
      {isPending && <Skeleton className="h-20 w-full" />}
      {items && items.length === 0 && (
        <p className="border border-line bg-panel p-4 text-sm text-muted-foreground">
          Nothing watched yet. Open a symbol and press Watch to keep it here.
        </p>
      )}
      {items && items.length > 0 && (
        <ul className="ledger grid-cols-1 md:grid-cols-2">
          {items.map((w) => (
            <li key={w.symbol}>
              <Tile symbol={w.symbol} name={w.name} price={w.price} currency={w.currency} change={w.change} percent={w.change_percent} />
            </li>
          ))}
          {/* An odd count would leave the last grid cell showing the rule colour; this fills it. */}
          {items.length % 2 === 1 && <li aria-hidden="true" className="hidden md:block" />}
        </ul>
      )}
    </section>
  );
}

function RecentlyViewed() {
  const raw = useSyncExternalStore(subscribeRecent, readRecentRaw, () => "[]");
  const recent = parseRecent(raw);
  if (recent.length === 0) return null;
  return (
    <section aria-label="Recently viewed">
      <SectionTitle>Recently viewed</SectionTitle>
      <ul className="flex flex-wrap gap-2">
        {recent.map((symbol) => (
          <li key={symbol}>
            <Link
              href={tradeHref(symbol)}
              className="t-meta block border border-line-hot px-3 py-2 text-foreground transition-colors duration-200 hover:bg-wash"
            >
              {symbol}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The Trade page with no symbol: never empty. Market hours, your watchlist, popular symbols, recent ones. */
export function TradeHome() {
  return (
    <div className="grid grid-cols-1 gap-6">
      <PageHeader
        title="Trade"
        eyebrow="Markets"
        description={
          <>
            Pick a symbol below, or press <kbd className="t-meta border border-line-hot px-1">Ctrl K</kbd> to search.
          </>
        }
      />

      <Rise i={1}>
        <section aria-label="Market status">
          <SectionTitle>Market status</SectionTitle>
          <ul className="grid grid-cols-1 gap-2 min-[480px]:grid-cols-2 lg:grid-cols-4">
            {REGIONS.map((r) => (
              <RegionStatus key={r.name} {...r} />
            ))}
          </ul>
        </section>
      </Rise>

      <Rise i={2} className="grid gap-6">
        <Watchlist />
        <RecentlyViewed />
      </Rise>

      <Rise i={3} className="grid gap-6">
        {POPULAR.map((group) => (
          <section key={group.title} aria-label={`Popular in ${group.title}`}>
            <SectionTitle>{`Popular · ${group.title}`}</SectionTitle>
            <ul className={cn("ledger grid-cols-1 sm:grid-cols-2", group.symbols.length > 2 && "lg:grid-cols-4")}>
              {group.symbols.map((symbol) => (
                <li key={symbol}>
                  <QuoteTile symbol={symbol} />
                </li>
              ))}
            </ul>
          </section>
        ))}
      </Rise>
    </div>
  );
}
