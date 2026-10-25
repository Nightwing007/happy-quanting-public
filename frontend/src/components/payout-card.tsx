import Link from "next/link";
import { DirectionBadge } from "@/components/trades-table";
import { productLabel } from "@/components/order-legs";
import { Pnl } from "@/components/pnl";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatMoney, formatPrice, formatQuantity, formatZonedTime, isZero } from "@/lib/format";
import type { Charge, Payout } from "@/lib/types";

const HOW: Record<string, { label: string; className: string }> = {
  exit: { label: "Exited", className: "" },
  sell: { label: "Exited", className: "" },
  cover: { label: "Exited", className: "" },
  stop_loss: { label: "Stop-loss fired", className: "border-down/60 bg-down/10 text-down" },
  target: {
    label: "Target reached",
    className: "border-up/40 bg-up/10 text-up",
  },
  square_off: {
    label: "Squared off by broker",
    className: "border-warn/60 bg-warn/15 text-warn",
  },
};

/** How a trade ended: you exited it, a stop-loss or target fired, or the broker squared it off. */
export function HowClosedBadge({ closedHow }: { closedHow: string }) {
  const how = HOW[closedHow] ?? HOW.exit;
  return (
    <Badge variant="outline" className={how.className}>
      {how.label}
    </Badge>
  );
}

function Row({ label, children, strong }: { label: React.ReactNode; children: React.ReactNode; strong?: boolean }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 ${strong ? "font-medium" : ""}`}>
      <dt className="min-w-0 text-muted-foreground">{label}</dt>
      <dd className="shrink-0 text-right tabular-nums">{children}</dd>
    </div>
  );
}

function ChargeLines({
  title,
  lines,
  total,
  currency,
}: {
  title: string;
  lines: Charge[];
  total: string;
  currency: string;
}) {
  return (
    <section className="grid min-w-0 content-start gap-1 rounded-md border p-2.5" aria-label={title}>
      <h3 className="font-medium">{title}</h3>
      {lines.length === 0 && <p className="text-xs text-muted-foreground">No charge lines were recorded for this end.</p>}
      <dl className="grid gap-1">
        {lines.map((c) => (
          <Row
            key={`${c.category}:${c.name}`}
            label={
              <Tooltip>
                <TooltipTrigger
                  render={<span tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-4" />}
                >
                  {c.name}
                </TooltipTrigger>
                <TooltipContent>{c.description}</TooltipContent>
              </Tooltip>
            }
          >
            {formatMoney(c.amount, currency)}
          </Row>
        ))}
        <div className="border-t pt-1">
          <Row label="Total" strong>
            {formatMoney(total, currency)}
          </Row>
        </div>
      </dl>
    </section>
  );
}

/** One closed trade, start to finish. Every figure is the server's. */
export function PayoutCard({ payout: p, currency }: { payout: Payout; currency: string }) {
  const short = p.direction === "short";
  return (
    <Card>
      <CardContent className="grid min-w-0 gap-3">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Link href={`/trade?symbol=${encodeURIComponent(p.symbol)}`} className="font-semibold hover:underline">
            {p.symbol}
          </Link>
          <DirectionBadge direction={p.direction} />
          <HowClosedBadge closedHow={p.closed_how} />
          <span className="text-xs text-muted-foreground">Trade #{p.trade_id}</span>
        </div>
        <p className="text-xs text-muted-foreground">
          {formatQuantity(p.quantity)} {short ? "sold short" : "bought"} at {formatPrice(p.entry_price, p.currency)} (
          {productLabel(p.product).toLowerCase()}) · {formatZonedTime(p.opened_at, p.timezone)} →{" "}
          {formatZonedTime(p.closed_at, p.timezone)}
        </p>

        <dl className="grid gap-1">
          <Row label={short ? "Sold short for" : "Paid for the shares"}>{formatMoney(p.entry_value, currency)}</Row>
          <Row label={short ? "Buying it back cost" : "Exit brought in"} strong>
            {formatMoney(p.exit_value, currency)}
          </Row>
          {short && (
            <Row label="Left after buying back">
              <Pnl value={p.brought_in} currency={currency} />
            </Row>
          )}
        </dl>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <ChargeLines title="Charges getting in" lines={p.entry_charge_lines} total={p.entry_charges_total} currency={currency} />
          <ChargeLines title="Charges getting out" lines={p.exit_charge_lines} total={p.exit_charges_total} currency={currency} />
        </div>

        <dl className="grid gap-1 border-t pt-2">
          <Row label="Borrowing / funding">{isZero(p.financing_paid) ? "None" : formatMoney(p.financing_paid, currency)}</Row>
          <Row label="Profit left over" strong>
            <Pnl value={p.realized_pnl} currency={currency} />
          </Row>
        </dl>
      </CardContent>
    </Card>
  );
}
