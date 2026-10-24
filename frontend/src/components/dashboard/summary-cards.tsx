"use client";

import { QueryError } from "@/components/query-error";
import { Pnl } from "@/components/pnl";
import { Term } from "@/components/term";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatMoney, isZero, toNumber } from "@/lib/format";
import type { TermId } from "@/lib/glossary";
import { usePortfolio } from "@/lib/queries";

function Stat({
  title,
  children,
  sub,
  help,
  term,
}: {
  title: string;
  children: React.ReactNode;
  sub: React.ReactNode;
  help?: string;
  /** A glossary term to explain the title instead of `help`. */
  term?: TermId;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {term ? (
            <Term id={term}>{title}</Term>
          ) : help ? (
            <Tooltip>
              <TooltipTrigger
                render={<span tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-4" />}
              >
                {title}
              </TooltipTrigger>
              <TooltipContent>{help}</TooltipContent>
            </Tooltip>
          ) : (
            title
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="min-w-0">
        <div className="truncate text-2xl font-semibold tabular-nums">{children}</div>
        <div className="mt-1 text-xs text-muted-foreground">{sub}</div>
      </CardContent>
    </Card>
  );
}

export function SummaryCards() {
  const { data: p, isPending, error, refetch } = usePortfolio();

  if (error && !p) {
    return <QueryError error={error} title="Couldn't load your account" onRetry={() => refetch()} />;
  }

  if (isPending || !p) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      </div>
    );
  }

  const c = p.currency;
  // Percent of the cash the account started with; guard the division.
  const pnlPercent = isZero(p.starting_cash) ? null : (toNumber(p.total_pnl) / toNumber(p.starting_cash)) * 100;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Stat title="Total value" sub={`Started with ${formatMoney(p.starting_cash, c)}`}>
        {formatMoney(p.total_value, c)}
      </Stat>
      <Stat
        title="Cash"
        sub="Includes any margin held for shorts"
        help="All the cash in your account, including the part blocked as margin for open shorts."
      >
        {formatMoney(p.cash, c)}
      </Stat>
      <Stat
        title="Margin used"
        sub="Held against your open shorts"
        term="margin"
      >
        {formatMoney(p.margin_used, c)}
      </Stat>
      <Stat
        title="Available cash"
        sub="Cash minus margin"
        term="available_cash"
      >
        {formatMoney(p.available_cash, c)}
      </Stat>
      <Stat title="Invested (cost)" sub={`Market value ${formatMoney(p.market_value, c)}`}>
        {formatMoney(p.invested, c)}
      </Stat>
      <Stat
        title="Profit / loss"
        sub={
          <>
            <Term id="realized_pnl">Realized</Term> <Pnl value={p.realized_pnl} currency={c} /> · <Term id="unrealized_pnl">Unrealized</Term>{" "}
            <Pnl value={p.unrealized_pnl} currency={c} />
          </>
        }
      >
        <Pnl value={p.total_pnl} currency={c} percent={pnlPercent} />
      </Stat>
    </div>
  );
}
