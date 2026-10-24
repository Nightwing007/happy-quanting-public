"use client";

import { useId } from "react";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";
import { BADGE_GLYPH, BADGE_REGION, BADGE_SIZES, FRAMES, GLYPHS, REGION_ART, type BadgeSize } from "@/lib/badge-art";

type Props = {
  id: string;
  /** Shown as the SVG title; falls back to the capitalised id. */
  name?: string;
  size?: BadgeSize;
  locked?: boolean;
  className?: string;
};

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function BadgeIcon({ id, name, size = "md", locked = false, className }: Props) {
  const { resolvedTheme } = useTheme();
  const uid = useId();
  const region = REGION_ART[BADGE_REGION[id] ?? "elite"];
  const pal = resolvedTheme === "dark" ? region.dark : region.light;
  const glyph = GLYPHS[BADGE_GLYPH[id] ?? "flag"];
  const champion = id === "champion";
  const px = BADGE_SIZES[size];
  const label = name ?? capitalise(id);
  const gradient = `${uid}-g`;
  const glow = `${uid}-glow`;
  // The star frame's centre sits a little lower than the others'.
  const shift = region.frame === "star" ? "24 28" : "26 26";

  return (
    <svg
      role="img"
      viewBox="0 0 100 100"
      width={px}
      height={px}
      aria-label={locked ? `${label} (locked)` : label}
      data-badge-icon={id}
      className={cn("shrink-0 overflow-visible", locked && "opacity-45 grayscale", className)}
    >
      <title>{label}</title>
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={pal.from} />
          <stop offset="1" stopColor={pal.to} />
        </linearGradient>
        <radialGradient id={glow}>
          <stop offset="0.55" stopColor={pal.from} stopOpacity="0.55" />
          <stop offset="1" stopColor={pal.from} stopOpacity="0" />
        </radialGradient>
      </defs>
      {champion && !locked && (
        // The glow only pulses for people who have not asked for less motion.
        <circle cx="50" cy="52" r="62" fill={`url(#${glow})`} className="motion-safe:animate-pulse" />
      )}
      <path d={FRAMES[region.frame]} fill={`url(#${gradient})`} stroke={pal.edge} strokeWidth="3" strokeLinejoin="round" />
      <g
        transform={`translate(${shift}) scale(2)`}
        fill={glyph.fill ? pal.glyph : "none"}
        stroke={pal.glyph}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {glyph.d.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </g>
      {locked && (
        <g>
          <circle cx="76" cy="76" r="17" fill="#374151" stroke="#ffffff" strokeWidth="3" />
          <rect x="68" y="75" width="16" height="12" rx="2" fill="#ffffff" />
          <path d="M71 75 V71 A5 5 0 0 1 81 71 V75" fill="none" stroke="#ffffff" strokeWidth="3" strokeLinecap="round" />
        </g>
      )}
    </svg>
  );
}
