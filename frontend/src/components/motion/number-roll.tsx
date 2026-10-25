"use client";

import { useEffect, useRef } from "react";
import { prefersReducedMotion } from "./use-reduced-motion";

const DURATION_MS = 450;
const easeOut = (t: number) => 1 - Math.pow(1 - t, 4);

// Write into React's own text node (not textContent) so React keeps a valid reference to it.
const setText = (node: HTMLElement, text: string) => {
  if (node.firstChild) node.firstChild.nodeValue = text;
  else node.textContent = text;
};

/**
 * Shows `format(value)`. The first render is instant; later changes tween briefly and always end on the
 * exact formatted value. Text is written straight to the DOM so a tween never re-renders React.
 */
export function NumberRoll({
  value,
  format,
  className,
}: {
  value: number;
  format: (n: number) => string;
  className?: string;
}) {
  const el = useRef<HTMLSpanElement>(null);
  const shown = useRef(value);
  const formatRef = useRef(format);

  useEffect(() => {
    formatRef.current = format;
  });

  useEffect(() => {
    const node = el.current;
    const from = shown.current;
    if (!node || from === value) return;
    const fmt = formatRef.current;
    if (prefersReducedMotion()) {
      shown.current = value;
      setText(node, fmt(value));
      return;
    }
    let raf = 0;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / DURATION_MS);
      const v = t >= 1 ? value : from + (value - from) * easeOut(t);
      shown.current = v;
      setText(node, fmt(v));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  // React owns the initial text; a tween overwrites it and its last frame equals this same string.
  return (
    <span ref={el} className={className}>
      {format(value)}
    </span>
  );
}
