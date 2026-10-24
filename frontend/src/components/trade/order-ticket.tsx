"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { ExitDialog } from "@/components/exit-dialog";
import { LegBreakdown, productLabel, unitFor } from "@/components/order-legs";
import { Pnl } from "@/components/pnl";
import { DirectionBadge } from "@/components/trades-table";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { ApiError } from "@/lib/api";
import { useOrderPreview, usePlaceOrder, usePortfolio } from "@/lib/queries";
import { formatMoney, formatPrice, formatQuantity, isZero, toNumber } from "@/lib/format";
import type { Order, OrderIn, OrderPreview, Quote, Trade } from "@/lib/types";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

type Mode = "buy" | "sell" | "exit";
type Kind = "market" | "limit";
type ShortRule = NonNullable<NonNullable<Quote["market"]>["short_selling"]>;

// Digits with at most one decimal point; anything else is rejected as the user types.
const DECIMAL = /^\d*\.?\d*$/;
const WHOLE = /^\d*$/;

function successMessage(order: Order): string {
  const qty = formatQuantity(order.quantity);
  if (order.status === "filled") {
    return `${order.side === "buy" ? "Bought" : "Sold"} ${qty} ${order.symbol} at ${formatPrice(order.fill_price, order.currency)}`;
  }
  if (order.type === "market") return "Order placed — waiting for the market to open";
  return `Limit order placed — waiting for ${formatPrice(order.limit_price, order.currency)}`;
}

// How a short works on this market, in the words a beginner needs before they place one.
function shortNote(rule: ShortRule): string {
  const margin = `${toNumber(rule.margin_percent)}% of its value is blocked as margin`;
  const borrow = toNumber(rule.borrow_percent_year);
  switch (rule.style) {
    case "intraday":
      return `This opens an intraday short: ${margin}, and it will be bought back for you ${rule.square_off_minutes_before_close ?? 10} minutes before the close.`;
    case "overnight":
      return `This opens a short you can hold overnight: ${margin}, and you pay about ${borrow}% a year to borrow the shares, charged daily.`;
    case "margin":
      return `This opens a margin short: ${margin}, and you pay funding every 8 hours (about ${borrow}% a year).`;
  }
}

// Every figure here is the server's; the browser never works out a charge itself.
function PreviewLines({
  preview,
  accountCurrency,
  unit,
}: {
  preview: OrderPreview;
  accountCurrency: string;
  unit: string;
}) {
  const foreign = preview.currency !== accountCurrency;
  const margin = toNumber(preview.margin_change);
  const cash = toNumber(preview.cash_change);
  return (
    <div className="grid gap-2">
      {preview.legs.map((leg, i) => (
        <LegBreakdown key={`${leg.kind}:${leg.trade_id ?? "new"}:${i}`} leg={leg} unit={unit} currency={accountCurrency} />
      ))}
      <div className="grid gap-1.5">
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Trade value</dt>
          <dd className="text-right tabular-nums">
            {formatMoney(preview.value_account, accountCurrency)}
            {foreign && (
              <span className="block text-xs text-muted-foreground">{formatMoney(preview.value, preview.currency)}</span>
            )}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Charges total</dt>
          <dd className="tabular-nums">{formatMoney(preview.charges_total, accountCurrency)}</dd>
        </div>
        {!isZero(preview.margin_change) && (
          <div className="flex justify-between gap-2">
            <dt className="text-muted-foreground">{margin > 0 ? "Margin blocked" : "Margin released"}</dt>
            <dd className="tabular-nums">{formatMoney(Math.abs(margin), accountCurrency)}</dd>
          </div>
        )}
        <div className="flex justify-between gap-2 border-t pt-1.5 font-medium">
          <dt>{cash < 0 ? "Cash you pay" : "Cash you receive"}</dt>
          <dd className="tabular-nums">{formatMoney(Math.abs(cash), accountCurrency)}</dd>
        </div>
        <p className="text-xs text-muted-foreground">
          via {preview.broker.name} · {preview.market.name} ·{" "}
          <Link href="/settings" className="underline underline-offset-2 hover:text-foreground">
            change broker
          </Link>
        </p>
      </div>
    </div>
  );
}

