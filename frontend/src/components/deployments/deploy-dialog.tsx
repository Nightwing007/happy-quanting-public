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
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatMoney, toNumber } from "@/lib/format";
import { allowedBy, marketWord } from "@/lib/marketplace-format";
import { useCreateDeployment, usePortfolio } from "@/lib/queries";
import type { DeploymentIn } from "@/lib/types";

const MAX_SYMBOLS = 10;
const DECIMAL = /^\d*\.?\d*$/;

/** What to deploy: a library algorithm with settings, or a saved algorithm (its own settings, optionally overridden). */
export type DeployWhat =
  | { library_key: string; params: Record<string, unknown> }
  | { algo_id: number; params?: Record<string, unknown> };

export type DeployDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The strategy's name: prefills the deployment's name. */
  name: string;
  /** Where it may trade (market segments or codes), as the algorithm declares them. */
  markets: string[];
  what: DeployWhat;
  /** Where the algorithm comes from, in words: "SMA crossover, a ready-made algorithm". */
  source: string;
  /** The settings being deployed, shown as a short list. Empty for a saved algorithm's own settings. */
  settings?: [string, string][];
  initialSymbols?: string[];
};

function Form({ onOpenChange, name, markets, what, source, settings = [], initialSymbols = [] }: Omit<DeployDialogProps, "open">) {
  const router = useRouter();
  const portfolio = usePortfolio().data;
  const deploy = useCreateDeployment();
  const [title, setTitle] = useState(name);
  const [symbols, setSymbols] = useState<string[]>(initialSymbols.slice(0, MAX_SYMBOLS));
  const [capital, setCapital] = useState("");

  const capitalValid = DECIMAL.test(capital) && toNumber(capital) > 0;
  const canConfirm = symbols.length > 0 && capitalValid && !deploy.isPending;

  function addSymbol(symbol: string) {
    const clean = symbol.trim().toUpperCase();
    setSymbols((cur) => (cur.includes(clean) || cur.length >= MAX_SYMBOLS ? cur : [...cur, clean]));
  }

  function confirm(e: React.FormEvent) {
    e.preventDefault();
    if (!canConfirm) return;
    const body: DeploymentIn = {
      ...what,
      symbols,
      capital: capital.replace(/\.$/, ""),
      name: title.trim() || null,
    };
    deploy.mutate(body, {
      onSuccess: (d) => {
        toast.success(`Deployed "${d.name}".`);
        onOpenChange(false);
        router.push(`/deployments/${d.id}`);
      },
    });
  }

  return (
    <form onSubmit={confirm} className="grid min-w-0 gap-4">
      <DialogHeader>
        <DialogTitle>Deploy {name}</DialogTitle>
        <DialogDescription>
          Runs live on a separate paper account every new bar during market hours, with real charges. Your manual
          trades are unaffected.
        </DialogDescription>
      </DialogHeader>

      <div className="grid gap-1.5">
        <Label htmlFor="deploy-name">Name</Label>
        <Input id="deploy-name" value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} />
      </div>

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
              filter={(i) => allowedBy(markets, i)}
              label={
                <>
                  <PlusIcon />
                  <span>{symbols.length ? "Add another" : "Add a symbol"}</span>
                </>
              }
            />
          )}
        </div>
        <p className="text-xs text-muted-foreground">Only {markets.map(marketWord).join(", ")} symbols can be picked.</p>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="deploy-capital">Capital to give it{portfolio ? ` (${portfolio.currency})` : ""}</Label>
        <Input
          id="deploy-capital"
          inputMode="decimal"
          value={capital}
          onChange={(e) => setCapital(e.target.value)}
          aria-invalid={capital !== "" && !capitalValid}
        />
        <p className="text-xs text-muted-foreground">
          {portfolio
            ? `You have ${formatMoney(portfolio.available_cash, portfolio.currency)} available.`
            : "Loading your available cash..."}{" "}
          It leaves your account while the deployment runs and comes back, less any losses and charges, when you stop.
        </p>
      </div>

      <div className="grid gap-1 border border-line p-3 text-sm" aria-label="Settings being deployed">
        <p className="t-meta text-dim">Settings being deployed</p>
        <p>{source}</p>
        {settings.length > 0 ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
            {settings.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-xs text-muted-foreground">With the settings saved in it. They are copied now and won&apos;t change if you edit it later.</p>
        )}
      </div>

      {deploy.error && (
        <Alert variant="destructive">
          <AlertDescription>{deploy.error.message}</AlertDescription>
        </Alert>
      )}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button type="submit" disabled={!canConfirm}>
          {deploy.isPending ? "Deploying…" : "Deploy"}
        </Button>
      </DialogFooter>
    </form>
  );
}

/** Starts a deployment: name, symbols in the algorithm's markets, capital, and what is being deployed. */
export function DeployDialog({ open, onOpenChange, ...rest }: DeployDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] min-w-0 overflow-y-auto sm:max-w-md">
        {/* Mounted only while open, so every opening starts from a clean form. */}
        <Form onOpenChange={onOpenChange} {...rest} />
      </DialogContent>
    </Dialog>
  );
}

/** A Deploy button that owns its dialog, for places where nothing has to happen first. */
export function DeployButton({
  label = "Deploy",
  variant = "outline",
  size = "sm",
  disabled,
  title,
  ...props
}: Omit<DeployDialogProps, "open" | "onOpenChange"> & {
  label?: string;
  variant?: "default" | "outline" | "ghost";
  size?: "default" | "sm";
  disabled?: boolean;
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button type="button" variant={variant} size={size} disabled={disabled} title={title} onClick={() => setOpen(true)}>
        {label}
      </Button>
      <DeployDialog open={open} onOpenChange={setOpen} {...props} />
    </>
  );
}

/** "fast_period" -> "fast period", for the settings list. */
export const settingLabel = (key: string) => key.replace(/_/g, " ");
