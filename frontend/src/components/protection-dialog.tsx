"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { formatMoney, formatPrice, formatQuantity, isZero, parseApiTime, toNumber } from "@/lib/format";
import { useProtectionPreview, usePortfolio, useSetProtection } from "@/lib/queries";
import type { ProtectionOutcome, Trade } from "@/lib/types";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

const DECIMAL = /^\d*\.?\d*$/;

/** The price to send for what is typed: null for empty (clears it), undefined while it is not a price yet. */
function parsePrice(text: string): string | null | undefined {
  if (text.trim() === "") return null;
  const cleaned = text.replace(/\.$/, "");
  return /^\d*\.?\d+$/.test(cleaned) && toNumber(cleaned) > 0 ? cleaned : undefined;
}

function outcomeSentence(
  label: string,
  o: ProtectionOutcome,
  trade: Trade,
  accountCurrency: string,
): string {
  const cash = toNumber(o.cash_change);
  const pnl = toNumber(o.realized_pnl);
  const money = (v: number) => formatMoney(Math.abs(v), accountCurrency);
  const flow = cash >= 0 ? `you'd get back ${money(cash)}` : `you'd pay ${money(cash)} to buy back`;
  const result = isZero(o.realized_pnl)
    ? "break-even"
    : `a ${pnl > 0 ? "profit" : "loss"} of ${money(pnl)}`;
  return `If the ${label} fires at ${formatPrice(o.price, trade.currency)} ${flow} after ${money(
    toNumber(o.charges_total),
  )} charges — ${result}.`;
}

function PriceField({
  id,
  label,
  value,
  onChange,
  hint,
  error,
  outcome,
  outcomeLabel,
  trade,
  accountCurrency,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint: string;
  error: string | null;
  outcome: ProtectionOutcome | null;
  outcomeLabel: string;
  trade: Trade;
  accountCurrency: string;
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        <Input
          id={id}
          inputMode="decimal"
          autoComplete="off"
          placeholder="Not set"
          value={value}
          aria-invalid={!!error}
          aria-describedby={`${id}-help`}
          onChange={(e) => DECIMAL.test(e.target.value) && onChange(e.target.value)}
        />
        <Button type="button" variant="outline" disabled={value === ""} onClick={() => onChange("")}>
          Clear
        </Button>
      </div>
      <div id={`${id}-help`} className="grid gap-1 text-xs">
        <p className="text-muted-foreground">{hint}</p>
        {error ? (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        ) : (
          outcome && <p>{outcomeSentence(outcomeLabel, outcome, trade, accountCurrency)}</p>
        )}
      </div>
    </div>
  );
}

/**
 * Set or clear a trade's stop-loss and target. Mount it with `key={trade.id}` so the inputs start
 * from this trade's saved prices.
 */
export function ProtectionDialog({
  trade,
  open,
  onOpenChange,
}: {
  trade: Trade;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const accountCurrency = usePortfolio().data?.currency ?? trade.currency;
  const save = useSetProtection();
  const [stop, setStop] = useState(trade.stop_price ? formatQuantity(trade.stop_price) : "");
  const [target, setTarget] = useState(trade.target_price ? formatQuantity(trade.target_price) : "");

  const stopValue = parsePrice(stop);
  const targetValue = parsePrice(target);
  const typedOk = stopValue !== undefined && targetValue !== undefined;
  const wanted = useMemo(
    () => (typedOk ? { stop_price: stopValue, target_price: targetValue } : null),
    [typedOk, stopValue, targetValue],
  );
  const debounced = useDebounced(wanted, 300);
  const hasPrice = !!debounced && (debounced.stop_price !== null || debounced.target_price !== null);
  const preview = useProtectionPreview(trade.id, open && !save.isSuccess && hasPrice ? debounced : null);
  const p = hasPrice ? preview.data : undefined;
  const previewError = preview.error instanceof ApiError ? preview.error.message : null;
  // The figures belong to the prices they were worked out for, not to ones typed since.
  const settled = debounced === wanted;

  const stopError = stopValue === undefined ? "Enter a price, such as 1200.50." : settled ? (p?.stop_error ?? null) : null;
  const targetError = targetValue === undefined ? "Enter a price, such as 1400.50." : settled ? (p?.target_error ?? null) : null;

  const current = p?.current_price ?? trade.last_price;
  const now = current ? formatPrice(current, trade.currency) : "the current price";
  const long = trade.direction === "long";
  const stopHint = `${long ? "Below" : "Above"} ${now}${long ? ": it limits a fall." : ": it limits a rise."}`;
  const targetHint = `${long ? "Above" : "Below"} ${now}${long ? ": it takes a profit." : ": it takes a profit when the price falls."}`;

  const unchanged = (stopValue ?? "") === (trade.stop_price ? formatQuantity(trade.stop_price) : "") &&
    (targetValue ?? "") === (trade.target_price ? formatQuantity(trade.target_price) : "");
  const hasProtection = !!trade.stop_price || !!trade.target_price;
  const canSave = typedOk && !stopError && !targetError && !unchanged && !save.isPending;

  const timeZone = trade.timezone;
  const lapses = trade.protection_expires_at
    ? parseApiTime(trade.protection_expires_at).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone,
      })
    : null;

  function confirm() {
    if (!typedOk) return;
    save.mutate(
      { id: trade.id, stop_price: stopValue, target_price: targetValue },
      {
        onSuccess: () => {
          toast.success(
            stopValue === null && targetValue === null
              ? `Removed the stop-loss and target on ${trade.symbol}`
              : `Saved the stop-loss and target on ${trade.symbol}`,
          );
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] min-w-0 overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Stop-loss and target for {trade.symbol}</DialogTitle>
          <DialogDescription>
            Trade #{trade.id}: {trade.direction} {formatQuantity(trade.open_quantity)} open, entered at{" "}
            {formatPrice(trade.entry_price, trade.currency)}. When either price is reached the whole open part
            closes and the other one is cancelled.
          </DialogDescription>
        </DialogHeader>

        <PriceField
          id="protection-stop"
          label="Stop-loss price"
          value={stop}
          onChange={setStop}
          hint={stopHint}
          error={stopError}
          outcome={p?.stop_outcome ?? null}
          outcomeLabel="stop-loss"
          trade={trade}
          accountCurrency={accountCurrency}
        />
        <PriceField
          id="protection-target"
          label="Target price"
          value={target}
          onChange={setTarget}
          hint={targetHint}
          error={targetError}
          outcome={p?.target_outcome ?? null}
          outcomeLabel="target"
          trade={trade}
          accountCurrency={accountCurrency}
        />

        <p className={cn("text-xs text-muted-foreground", preview.isPlaceholderData && "opacity-60")}>
          {lapses ? `Lapses on ${lapses}, like a GTT.` : "Once set, it lapses after a year, like a GTT."}
        </p>

        <Alert>
          <AlertDescription>
            Prices here are delayed about 15 minutes, so a stop can fire late. A stop-loss sells at the market
            price when it triggers, not at your price — if the price gaps past it, you get out lower.
          </AlertDescription>
        </Alert>

        {(save.error || previewError) && (
          <Alert variant="destructive">
            <AlertDescription className="text-destructive">{save.error?.message ?? previewError}</AlertDescription>
          </Alert>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" disabled={!canSave} onClick={confirm}>
            {save.isPending ? "Saving..." : stop === "" && target === "" && hasProtection ? "Remove both" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
