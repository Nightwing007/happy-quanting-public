import type { CSSProperties } from "react";
import { cn } from "@/lib/utils";

/**
 * Rise-with-stagger entry for a page section (760 ms, 70 ms per item, only the first 8 are staggered).
 * Pure CSS: the content is in the DOM from the first paint, so numbers are never delayed by the animation.
 */
export function Rise({
  i = 0,
  as: Tag = "div",
  className,
  children,
}: {
  i?: number;
  as?: "div" | "section" | "ul" | "header";
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Tag className={cn("rise", className)} style={{ "--i": i } as CSSProperties}>
      {children}
    </Tag>
  );
}