// The open trades of this symbol, to pick one to exit.
function ExitList({ trades, accountCurrency }: { trades: Trade[]; accountCurrency: string }) {
  const [exiting, setExiting] = useState<Trade | null>(null);
  if (trades.length === 0) {
    return <p className="text-sm text-muted-foreground">You have no open trades in this symbol to exit.</p>;
  }
  return (
    <div className="grid gap-2">
      <p className="text-sm text-muted-foreground">Pick a trade to exit. You will see the payout before you confirm.</p>
      {trades.map((t) => (
        <div key={t.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-2.5 text-sm">
          <div className="grid min-w-0 gap-0.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <DirectionBadge direction={t.direction} />
              <span className="text-muted-foreground">{productLabel(t.product)}</span>
            </div>
            <span className="tabular-nums">
              {formatQuantity(t.open_quantity)} at {formatPrice(t.entry_price, t.currency)}
            </span>
            {t.unrealized_pnl !== null && (
              <Pnl value={t.unrealized_pnl} currency={accountCurrency} percent={t.unrealized_pct} className="text-xs" />
            )}
          </div>
          <Button type="button" variant="outline" size="sm" onClick={() => setExiting(t)}>
            Exit
          </Button>
        </div>
      ))}
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

// Keyed by symbol in the parent so the inputs reset when the symbol changes.
export function OrderTicket({ quote }: { quote: Quote }) {
  const portfolio = usePortfolio();
  const place = usePlaceOrder();

  const [mode, setMode] = useState<Mode>("buy");
  const [kind, setKind] = useState<Kind>("market");
  const [quantity, setQuantity] = useState("");
  const [limitInput, setLimitInput] = useState<string | null>(null);
  const [rejection, setRejection] = useState<string | null>(null);

  const exitMode = mode === "exit";
  const side = mode === "sell" ? "sell" : "buy";
  const limit = limitInput ?? formatQuantity(quote.price);
  // Whole-share markets take no decimal point at all; the server states the rule if a fraction slips through.
  const step = quote.market?.quantity_step ?? "0.00000001";
  const wholeOnly = step === "1";
  const marketClosed = quote.market?.state === "closed";
  const qtyNumber = DECIMAL.test(quantity) ? toNumber(quantity) : 0;
  const limitNumber = DECIMAL.test(limit) ? toNumber(limit) : 0;
  const quantityValid = qtyNumber > 0;
  const limitValid = kind === "market" || limitNumber > 0;
  const unit = unitFor(quote.market?.code);

  const previewBody = useMemo<OrderIn | null>(
    () =>
      !exitMode && quantityValid && limitValid
        ? {
            symbol: quote.symbol,
            side,
            type: kind,
            quantity: quantity.replace(/\.$/, ""),
            limit_price: kind === "limit" ? limit.replace(/\.$/, "") : null,
          }
        : null,
    [exitMode, quantityValid, limitValid, quote.symbol, side, kind, quantity, limit],
  );
  const debouncedBody = useDebounced(previewBody, 300);
  // A body that went invalid must not keep quoting the old one.
  const preview = useOrderPreview(previewBody ? debouncedBody : null);
  const previewError = previewBody && preview.error instanceof ApiError ? preview.error : null;
  const previewRefused = !!previewError && previewError.status >= 400 && previewError.status < 500;
  const accountCurrency = portfolio.data?.currency ?? quote.currency;

  const heldLong = portfolio.data?.holdings.find((p) => p.symbol === quote.symbol && p.direction === "long");
  const heldShort = portfolio.data?.holdings.find((p) => p.symbol === quote.symbol && p.direction === "short");
  const openTrades = (portfolio.data?.trades ?? []).filter((t) => t.symbol === quote.symbol);
  const error = rejection ?? (place.error ? place.error.message : null);

  // The legs are the server's reading of the order, so "does this open a short" is asked of them.
  const opensShort = !!previewBody && !!preview.data?.legs.some((l) => l.kind === "open_short");
  const shortRule = quote.market?.short_selling ?? null;

  function submit(e: React.SyntheticEvent) {
    e.preventDefault();
    if (exitMode || !quantityValid || !limitValid || !quote.tradable) return;
    setRejection(null);
    place.mutate(
      {
        symbol: quote.symbol,
        side,
        type: kind,
        quantity: quantity.replace(/\.$/, ""),
        limit_price: kind === "limit" ? limit.replace(/\.$/, "") : null,
      },
      {
        onSuccess: (order) => {
          if (order.status === "rejected") {
            setRejection(order.reject_reason ?? "The order was rejected.");
            return;
          }
          toast.success(successMessage(order));
          setQuantity("");
        },
      },
    );
  }

  const disabled = !quote.tradable || !quantityValid || !limitValid || place.isPending || previewRefused;
  const onlyShorts = opensShort && !!preview.data?.legs.every((l) => l.kind === "open_short");
  const buttonLabel = mode === "buy" ? "Buy" : onlyShorts ? "Short" : "Sell";

  return (
    <Card>
      <CardHeader>
        <CardTitle>Order ticket</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        <form onSubmit={submit} className="grid gap-4">
          <ToggleGroup
            variant="outline"
            spacing={0}
            className="w-full"
            aria-label="Action"
            value={[mode]}
            onValueChange={(v) => {
              if (!v[0]) return;
              setMode(v[0] as Mode);
              setRejection(null);
              place.reset();
            }}
          >
            <ToggleGroupItem
              value="buy"
              className="flex-1 aria-pressed:bg-green-600 aria-pressed:text-white dark:aria-pressed:bg-green-700"
            >
              Buy
            </ToggleGroupItem>
            <ToggleGroupItem
              value="sell"
              className="flex-1 aria-pressed:bg-red-600 aria-pressed:text-white dark:aria-pressed:bg-red-700"
            >
              Sell
            </ToggleGroupItem>
            <ToggleGroupItem value="exit" className="flex-1">
              Exit
            </ToggleGroupItem>
          </ToggleGroup>

          {exitMode ? (
            <ExitList trades={openTrades} accountCurrency={accountCurrency} />
          ) : (
            <>
              <ToggleGroup
                variant="outline"
                size="sm"
                spacing={0}
                className="w-full"
                aria-label="Order type"
                value={[kind]}
                onValueChange={(v) => v[0] && setKind(v[0] as Kind)}
              >
                <ToggleGroupItem value="market" className="flex-1">
                  Market
                </ToggleGroupItem>
                <ToggleGroupItem value="limit" className="flex-1">
                  Limit
                </ToggleGroupItem>
              </ToggleGroup>

              <div className="grid gap-1.5">
                <Label htmlFor="order-qty">Quantity</Label>
                <Input
                  id="order-qty"
                  inputMode={wholeOnly ? "numeric" : "decimal"}
                  step={step}
                  autoComplete="off"
                  placeholder="0"
                  value={quantity}
                  onChange={(e) => (wholeOnly ? WHOLE : DECIMAL).test(e.target.value) && setQuantity(e.target.value)}
                />
                {!wholeOnly && <p className="text-xs text-muted-foreground">Smallest step: {step}</p>}
              </div>

              {marketClosed && (
                <Alert>
                  <AlertDescription>
                    The market is closed. Your order will wait and fill at the next open (like an after-market order).
                  </AlertDescription>
                </Alert>
              )}

              {kind === "limit" && (
                <div className="grid gap-1.5">
                  <Label htmlFor="order-limit">Limit price ({quote.currency})</Label>
                  <Input
                    id="order-limit"
                    inputMode="decimal"
                    autoComplete="off"
                    value={limit}
                    onChange={(e) => DECIMAL.test(e.target.value) && setLimitInput(e.target.value)}
                  />
                </div>
              )}

              {mode === "sell" && opensShort && shortRule && (
                <Alert>
                  <AlertDescription>{shortNote(shortRule)}</AlertDescription>
                </Alert>
              )}

              <dl className="grid gap-1.5 text-sm">
                {!previewBody ? (
                  <div className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">Trade value</dt>
                    <dd className="tabular-nums">—</dd>
                  </div>
                ) : previewError && previewRefused ? (
                  <Alert variant="destructive">
                    <AlertDescription className="text-destructive">
                      {previewError.message}
                      {previewError.code === "broker_unavailable" && (
                        <>
                          {" "}
                          <Link href="/settings" className="underline underline-offset-2">
                            Broker settings
                          </Link>
                        </>
                      )}
                    </AlertDescription>
                  </Alert>
                ) : preview.data ? (
                  <div className={cn("transition-opacity", preview.isPlaceholderData && "opacity-60")}>
                    <PreviewLines preview={preview.data} accountCurrency={accountCurrency} unit={unit} />
                  </div>
                ) : preview.error ? (
                  <p className="text-muted-foreground">{preview.error.message}</p>
                ) : (
                  <Skeleton className="h-28 w-full" />
                )}
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">You hold</dt>
                  <dd className="text-right tabular-nums">
                    {portfolio.data ? `${formatQuantity(heldLong?.quantity ?? "0")} ${quote.symbol}` : "—"}
                    {heldShort && (
                      <span className="block text-xs text-orange-700 dark:text-orange-300">
                        short {formatQuantity(heldShort.quantity)}
                      </span>
                    )}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">Available cash</dt>
                  <dd className="tabular-nums">
                    {portfolio.data ? formatMoney(portfolio.data.available_cash, portfolio.data.currency) : "—"}
                  </dd>
                </div>
              </dl>

              <Button
                type="submit"
                disabled={disabled}
                className={cn(
                  side === "buy"
                    ? "bg-green-600 text-white hover:bg-green-600/90 dark:bg-green-700"
                    : "bg-red-600 text-white hover:bg-red-600/90 dark:bg-red-700",
                )}
              >
                {place.isPending ? "Placing..." : `${buttonLabel} ${quote.symbol}${kind === "limit" ? " (limit)" : ""}`}
              </Button>
            </>
          )}

          {!quote.tradable && (
            <p className="text-sm text-muted-foreground">This instrument can&apos;t be traded.</p>
          )}
          {error && !exitMode && (
            <Alert variant="destructive">
              <AlertDescription className="text-destructive">{error}</AlertDescription>
            </Alert>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
