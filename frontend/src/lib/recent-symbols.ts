// Recently viewed symbols live in this browser only (localStorage); every access is guarded because storage can
// be blocked or empty (private windows, previews) and the page must work without it.
const KEY = "hq.recent-symbols";
const MAX = 8;
const EVENT = "hq:recent-symbols";

export function readRecentRaw(): string {
  try {
    return window.localStorage.getItem(KEY) ?? "[]";
  } catch {
    return "[]";
  }
}

export function parseRecent(raw: string): string[] {
  try {
    const v: unknown = JSON.parse(raw);
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string").slice(0, MAX) : [];
  } catch {
    return [];
  }
}

/** Puts `symbol` first, dropping a later duplicate and anything past the cap. */
export function pushRecent(symbol: string) {
  try {
    const next = [symbol, ...parseRecent(readRecentRaw()).filter((s) => s !== symbol)].slice(0, MAX);
    window.localStorage.setItem(KEY, JSON.stringify(next));
    window.dispatchEvent(new Event(EVENT));
  } catch {
    // Storage unavailable: the list just won't remember.
  }
}

export function subscribeRecent(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}
