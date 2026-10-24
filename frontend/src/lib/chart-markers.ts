import type { Time } from "lightweight-charts";
import { parseApiTime } from "./format";
import type { Bar, Order } from "./types";

type LegKind = Order["legs"][number]["kind"];

export type FillMarker = {
  time: Time;
  position: "aboveBar" | "belowBar";
  shape: "arrowUp" | "arrowDown";
  color: string;
  text: string;
};

// Arrows follow the direction of the trade, not the order: a cover is a buy, so it points up.
export const MARKER_STYLES: Record<LegKind, Omit<FillMarker, "time" | "text"> & { label: string }> = {
  open_long: { label: "Buy", position: "belowBar", shape: "arrowUp", color: "#16a34a" },
  close_long: { label: "Sell", position: "aboveBar", shape: "arrowDown", color: "#dc2626" },
  open_short: { label: "Short", position: "aboveBar", shape: "arrowDown", color: "#f97316" },
  close_short: { label: "Cover", position: "belowBar", shape: "arrowUp", color: "#3b82f6" },
};

function zonedParts(ms: number, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(ms);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  return { y: get("year"), mo: get("month"), d: get("day"), h: get("hour"), mi: get("minute"), s: get("second") };
}

/**
 * Where a fill sits on the chart. Daily bars are keyed "YYYY-MM-DD" and intraday bars by
 * exchange-local seconds (the backend shifts them by the exchange's UTC offset), so the fill
 * has to be read on the exchange's clock, not the viewer's.
 */
function fillTime(filledAt: string, timeZone: string, intraday: boolean): string | number {
  const { y, mo, d, h, mi, s } = zonedParts(parseApiTime(filledAt).getTime(), timeZone);
  if (intraday) return Date.UTC(y, mo - 1, d, h, mi, s) / 1000;
  return `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

// Bar times are all strings (daily) or all numbers (intraday), and fill times match; JS orders both.
const before = (a: string | number, b: string | number) => (a as number) < (b as number);

/** Last bar whose start is at or before `t`; null when the fill predates the whole chart. */
function barFor(bars: Bar[], t: string | number): string | number | null {
  let found: string | number | null = null;
  for (const bar of bars) {
    if (!before(t, bar.time)) found = bar.time;
    else break;
  }
  return found;
}

/** One marker per bar and kind (with a count when several fills share a bar), sorted by time. */
export function buildFillMarkers(
  orders: Order[],
  bars: Bar[],
  intraday: boolean,
  timeZone: string | undefined,
): FillMarker[] {
  if (!bars.length) return [];
  const zone = timeZone ?? "UTC";
  const groups = new Map<string, { time: string | number; kind: LegKind; count: number }>();
  for (const order of orders) {
    if (order.status !== "filled" || !order.filled_at) continue;
    const barTime = barFor(bars, fillTime(order.filled_at, zone, intraday));
    if (barTime === null) continue;
    for (const leg of order.legs) {
      const key = `${barTime}|${leg.kind}`;
      const group = groups.get(key);
      if (group) group.count += 1;
      else groups.set(key, { time: barTime, kind: leg.kind, count: 1 });
    }
  }
  return [...groups.values()]
    .sort((a, b) => (before(a.time, b.time) ? -1 : before(b.time, a.time) ? 1 : 0))
    .map(({ time, kind, count }) => {
      const { label, ...style } = MARKER_STYLES[kind];
      return { ...style, time: time as Time, text: count > 1 ? `${label} ×${count}` : label };
    });
}
