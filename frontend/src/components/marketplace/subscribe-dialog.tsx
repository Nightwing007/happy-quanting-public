"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { PlusIcon, XIcon } from "lucide-react";
import { toast } from "sonner";
import { SymbolSearch } from "@/components/symbol-search";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatMoney, toNumber } from "@/lib/format";
import { allowedBy, feeTerms, marketWord } from "@/lib/marketplace-format";
import { usePortfolio, useSubscribe } from "@/lib/queries";
import type { Listing } from "@/lib/types";

const MAX_SYMBOLS = 10;
const DECIMAL = /^\d*\.?\d*$/;

export function SubscribeDialog({ listing }: { listing: Listing }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [capital, setCapital] = useState("");
  const portfolio = usePortfolio().data;
  const subscribe = useSubscribe(listing.id);

  const capitalValid = DECIMAL.test(capital) && toNumber(capital) > 0;
  const canConfirm = symbols.length > 0 && capitalValid && !subscribe.isPending;

  function addSymbol(symbol: string) {
    const clean = symbol.trim().toUpperCase();
    setSymbols((cur) => (cur.includes(clean) || cur.length >= MAX_SYMBOLS ? cur : [...cur, clean]));
  }

  function confirm() {
    if (!canConfirm) return;
    subscribe.mutate(
      { symbols, capital: capital.replace(/\.$/, "") },
      {
        onSuccess: () => {
          toast.success(`Subscribed to ${listing.name}.`);
          setOpen(false);
          router.push("/marketplace/subscriptions");
        },
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) subscribe.reset();
      }}
    >
      <DialogTrigger render={<Button className="w-full" />}>Subscribe</DialogTrigger>
      <DialogContent className="max-h-[90vh] min-w-0 overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Subscribe to {listing.name}</DialogTitle>
          <DialogDescription>
            Choose where it trades and how much it may use. It runs on its own account, funded from your cash.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-1.5">
          <Label>Symbols (up to {MAX_SYMBOLS})</Label>
          <div className="flex flex-wrap items-center gap-2">
            {symbols.map((s) => (
              <Badge key={s} variant="secondary" className="gap-1">
                {s}
                <button
                  type="button"
                  aria-label={`Remove ${s}`}
                  onClick={() => setSymbols((cur) => cur.filter((x) => x !== s))}
                  className="rounded-full p-0.5 hover:bg-foreground/10"
                >
                  <XIcon className="size-3" />
                </button>
              </Badge>
            ))}
            {symbols.length < MAX_SYMBOLS && (
              <SymbolSearch
                onSelect={addSymbol}
                filter={(i) => allowedBy(listing.markets, i)}
                label={
                  <>
                    <PlusIcon />
                    <span>{symbols.length ? "Add another" : "Add a symbol"}</span>
                  </>
                }
              />
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Only {listing.markets.map(marketWord).join(", ")} symbols can be picked.
          </p>
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="subscribe-capital">Capital to give it{portfolio ? ` (${portfolio.currency})` : ""}</Label>
          <Input
            id="subscribe-capital"
            inputMode="decimal"
            value={capital}
            onChange={(e) => setCapital(e.target.value)}
            aria-invalid={capital !== "" && !capitalValid}
          />
          <p className="text-xs text-muted-foreground">
            {portfolio
              ? `You have ${formatMoney(portfolio.available_cash, portfolio.currency)} available.`
              : "Loading your available cash..."}{" "}
            It leaves your account while the subscription runs and comes back, less any losses and fees, when you stop.
          </p>
        </div>

        <p className="text-sm text-muted-foreground">{feeTerms(listing.fee_percent)}</p>

        {subscribe.error && (
          <Alert variant="destructive">
            <AlertDescription>{subscribe.error.message}</AlertDescription>
          </Alert>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button disabled={!canConfirm} onClick={confirm}>
            {subscribe.isPending ? "Subscribing…" : "Confirm"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
