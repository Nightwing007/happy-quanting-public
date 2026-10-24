// The only place API decimal strings become numbers, and only for display.

export function toNumber(s: string | number | null | undefined): number {
  if (s === null || s === undefined || s === "") return 0;
  const n = typeof s === "number" ? s : Number(s);
  return Number.isFinite(n) ? n : 0;
}

/** True for "0", "0.00", "-0.0" - never compare the strings themselves. */
export const isZero = (s: string | number | null | undefined) => toNumber(s) === 0;

function locale(currency: string) {
  return currency === "INR" ? "en-IN" : "en-US";
}

function formatCurrency(value: number, currency: string, decimals: number, signed: boolean) {
  const options = {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    signDisplay: signed ? "exceptZero" : "auto",
  } as const;
  try {
    return new Intl.NumberFormat(locale(currency), { ...options, style: "currency", currency }).format(value);
  } catch {
    // Intl throws on a malformed currency code; show the number with the code after it.
    return `${new Intl.NumberFormat("en-US", options).format(value)} ${currency}`;
  }
}

/** Decimal places for a price: 2 from 1 upwards; below 1, enough to show 4 significant digits (max 8). */
export function priceDecimals(value: number): number {
  const abs = Math.abs(value);
  if (abs >= 1 || abs === 0) return 2;
  const leadingZeros = Math.floor(-Math.log10(abs)); // 0.05 -> 1, 0.00012 -> 3
  return Math.min(8, Math.max(2, leadingZeros + 4));
}

export function formatMoney(value: string | number | null | undefined, currency: string): string {
  return formatCurrency(toNumber(value), currency, 2, false);
}

export function formatPrice(value: string | number | null | undefined, currency: string): string {
  const n = toNumber(value);
  return formatCurrency(n, currency, priceDecimals(n), false);
}

/** A price move, using the decimal rule of the price it is measured against: "+$0.81", not "+$0.8100". */
export function formatPriceChange(
  change: string | number | null | undefined,
  currency: string,
  referencePrice: string | number | null | undefined,
): string {
  return formatCurrency(toNumber(change), currency, priceDecimals(toNumber(referencePrice)), true);
}

/** "+1.25%", "-0.5%", "0%": signed, trailing zeros trimmed. */
export function formatPercent(value: string | number | null | undefined, maxDecimals = 2): string {
  const text = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: maxDecimals,
    signDisplay: "exceptZero",
  }).format(toNumber(value));
  return `${text}%`;
}

/** "24.8x", "30x", "18.5%", "60%": at most one decimal, trailing zeros trimmed. */
export function formatRatio(value: string | number | null | undefined, unit: "x" | "%" | string): string {
  const text = new Intl.NumberFormat("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 1 }).format(
    toNumber(value),
  );
  return `${text}${unit}`;
}

// Fewer decimals as numbers grow: "₹4,520 crore" and "₹12.5 lakh", never "₹4,520.00 crore".
const unitDecimals = (n: number) => (n >= 100 ? 0 : 1);

function trimmed(n: number, locale: string, decimals: number): string {
  return new Intl.NumberFormat(locale, { minimumFractionDigits: 0, maximumFractionDigits: decimals }).format(n);
}

/**
 * A large amount in the units its readers use. Rupees get lakh and crore ("₹138 lakh crore", with
 * 1 lakh crore = 10^12); other currencies get compact Western units ("$3.4T", "$820B"). With no
 * currency it is a plain count ("19.8M").
 */
export function formatLargeAmount(value: string | number | null | undefined, currency?: string | null): string {
  const n = toNumber(value);
  if (currency === "INR") {
    const abs = Math.abs(n);
    const steps: [number, string][] = [
      [1e12, "lakh crore"],
      [1e7, "crore"],
      [1e5, "lakh"],
    ];
    for (const [size, name] of steps) {
      if (abs >= size) return `₹${trimmed(n / size, "en-IN", unitDecimals(abs / size))} ${name}`;
    }
    return `₹${trimmed(n, "en-IN", 2)}`;
  }
  const options = { notation: "compact", minimumFractionDigits: 0, maximumFractionDigits: 1 } as const;
  if (currency) {
    try {
      return new Intl.NumberFormat("en-US", { ...options, style: "currency", currency }).format(n);
    } catch {
      // Malformed currency code: fall through to the plain count with the code after it.
      return `${new Intl.NumberFormat("en-US", options).format(n)} ${currency}`;
    }
  }
  return new Intl.NumberFormat("en-US", options).format(n);
}

/** Up to 8 decimals with trailing zeros trimmed: "10", "0.5", "0.00012345". */
export function formatQuantity(value: string | number | null | undefined): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
    useGrouping: false,
  }).format(toNumber(value));
}

/** "an index", "a currency", "an ETF", "an FX pair". */
export function article(word: string): string {
  const w = word.trim();
  // Spoken letter names start with a vowel sound for F, H, L, M, N, R, S, X ("eff", "aitch"...),
  // so an all-caps acronym like ETF or FX takes "an" even though its first letter is a consonant.
  const acronym = /^[A-Z]{2,5}$/.test(w);
  const vowelSound = acronym ? /^[AEIOFHLMNRSX]/.test(w) : /^[aeiou]/i.test(w);
  return vowelSound ? `an ${word}` : `a ${word}`;
}

/** The API sends UTC timestamps, sometimes without a zone suffix; read them as UTC either way. */
export function parseApiTime(iso: string): Date {
  return new Date(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`);
}

/** "24 Oct, 15:20 IST": a moment in the given exchange zone (the viewer's own zone if unknown). */
export function formatZonedTime(iso: string, timeZone: string | undefined): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone,
      timeZoneName: "short",
    }).format(parseApiTime(iso));
  } catch {
    return parseApiTime(iso).toLocaleString();
  }
}
