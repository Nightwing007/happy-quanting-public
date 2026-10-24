"use client";

import Link from "next/link";
import { QueryError } from "@/components/query-error";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatMoney } from "@/lib/format";
import { useEarnings, useMe } from "@/lib/queries";

function Earnings() {
  const { data, isPending, error, refetch } = useEarnings();
  if (error && !data) return <QueryError error={error} title="Couldn't load your earnings" onRetry={() => refetch()} />;
  if (isPending || !data) return <Skeleton className="h-48 w-full" />;
  return (
    <Card>
      <CardContent className="min-w-0 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Listing</TableHead>
              <TableHead className="text-right">Subscribers</TableHead>
              <TableHead className="text-right">Fees received</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.listings.length === 0 && (
              <TableRow>
                <TableCell colSpan={3} className="text-center text-muted-foreground">
                  You have no listings yet.
                </TableCell>
              </TableRow>
            )}
            {data.listings.map((l) => (
              <TableRow key={l.listing_id}>
                <TableCell className="font-medium">
                  <Link href={`/marketplace/${l.listing_id}`} className="hover:underline">
                    {l.name}
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {l.subscribers} <span className="text-muted-foreground">({l.active_subscribers} active)</span>
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatMoney(l.fees_received, data.currency)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell colSpan={2} className="font-medium">
                Total
              </TableCell>
              <TableCell className="text-right font-semibold tabular-nums">{formatMoney(data.total, data.currency)}</TableCell>
            </TableRow>
          </TableFooter>
        </Table>
      </CardContent>
    </Card>
  );
}

export function EarningsView() {
  const me = useMe();
  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">My earnings</h1>
      {me.isPending && <Skeleton className="h-48 w-full" />}
      {me.data && !me.data.is_creator && (
        <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          Earnings are shown to creators. Once you publish a listing, the fees it earns appear here.
        </p>
      )}
      {me.data?.is_creator && <Earnings />}
    </div>
  );
}
