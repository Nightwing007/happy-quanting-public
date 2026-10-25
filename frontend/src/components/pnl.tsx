import { formatMoney, formatPercent, isZero, toNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Colour for a signed money string; zero stays neutral. Never compares the strings. */
export function pnlClass(value: string | number | null | undefined) {
  if (isZero(value)) return "text-muted-foreground";
  return toNumber(value) > 0 ? "text-up" : "text-down";
}

/** A signed, coloured profit/loss amount with an optional percentage. */
export function Pnl({
  value,
  currency,
  percent,
  className,
}: {
  value: string | number | null | undefined;
  currency: string;
  percent?: string | number | null;
  className?: string;
}) {
  const n = toNumber(value);
  const sign = isZero(value) ? "" : n > 0 ? "+" : "-";
  return (
    <span className={cn("tabular-nums", pnlClass(value), className)}>
      {sign}
      {formatMoney(Math.abs(n), currency)}
      {percent !== undefined && percent !== null && ` (${formatPercent(percent)})`}
    </span>
  );
}
