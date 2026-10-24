"use client";

import type { ReactNode } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCoarsePointer } from "@/components/term";
import { parseApiTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function earnedDate(iso: string): string {
  return parseApiTime(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

type Props = {
  name: string;
  hint: string;
  /** Set when the badge is earned. */
  earnedAt?: string;
  /** True in a badge case, for one not earned yet; leave off where only earned badges are shown. */
  locked?: boolean;
  children: ReactNode;
  className?: string;
  testId?: string;
};

function Body({ name, hint, earnedAt, locked }: Pick<Props, "name" | "hint" | "earnedAt" | "locked">) {
  return (
    <div className="grid gap-1 text-left text-xs leading-snug">
      <p className="font-semibold">{name}</p>
      <p>{hint}</p>
      {earnedAt && <p className="opacity-80">Earned {earnedDate(earnedAt)}</p>}
      {locked && <p className="opacity-80">Not earned yet</p>}
    </div>
  );
}

/** Name, hint and date on hover or focus; a coarse pointer (a phone) gets tap-to-open instead,
 *  the same split `Term` makes. */
export function BadgeTip({ name, hint, earnedAt, locked, children, className, testId }: Props) {
  const coarse = useCoarsePointer();
  const trigger = <button type="button" data-testid={testId} className={cn("rounded-md text-left", className)} />;
  if (coarse) {
    return (
      <Popover>
        <PopoverTrigger render={trigger}>{children}</PopoverTrigger>
        <PopoverContent align="center" className="w-auto max-w-72 p-2.5">
          <Body name={name} hint={hint} earnedAt={earnedAt} locked={locked} />
        </PopoverContent>
      </Popover>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger render={trigger}>{children}</TooltipTrigger>
      <TooltipContent className="block max-w-72 py-2">
        <Body name={name} hint={hint} earnedAt={earnedAt} locked={locked} />
      </TooltipContent>
    </Tooltip>
  );
}
