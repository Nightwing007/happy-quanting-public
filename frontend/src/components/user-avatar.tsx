"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/** The picture when the URL loads, otherwise the person's initials. */
export function UserAvatar({ name, url, size = "sm" }: { name: string; url: string | null; size?: "sm" | "lg" }) {
  // Remember which URL failed, so a corrected URL gets another try.
  const [brokenUrl, setBrokenUrl] = useState<string | null>(null);
  const broken = url === brokenUrl;
  const box = cn(
    "inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted font-medium text-muted-foreground",
    size === "lg" ? "size-14 text-lg" : "size-7 text-xs",
  );
  if (url && !broken) {
    // eslint-disable-next-line @next/next/no-img-element -- arbitrary user-supplied host
    return <img src={url} alt="" className={cn(box, "object-cover")} onError={() => setBrokenUrl(url)} />;
  }
  return <span className={box} aria-hidden>{initials(name)}</span>;
}
