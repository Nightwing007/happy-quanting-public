import { parseApiTime } from "./format";
import type { SimSession } from "./types";

export const SIM_INTERVALS = [
  { id: "1m", label: "1-minute" },
  { id: "5m", label: "5-minute" },
  { id: "15m", label: "15-minute" },
] as const;

export const intervalWords = (id: string) => SIM_INTERVALS.find((i) => i.id === id)?.label ?? id;

/** "23 Oct 2026" from a "YYYY-MM-DD" date. Read as UTC so the viewer's zone cannot shift the day. */
export function formatDay(day: string): string {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(
    new Date(`${day}T00:00:00Z`),
  );
}

export const formatDayRange = (s: Pick<SimSession, "start_date" | "end_date">) =>
  s.start_date === s.end_date ? formatDay(s.start_date) : `${formatDay(s.start_date)} to ${formatDay(s.end_date)}`;

// Intl's short zone names fall back to GMT offsets ("GMT+5:30") for most zones outside the US,
// so the zones people trade in are named here.
const ZONE_NAMES: Record<string, string> = {
  "Asia/Kolkata": "IST",
  "America/New_York": "ET",
  "Europe/London": "UK",
  "Asia/Hong_Kong": "HKT",
  "Asia/Tokyo": "JST",
  "Asia/Singapore": "SGT",
  UTC: "UTC",
};

/** "IST" for Asia/Kolkata; a zone not listed gets whatever Intl offers. */
export function zoneShortName(timeZone: string, at: Date = new Date()): string {
  const mapped = ZONE_NAMES[timeZone];
  if (mapped) return mapped;
  try {
    const part = new Intl.DateTimeFormat("en-GB", { timeZone, timeZoneName: "short" })
      .formatToParts(at)
      .find((p) => p.type === "timeZoneName");
    return part?.value ?? timeZone;
  } catch {
    return timeZone;
  }
}

/** "Fri 23 Oct, 09:20:00 IST": the replayed moment on the exchange's own clock. */
export function formatExchangeClock(iso: string, timeZone: string): string {
  const when = parseApiTime(iso);
  try {
    const text = new Intl.DateTimeFormat("en-GB", {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
      timeZone,
    }).format(when);
    return `${text} ${zoneShortName(timeZone, when)}`;
  } catch {
    return when.toLocaleString();
  }
}

export const STATUS_WORDS: Record<SimSession["status"], string> = {
  ready: "Ready",
  running: "Running",
  paused: "Paused",
  finished: "Finished",
};
