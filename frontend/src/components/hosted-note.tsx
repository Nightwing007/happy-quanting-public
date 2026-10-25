"use client";

import { cn } from "@/lib/utils";

/** Stands where a code entry point would be on a hosted demo, where nobody may bring their own code. */
export function HostedNote({ className }: { className?: string }) {
  return (
    <p role="note" className={cn("border border-line p-3 text-sm text-muted-foreground", className)}>
      Code upload is turned off on this hosted demo
    </p>
  );
}
