"use client";

import { useState } from "react";
import { toast } from "sonner";
import { unitFor } from "@/components/order-legs";
import { Pnl } from "@/components/pnl";
import { Term } from "@/components/term";
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
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { formatMoney, formatPrice, formatQuantity, isZero, toNumber } from "@/lib/format";
import { useExitPreview, useExitTrade, usePortfolio } from "@/lib/queries";
import type { Order, Trade } from "@/lib/types";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

const DECIMAL = /^\d*\.?\d*$/;

function Row({ label, children, strong }: { label: React.ReactNode; children: React.ReactNode; strong?: boolean }) {
  return (
    <div className={cn("flex justify-between gap-2", strong && "border-t pt-1.5 font-medium")}>
      <dt className={cn("min-w-0", !strong && "text-muted-foreground")}>{label}</dt>
      <dd className="text-right tabular-nums">{children}</dd>
    </div>
  );
}

function successMessage(order: Order, trade: Trade, accountCurrency: string): string {
  const verb = trade.direction === "short" ? "Covered" : "Sold";
  const pnl = toNumber(order.realized_pnl);
  const result = isZero(order.realized_pnl)
    ? "break-even"
    : `${pnl > 0 ? "profit" : "loss"} ${formatMoney(Math.abs(pnl), accountCurrency)}`;
  return `${verb} ${formatQuantity(order.quantity)} ${order.symbol} at ${formatPrice(order.fill_price, order.currency)} (${result})`;
}

/**
 * Shows the payout before you commit. Mount it with `key={trade.id}` so the quantity resets
 * for each trade.
 */
export function ExitDialog({
  trade,
  open,
  onOpenChange,
}: {
  trade: Trade;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const accountCurrency = usePortfolio().data?.currency ?? trade.currency;
  const exit = useExitTrade();
  const [quantity, setQuantity] = useState(formatQuantity(trade.open_quantity));
  const [rejection, setRejection] = useState<string | null>(null);

  const qtyNumber = DECIMAL.test(quantity) ? toNumber(quantity) : 0;
  const valid = qtyNumber > 0;
  const cleaned = quantity.replace(/\.$/, "");
  const debounced = useDebounced(valid ? cleaned : null, 300);
  // Off while closed and once the exit went through: the trade may be gone and the server would refuse.
  const preview = useExitPreview(
    trade.id,
    debounced ?? undefined,
    open && !exit.isSuccess && valid && debounced !== null,
  );

  const previewError = valid && preview.error instanceof ApiError ? preview.error : null;
  const p = valid && !previewError ? preview.data : undefined;
  const error = rejection ?? (exit.error ? exit.error.message : null);
  const unit = unitFor(trade.market_code);
  const covering = trade.direction === "short";

  function confirm() {
    if (!valid) return;
    setRejection(null);
    exit.mutate(
      { id: trade.id, quantity: cleaned },
      {
        onSuccess: (order) => {
          if (order.status === "rejected") {
            setRejection(order.reject_reason ?? "The exit was rejected.");
            return;
          }
          toast.success(successMessage(order, trade, accountCurrency));
          onOpenChange(false);
        },
      },
    );
  }

  const closes = p ? p.legs.map((l) => `#${l.trade_id} (${formatQuantity(l.quantity)})`).join(", ") : "";
  const payoutLabel = p && toNumber(p.cash_change) < 0 ? "Cash you pay" : "Cash you receive";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] min-w-0 overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {covering ? "Cover" : "Exit"} {trade.symbol}
          </DialogTitle>
          <DialogDescription>
            Trade #{trade.id}: {trade.direction} {formatQuantity(trade.open_quantity)} {unit} open, entered at{" "}
            {formatPrice(trade.entry_price, trade.currency)}.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-1.5">
          <Label htmlFor="exit-qty">Quantity to {covering ? "cover" : "sell"}</Label>
          <Input
            id="exit-qty"
            inputMode="decimal"
            autoComplete="off"
            value={quantity}
            onChange={(e) => DECIMAL.test(e.target.value) && setQuantity(e.target.value)}
          />
          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto w-fit p-0"
            onClick={() => setQuantity(formatQuantity(trade.open_quantity))}
          >
            Use the whole open part ({formatQuantity(trade.open_quantity)})
          </Button>
        </div>

        {trade.lot_exits === "fifo" ? (
          <Alert>
            <AlertDescription>
              Indian demat accounts pool your shares, so exits always take your oldest shares first.{" "}
              {p ? `This exit closes: ${closes}.` : "The trades it closes appear once the figures load."}
            </AlertDescription>
          </Alert>
        ) : (
          <p className="text-xs text-muted-foreground">
            This exit closes exactly this trade (#{trade.id}), not any other lot you hold.
          </p>
        )}

        <dl className="grid gap-1.5 text-sm">
          {!valid ? (
            <p className="text-muted-foreground">Enter a quantity to see the payout.</p>
          ) : previewError ? (
            <Alert variant="destructive">
              <AlertDescription className="text-destructive">{previewError.message}</AlertDescription>
            </Alert>
          ) : p ? (
            <div className={cn("grid gap-1.5 transition-opacity", preview.isPlaceholderData && "opacity-60")}>
              <Row label="Exit value">
                {formatMoney(p.value_account, accountCurrency)}
                {p.currency !== accountCurrency && (
                  <span className="block text-xs text-muted-foreground">{formatMoney(p.value, p.currency)}</span>
                )}
              </Row>
              {p.charges.map((c) => (
                <Row key={`${c.category}:${c.name}`} label={c.name}>
                  {formatMoney(c.amount, accountCurrency)}
                </Row>
              ))}
              <Row label="Charges total">{formatMoney(p.charges_total, accountCurrency)}</Row>
              {!isZero(trade.financing_paid) && (
                <Row label={covering ? "Borrow or funding paid so far" : "Financing paid so far"}>
                  {formatMoney(trade.financing_paid, accountCurrency)}
                </Row>
              )}
              {!isZero(p.margin_change) && (
                <Row label={<Term id="margin">{toNumber(p.margin_change) > 0 ? "Margin blocked" : "Margin released"}</Term>}>
                  {formatMoney(Math.abs(toNumber(p.margin_change)), accountCurrency)}
                </Row>
              )}
              {p.realized_pnl !== null && p.realized_pnl !== undefined && (
                <Row label={<Term id="realized_pnl">Realized P&L</Term>}>
                  <Pnl value={p.realized_pnl} currency={accountCurrency} />
                </Row>
              )}
              <Row label={payoutLabel} strong>
                {formatMoney(Math.abs(toNumber(p.cash_change)), accountCurrency)}
              </Row>
            </div>
          ) : (
            <Skeleton className="h-32 w-full" />
          )}
        </dl>

        {error && (
          <Alert variant="destructive">
            <AlertDescription className="text-destructive">{error}</AlertDescription>
          </Alert>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" disabled={!valid || !!previewError || exit.isPending} onClick={confirm}>
            {exit.isPending ? "Exiting..." : `Confirm ${covering ? "cover" : "exit"}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
