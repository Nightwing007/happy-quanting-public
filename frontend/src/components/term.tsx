"use client";

import { Fragment, useSyncExternalStore, type ReactNode } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { GLOSSARY, type TermId } from "@/lib/glossary";
import { cn } from "@/lib/utils";

type Params = Record<string, string | number>;

type Props = {
  id: TermId;
  children: ReactNode;
  /** Fills `{name}` placeholders in the definition, e.g. { period: 20 } for "SMA 20". */
  params?: Params;
  /** False inside a button or link, which is already focusable on its own. */
  focusable?: boolean;
  className?: string;
};

// Phones have no hover, so a coarse pointer gets a tap-to-open popover instead of a tooltip.
const COARSE = "(pointer: coarse)";
function subscribeCoarse(cb: () => void) {
  const mq = window.matchMedia(COARSE);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}
const isCoarse = () => window.matchMedia(COARSE).matches;
const notCoarse = () => false;
export const useCoarsePointer = () => useSyncExternalStore(subscribeCoarse, isCoarse, notCoarse);

function fill(text: string, params?: Params): ReactNode {
  return text.split(/(\{\w+\})/).map((part, i) => {
    const m = /^\{(\w+)\}$/.exec(part);
    if (!m) return <Fragment key={i}>{part}</Fragment>;
    return <strong key={i}>{params?.[m[1]] ?? "N"}</strong>;
  });
}

function TermBody({ id, params }: { id: TermId; params?: Params }) {
  const t: { term: string; short: string; read: string; good?: string } = GLOSSARY[id];
  return (
    <div className="grid gap-1 text-left text-xs leading-snug">
      <p className="font-semibold">{t.term}</p>
      <p>{fill(t.short, params)}</p>
      <p className="opacity-80">{t.read}</p>
      {t.good && (
        <p>
          <span className="font-medium">Good? </span>
          {t.good}
        </p>
      )}
    </div>
  );
}

export function Term({ id, children, params, focusable = true, className }: Props) {
  const coarse = useCoarsePointer();
  const trigger = (
    <span
      tabIndex={focusable ? 0 : undefined}
      className={cn("cursor-help underline decoration-dotted decoration-1 underline-offset-4", className)}
    />
  );

  if (coarse) {
    return (
      <Popover>
        <PopoverTrigger render={trigger} nativeButton={false}>
          {children}
        </PopoverTrigger>
        <PopoverContent align="center" className="w-auto max-w-80 p-2.5">
          <TermBody id={id} params={params} />
        </PopoverContent>
      </Popover>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger render={trigger}>{children}</TooltipTrigger>
      <TooltipContent className="block max-w-80 py-2">
        <TermBody id={id} params={params} />
      </TooltipContent>
    </Tooltip>
  );
}
