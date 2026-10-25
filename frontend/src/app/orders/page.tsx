"use client";

import { useState } from "react";
import { toast } from "sonner";
import { OrdersTable } from "@/components/orders-table";
import { QueryError } from "@/components/query-error";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatMoney } from "@/lib/format";
import { useOrders, usePortfolio, useResetPortfolio } from "@/lib/queries";
import { PageHeader } from "@/components/motion/page-header";

const FILTERS = [
  { value: "all", label: "All" },
  { value: "open", label: "Waiting" },
  { value: "filled", label: "Filled" },
  { value: "cancelled", label: "Cancelled" },
  { value: "rejected", label: "Rejected" },
];

function ResetAccount() {
  const [open, setOpen] = useState(false);
  const { data: portfolio } = usePortfolio();
  const reset = useResetPortfolio();
  const cash = portfolio ? formatMoney(portfolio.starting_cash, portfolio.currency) : "your starting cash";

  function onReset() {
    reset.mutate(undefined, {
      onSuccess: () => {
        setOpen(false);
        toast.success("Account reset. You're back to your starting cash.");
      },
      onError: (e) => toast.error(e.message),
    });
  }

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger render={<Button variant="outline" />}>Reset account</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Reset your account?</AlertDialogTitle>
          <AlertDialogDescription>
            This deletes every order and position and restores your starting cash of {cash}. Your watchlist is kept.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep my account</AlertDialogCancel>
          <AlertDialogAction variant="destructive" disabled={reset.isPending} onClick={onReset}>
            {reset.isPending ? "Resetting…" : "Reset account"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export default function OrdersPage() {
  const [filter, setFilter] = useState("all");
  const { data: orders, isPending, error, refetch } = useOrders({
    status: filter === "all" ? undefined : filter,
    limit: 500,
  });

  return (
    <div className="grid grid-cols-1 gap-4">
      <PageHeader title="Orders" eyebrow="Account" actions={<ResetAccount />} />
      <Tabs value={filter} onValueChange={(v) => setFilter(String(v))} className="min-w-0">
        <div className="min-w-0 overflow-x-auto">
          <TabsList>
            {FILTERS.map((f) => (
              <TabsTrigger key={f.value} value={f.value}>
                {f.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      </Tabs>
      <Card>
        <CardContent className="min-w-0">
          {error && !orders && <QueryError error={error} title="Couldn't load your orders" onRetry={() => refetch()} />}
          {isPending && <Skeleton className="h-40 w-full" />}
          {orders && orders.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {filter === "all"
                ? "No orders yet. Search for a symbol with Ctrl+K to place your first one."
                : "No orders match this filter."}
            </p>
          )}
          {orders && orders.length > 0 && <OrdersTable orders={orders} />}
        </CardContent>
      </Card>
    </div>
  );
}
