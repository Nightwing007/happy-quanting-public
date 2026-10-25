"use client";

import { NumberRoll } from "@/components/motion/number-roll";
import { QueryError } from "@/components/query-error";
import { Pnl, pnlClass } from "@/components/pnl";
import { Term } from "@/components/term";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatMoney, formatPercent, isZero, toNumber } from "@/lib/format";
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
    <div className="grid min-w-0 content-start gap-1.5 p-4">
      <div className="t-meta text-muted-foreground">
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
      </div>
      <div className="t-data truncate text-2xl font-medium">{children}</div>
      <div className="text-xs text-muted-foreground">{sub}</div>
    </div>
  );
}

export function SummaryCards() {
  const { data: p, isPending, error, refetch } = usePortfolio();

  if (error && !p) {
    return <QueryError error={error} title="Couldn't load your account" onRetry={() => refetch()} />;
  }

  if (isPending || !p) {
    return (
      <div className="ledger grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      </div>
    );
  }

  const c = p.currency;
  // Percent of the cash the account started with; guard the division.
  const pnlPercent = isZero(p.starting_cash) ? null : (toNumber(p.total_pnl) / toNumber(p.starting_cash)) * 100;

  const money = (v: string) => <NumberRoll value={toNumber(v)} format={(n) => formatMoney(n, c)} />;
  const pnl = toNumber(p.total_pnl);

  return (
    <div className="ledger grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
      <Stat title="Total value" sub={`Started with ${formatMoney(p.starting_cash, c)}`}>
        {money(p.total_value)}
      </Stat>
      <Stat
        title="Cash"
        sub="Includes any margin held for shorts"
        help="All the cash in your account, including the part blocked as margin for open shorts."
      >
        {money(p.cash)}
      </Stat>
      <Stat
        title="Margin used"
        sub="Held against your open shorts"
        term="margin"
      >
        {money(p.margin_used)}
      </Stat>
      <Stat
        title="Available cash"
        sub="Cash minus margin"
        term="available_cash"
      >
        {money(p.available_cash)}
      </Stat>
      <Stat title="Invested (cost)" sub={`Market value ${formatMoney(p.market_value, c)}`}>
        {money(p.invested)}
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
        <span className={pnlClass(p.total_pnl)}>
          <NumberRoll
            value={pnl}
            format={(n) => `${isZero(n) ? "" : n > 0 ? "+" : "-"}${formatMoney(Math.abs(n), c)}`}
          />
          {pnlPercent !== null && ` (${formatPercent(pnlPercent)})`}
        </span>
      </Stat>
    </div>
  );
}
