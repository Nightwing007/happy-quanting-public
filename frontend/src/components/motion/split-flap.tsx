"use client";

import { Fragment, useLayoutEffect, useRef } from "react";
import { prefersReducedMotion } from "./use-reduced-motion";
import { cn } from "@/lib/utils";

const TICK_MS = 55;
const FLIP_MS = 120;
const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
// Titles settle left to right within about 550 ms, however long they are.
const MAX_TICKS = 10;

/**
 * Page-title split-flap: wheels (two-tone faces, hinge line) that riffle once on mount. Titles only - never prices
 * or any number that carries meaning. The real letters stay in the DOM (so headings keep their text); the scramble
 * is drawn from data-g. Words never break mid-word.
 */
export function SplitFlap({ text, className }: { text: string; className?: string }) {
  const root = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const el = root.current;
    if (!el || prefersReducedMotion()) return;
    const tiles = Array.from(el.querySelectorAll<HTMLElement>(".sf-tile"));
    if (tiles.length === 0) return;

    // Letter i settles after round((3 + i*1.25 + rand*4) * pace) ticks.
    const raw = tiles.map((_, i) => 3 + i * 1.25 + Math.random() * 4);
    const pace = Math.min(1, MAX_TICKS / Math.max(...raw));
    const settle = raw.map((r) => Math.max(1, Math.round(r * pace)));
    const glyph = () => GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
    const ghost = (t: HTMLElement) => t.querySelector<HTMLElement>(".sf-ghost")!;

    tiles.forEach((t) => {
      t.setAttribute("data-flap", "");
      ghost(t).dataset.g = glyph();
    });

    let tick = 0;
    const settled = new Set<number>();
    const id = window.setInterval(() => {
      tick += 1;
      tiles.forEach((t, i) => {
        if (settled.has(i)) return;
        if (tick >= settle[i]) {
          settled.add(i);
          t.removeAttribute("data-flap");
          t.animate(
            [
              { transform: "perspective(12em) rotateX(-78deg)", filter: "brightness(1.6)" },
              { transform: "perspective(12em) rotateX(0deg)", filter: "brightness(1)" },
            ],
            { duration: FLIP_MS, easing: "cubic-bezier(0.16, 1, 0.3, 1)" },
          );
        } else {
          ghost(t).dataset.g = glyph();
        }
      });
      if (settled.size === tiles.length) window.clearInterval(id);
    }, TICK_MS);

    return () => {
      window.clearInterval(id);
      tiles.forEach((t) => t.removeAttribute("data-flap"));
    };
  }, [text]);

  // CSS uppercases the letters; the DOM keeps the original text (and a plain space between words for copy/paste).
  return (
    <span ref={root} role="img" aria-label={text} className={cn("t-display sf-line", className)}>
      {text.split(" ").map((word, w) => (
        <Fragment key={w}>
          {w > 0 && " "}
          <span className="sf-word">
            {Array.from(word).map((ch, i) => (
              <span key={i} className="sf-tile">
                <span className="sf-real">{ch}</span>
                <span className="sf-ghost" aria-hidden="true" />
              </span>
            ))}
          </span>
        </Fragment>
      ))}
    </span>
  );
}
