"use client";

import Link from "next/link";
import { DirectionBadge } from "@/components/trades-table";
import { QueryError } from "@/components/query-error";
import { Pnl } from "@/components/pnl";
import { Term } from "@/components/term";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatMoney, formatPrice, formatQuantity } from "@/lib/format";
import { usePortfolio } from "@/lib/queries";

export function PositionsCard() {
  const { data: p, isPending, error, refetch } = usePortfolio();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Holdings</CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        {error && !p && <QueryError error={error} title="Couldn't load your holdings" onRetry={() => refetch()} />}
        {isPending && <Skeleton className="h-32 w-full" />}
        {p && p.holdings.length === 0 && (
          <p className="text-sm text-muted-foreground">
            You don&apos;t hold anything yet. Search for a symbol with Ctrl+K and place a paper order.
          </p>
        )}
        {p && p.holdings.length > 0 && (
          <div className="min-w-0 overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right"><Term id="avg_entry">Avg price</Term></TableHead>
                  <TableHead className="text-right">Last price</TableHead>
                  <TableHead className="text-right" title="For a short: what buying the shares back would cost now">Market value</TableHead>
                  <TableHead className="text-right"><Term id="unrealized_pnl">Unrealized P&amp;L</Term></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {p.holdings.map((pos) => (
                  <TableRow key={`${pos.symbol}-${pos.direction}`}>
                    <TableCell className="whitespace-nowrap font-medium">
                      <Link href={`/trade?symbol=${encodeURIComponent(pos.symbol)}`} className="hover:underline">
                        {pos.symbol}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <DirectionBadge direction={pos.direction} />
                    </TableCell>
                    <TableCell className="max-w-48 truncate text-muted-foreground">{pos.name}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatQuantity(pos.quantity)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatPrice(pos.avg_price, pos.currency)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {pos.price_unavailable ? (
                        <Badge variant="secondary" title="No live price right now; showing the last known value">
                          Price unavailable
                        </Badge>
                      ) : (
                        formatPrice(pos.last_price, pos.currency)
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatMoney(pos.market_value, p.currency)}</TableCell>
                    <TableCell className="text-right">
                      <Pnl value={pos.unrealized_pnl} currency={p.currency} percent={pos.unrealized_pct} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
