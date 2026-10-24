"use client";

import Link from "next/link";
import { toast } from "sonner";
import { OrderStatusBadge } from "@/components/order-status-badge";
import { Pnl } from "@/components/pnl";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatMoney, formatPrice, formatQuantity, isZero } from "@/lib/format";
import { useCancelOrder, usePortfolio } from "@/lib/queries";
import { describeOrder } from "@/lib/order-words";
import type { Order } from "@/lib/types";

// Charges and amounts are stored in the account currency, not the instrument's.
function ChargesCell({ order, currency }: { order: Order; currency: string }) {
  if (order.status !== "filled") return <>—</>;
  if (isZero(order.charges_total) && order.charges.length === 0) {
    return <span className="tabular-nums">{formatMoney(order.charges_total, currency)}</span>;
  }
  return (
    <Popover>
      <PopoverTrigger
        openOnHover
        delay={150}
        className="cursor-help tabular-nums underline decoration-dotted underline-offset-4"
        aria-label={`Charges breakdown for order ${order.id}`}
      >
        {formatMoney(order.charges_total, currency)}
      </PopoverTrigger>
      <PopoverContent>
        <p className="mb-2 font-medium">Charges on this order</p>
        <ul className="grid gap-1">
          {order.charges.map((c) => (
            <li key={`${c.category}:${c.name}`} className="flex justify-between gap-3">
              <span className="text-muted-foreground">{c.name}</span>
              <span className="tabular-nums">{formatMoney(c.amount, currency)}</span>
            </li>
          ))}
          <li className="flex justify-between gap-3 border-t pt-1 font-medium">
            <span>Total</span>
            <span className="tabular-nums">{formatMoney(order.charges_total, currency)}</span>
          </li>
        </ul>
      </PopoverContent>
    </Popover>
  );
}

function WhatItDid({ order }: { order: Order }) {
  return (
    <div className="min-w-0 max-w-64 whitespace-normal">
      <span>{describeOrder(order)}</span>
      {order.note && <span className="block text-xs text-muted-foreground">{order.note}</span>}
    </div>
  );
}

/** Shared by /orders and the per-symbol list on /trade. */
export function OrdersTable({ orders, showSymbol = true }: { orders: Order[]; showSymbol?: boolean }) {
  const cancel = useCancelOrder();
  const accountCurrency = usePortfolio().data?.currency ?? "USD";

  function onCancel(order: Order) {
    cancel.mutate(order.id, {
      onSuccess: () => toast.success(`Cancelled your ${order.side} order for ${order.symbol}`),
      onError: (e) => toast.error(e.message),
    });
  }

  return (
    <div className="min-w-0 overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            {showSymbol && <TableHead>Symbol</TableHead>}
            <TableHead>Side</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>What it did</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Limit</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Fill price</TableHead>
            <TableHead className="text-right">Amount</TableHead>
            <TableHead className="text-right">Charges</TableHead>
            <TableHead className="text-right">Realized P&amp;L</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {orders.map((o) => (
            <TableRow key={o.id}>
              <TableCell className="whitespace-nowrap">
                {new Date(o.created_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}
              </TableCell>
              {showSymbol && (
                <TableCell className="whitespace-nowrap font-medium">
                  <Link href={`/trade?symbol=${encodeURIComponent(o.symbol)}`} className="hover:underline">
                    {o.symbol}
                  </Link>
                </TableCell>
              )}
              <TableCell
                className={o.side === "buy" ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}
              >
                {o.side}
              </TableCell>
              <TableCell>{o.type}</TableCell>
              <TableCell>
                <WhatItDid order={o} />
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatQuantity(o.quantity)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {o.limit_price ? formatPrice(o.limit_price, o.currency) : "—"}
              </TableCell>
              <TableCell>
                <OrderStatusBadge order={o} />
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {o.fill_price ? formatPrice(o.fill_price, o.currency) : "—"}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {o.amount ? formatMoney(o.amount, accountCurrency) : "—"}
              </TableCell>
              <TableCell className="text-right">
                <ChargesCell order={o} currency={accountCurrency} />
              </TableCell>
              <TableCell className="text-right">
                {o.realized_pnl !== null && o.realized_pnl !== undefined ? (
                  <Pnl value={o.realized_pnl} currency={accountCurrency} />
                ) : (
                  "—"
                )}
              </TableCell>
              <TableCell className="text-right">
                {o.status === "open" && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={cancel.isPending && cancel.variables === o.id}
                    onClick={() => onCancel(o)}
                  >
                    {cancel.isPending && cancel.variables === o.id ? "Cancelling…" : "Cancel"}
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
