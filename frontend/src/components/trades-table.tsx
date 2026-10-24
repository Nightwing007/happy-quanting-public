"use client";

import { useState } from "react";
import Link from "next/link";
import { ExitDialog } from "@/components/exit-dialog";
import { productLabel } from "@/components/order-legs";
import { Pnl } from "@/components/pnl";
import { ProtectionDialog } from "@/components/protection-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatMoney, formatPrice, formatQuantity, formatZonedTime, isZero } from "@/lib/format";
import { usePortfolio } from "@/lib/queries";
import type { Trade } from "@/lib/types";
import { cn } from "@/lib/utils";

export function DirectionBadge({ direction, className }: { direction: "long" | "short"; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        direction === "short"
          ? "border-orange-500/60 bg-orange-500/15 text-orange-700 dark:text-orange-300"
          : "border-green-600/40 bg-green-600/10 text-green-700 dark:text-green-300",
        className,
      )}
    >
      {direction === "short" ? "Short" : "Long"}
    </Badge>
  );
}

/** How a closed trade ended, when it was by a stop-loss or a target. Nothing for the other ways. */
export function ClosedHowBadge({ closedHow }: { closedHow: string | null | undefined }) {
  if (closedHow !== "stop_loss" && closedHow !== "target") return null;
  return (
    <Badge
      variant="outline"
      className={
        closedHow === "stop_loss"
          ? "border-red-500/60 bg-red-500/10 text-red-700 dark:text-red-300"
          : "border-green-600/40 bg-green-600/10 text-green-700 dark:text-green-300"
      }
    >
      {closedHow === "stop_loss" ? "Stop-loss" : "Target"}
    </Badge>
  );
}

/** Open trades with an Exit button each. Used on the dashboard and the trade page. */
export function TradesTable({ trades, showSymbol = true }: { trades: Trade[]; showSymbol?: boolean }) {
  const accountCurrency = usePortfolio().data?.currency ?? "USD";
  const [exiting, setExiting] = useState<Trade | null>(null);
  const [protecting, setProtecting] = useState<Trade | null>(null);

  return (
    <div className="min-w-0 overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Opened</TableHead>
            {showSymbol && <TableHead>Symbol</TableHead>}
            <TableHead>Direction</TableHead>
            <TableHead>Product</TableHead>
            <TableHead className="text-right">Open / qty</TableHead>
            <TableHead className="text-right">Entry price</TableHead>
            <TableHead className="text-right">Current price</TableHead>
            <TableHead className="text-right">Unrealized P&amp;L</TableHead>
            <TableHead className="text-right">Entry charges</TableHead>
            <TableHead className="text-right">Margin blocked</TableHead>
            <TableHead className="text-right">Financing paid</TableHead>
            <TableHead className="text-right">Stop-loss</TableHead>
            <TableHead className="text-right">Target</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((t) => (
            <TableRow key={t.id}>
              <TableCell className="whitespace-nowrap">
                {formatZonedTime(t.opened_at, t.timezone)}
              </TableCell>
              {showSymbol && (
                <TableCell className="whitespace-nowrap font-medium">
                  <Link href={`/trade?symbol=${encodeURIComponent(t.symbol)}`} className="hover:underline">
                    {t.symbol}
                  </Link>
                </TableCell>
              )}
              <TableCell>
                <DirectionBadge direction={t.direction} />
              </TableCell>
              <TableCell>{productLabel(t.product)}</TableCell>
              <TableCell className="whitespace-nowrap text-right tabular-nums">
                {formatQuantity(t.open_quantity)} / {formatQuantity(t.quantity)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(t.entry_price, t.currency)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {t.price_unavailable || t.last_price === null ? (
                  <Badge variant="secondary" title="No live price right now">
                    Unavailable
                  </Badge>
                ) : (
                  formatPrice(t.last_price, t.currency)
                )}
              </TableCell>
              <TableCell className="text-right">
                {t.unrealized_pnl === null ? (
                  "—"
                ) : (
                  <Pnl value={t.unrealized_pnl} currency={accountCurrency} percent={t.unrealized_pct} />
                )}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatMoney(t.entry_charges_paid, accountCurrency)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {isZero(t.margin_blocked) ? "—" : formatMoney(t.margin_blocked, accountCurrency)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {isZero(t.financing_paid) ? "—" : formatMoney(t.financing_paid, accountCurrency)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {t.stop_price ? formatPrice(t.stop_price, t.currency) : "—"}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {t.target_price ? formatPrice(t.target_price, t.currency) : "—"}
              </TableCell>
              <TableCell className="text-right">
                {t.status === "open" ? (
                  <div className="flex justify-end gap-1.5">
                    <Button variant="outline" size="sm" onClick={() => setProtecting(t)}>
                      Stop / target
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setExiting(t)}>
                      Exit
                    </Button>
                  </div>
                ) : (
                  <ClosedHowBadge closedHow={t.closed_how} />
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {protecting && (
        <ProtectionDialog
          key={protecting.id}
          trade={protecting}
          open
          onOpenChange={(o) => {
            if (!o) setProtecting(null);
          }}
        />
      )}
      {exiting && (
        <ExitDialog
          key={exiting.id}
          trade={exiting}
          open
          onOpenChange={(o) => {
            if (!o) setExiting(null);
          }}
        />
      )}
    </div>
  );
}
