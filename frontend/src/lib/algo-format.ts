import { toNumber } from "./format";
import type { AlgoParam, HistoryLimits } from "./types";

export const MARKET_LABELS: Record<string, string> = {
  india: "India",
  international: "International",
  crypto: "Crypto",
};

const INTERVAL_WORDS: Record<string, string> = { "1d": "Daily", "1h": "1-hour", "1wk": "Weekly", "1mo": "Monthly" };

export const algoIntervalWords = (id: string) => INTERVAL_WORDS[id] ?? id;

export const isIntraday = (interval: string) => !["1d", "1wk", "1mo"].includes(interval);

/** "stamp_duty" as sentence-case words: "Stamp duty". */
export function categoryLabel(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}

export const CLOSED_HOW_WORDS: Record<string, string> = {
  exit: "Exit",
  sell: "Sold",
  cover: "Covered",
  square_off: "Squared off",
  stop_loss: "Stop-loss",
  target: "Target",
};

export const closedHowLabel = (how: string | null | undefined) =>
  how ? (CLOSED_HOW_WORDS[how] ?? categoryLabel(how)) : "Still open";

/** "Daily data: any date. 1-hour: back to 25 Oct 2024." from the server's limits. */
export function historyLimitsText(limits: HistoryLimits, formatDay: (d: string) => string): string {
  const part = (interval: string, name: string) => {
    const earliest = limits.limits.find((l) => l.interval === interval)?.earliest;
    return `${name}: ${earliest ? `back to ${formatDay(earliest)}` : "any date"}.`;
  };
  return `${part("1d", "Daily data")} ${part("1h", "1-hour")}`;
}

/** A plain number for ratios that are not money: "1.2" -> "1.20". */
export function formatPlain(value: string | number | null | undefined, decimals = 2): string {
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(
    toNumber(value),
  );
}

/** The smallest chart range (as the bars route names them) that reaches back to `start`. */
export function chartRangeFor(interval: string, start: string, today: string): string {
  const days = Math.max(0, (Date.parse(`${today}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000);
  const steps: [number, string][] =
    interval === "1h"
      ? [
          [1, "1d"],
          [5, "5d"],
          [30, "1mo"],
          [90, "3mo"],
          [180, "6mo"],
        ]
      : [
          [30, "1mo"],
          [90, "3mo"],
          [180, "6mo"],
          [365, "1y"],
          [730, "2y"],
          [1825, "5y"],
          [3650, "10y"],
        ];
  for (const [limit, range] of steps) if (days <= limit) return range;
  return interval === "1h" ? "1y" : "max";
}

export type ParamValue = string | number | boolean;

/** Decimal places in a number-like value: "0.25" -> 2. */
const decimalsOf = (v: string | number | boolean | null | undefined) => {
  const m = /\.(\d+)/.exec(String(v ?? ""));
  return m ? m[1].length : 0;
};

/** Slider step: as fine as the default and the bounds are written. */
export function sliderStep(p: AlgoParam): number {
  if (p.kind === "int") return 1;
  return 10 ** -Math.max(decimalsOf(p.default), decimalsOf(p.min), decimalsOf(p.max));
}

/** The server's own wording for a setting that is out of bounds, so the form and the API agree. */
export function paramProblem(p: AlgoParam, raw: ParamValue): string | null {
  if (p.kind === "bool" || p.kind === "choice") return null;
  const text = String(raw).trim();
  const n = Number(text);
  if (text === "" || !Number.isFinite(n)) return `${p.label} must be a number, not '${text}'.`;
  if (p.kind === "int" && !Number.isInteger(n)) return `${p.label} must be a whole number, not '${text}'.`;
  if (p.min !== null && n < Number(p.min)) return `${p.label} must be at least ${p.min}, not ${text}.`;
  if (p.max !== null && n > Number(p.max)) return `${p.label} must be at most ${p.max}, not ${text}.`;
  return null;
}

/** What goes in the request: whole numbers as numbers, decimals as the text typed. */
export function paramPayload(p: AlgoParam, raw: ParamValue): string | number | boolean {
  if (p.kind === "int") return Number(raw);
  if (p.kind === "decimal") return String(raw).trim();
  return raw;
}

/** The same calendar day one year earlier, as YYYY-MM-DD. */
export function yearBefore(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCFullYear(d.getUTCFullYear() - 1);
  return d.toISOString().slice(0, 10);
}
