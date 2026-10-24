"use client";

import { PayoutCard } from "@/components/payout-card";
import { Pnl } from "@/components/pnl";
import { QueryError } from "@/components/query-error";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney } from "@/lib/format";
import { usePayouts } from "@/lib/queries";

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Card size="sm">
      <CardContent className="grid min-w-0 gap-0.5">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="truncate text-base font-semibold tabular-nums">{children}</p>
      </CardContent>
    </Card>
  );
}

/** Totals and one card per closed trade, for whichever account the surrounding <TradingScope> names. */
export function PayoutsPanel() {
  const { data, isPending, error, refetch } = usePayouts();

  return (
    <>
      {error && !data && <QueryError error={error} title="Couldn't load your payouts" onRetry={() => refetch()} />}
      {isPending && <Skeleton className="h-40 w-full" />}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            <Stat label="Trades closed">{data.totals.trades_closed}</Stat>
            <Stat label="Total brought in">{formatMoney(data.totals.brought_in, data.currency)}</Stat>
            <Stat label="Total charges">{formatMoney(data.totals.charges, data.currency)}</Stat>
            <Stat label="Borrowing / funding">{formatMoney(data.totals.financing, data.currency)}</Stat>
            <Stat label="Net profit">
              <Pnl value={data.totals.net_profit} currency={data.currency} />
            </Stat>
          </div>
          {data.payouts.length === 0 ? (
            <Card>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Nothing has been paid out yet. Close a trade and you will see here what it brought in, every charge
                  at both ends, and the profit left over.
                </p>
              </CardContent>
            </Card>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">
                Brought in is a long&apos;s sale proceeds; for a short it is what selling first took in, less what
                buying it back cost. Each profit is that, less the charges at both ends and any borrowing or funding.
              </p>
              {data.payouts.map((p) => (
                <PayoutCard key={p.trade_id} payout={p} currency={data.currency} />
              ))}
            </>
          )}
        </>
      )}
    </>
  );
}
