"use client";

import { useCallback } from "react";
import type { PointerEvent } from "react";
import { prefersReducedMotion } from "./use-reduced-motion";

const PSEUDO = "::before";

type Side = "top" | "right" | "bottom" | "left";

function nearestSide(el: HTMLElement, x: number, y: number): Side {
  const r = el.getBoundingClientRect();
  const d: [Side, number][] = [
    ["top", y - r.top],
    ["right", r.right - x],
    ["bottom", r.bottom - y],
    ["left", x - r.left],
  ];
  return d.reduce((a, b) => (b[1] < a[1] ? b : a))[0];
}

const pct = (v: number) => `${(v * 100).toFixed(2)}%`;

/** The sheet anchored at `side`, its free edge `a` and `b` of the way across (one per corner, so the edge can lean). */
function poly(side: Side, a: number, b: number) {
  switch (side) {
    case "left":
      return `polygon(0% 0%, ${pct(a)} 0%, ${pct(b)} 100%, 0% 100%)`;
    case "right":
      return `polygon(${pct(1 - a)} 0%, 100% 0%, 100% 100%, ${pct(1 - b)} 100%)`;
    case "top":
      return `polygon(0% 0%, 100% 0%, 100% ${pct(b)}, 0% ${pct(a)})`;
    default:
      return `polygon(0% ${pct(1 - a)}, 100% ${pct(1 - b)}, 100% 100%, 0% 100%)`;
  }
}

const outCubic = (t: number) => 1 - (1 - t) ** 3;
const inOutCubic = (t: number) => (t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2);

/** Keyframes for the sheet coming in from, or going out through, `side`. The two corners of the free edge run on
 *  different curves (one lunges, one follows), which tilts the edge mid-flight like a plane being pulled across. */
function sweep(side: Side, dir: "in" | "out", lead: boolean) {
  const frames: string[] = [];
  const N = 12;
  for (let k = 0; k <= N; k++) {
    const t = k / N;
    const fast = outCubic(t);
    const slow = inOutCubic(t);
    const [a, b] = lead ? [fast, slow] : [slow, fast];
    frames.push(dir === "in" ? poly(side, a, b) : poly(side, 1 - a, 1 - b));
  }
  return frames;
}

function run(el: HTMLElement, frames: string[], ms: number, dropAtEnd: boolean) {
  for (const a of el.getAnimations({ subtree: false })) {
    if ((a.effect as KeyframeEffect | null)?.pseudoElement === PSEUDO) a.cancel();
  }
  const anim = el.animate(
    frames.map((clipPath) => ({ clipPath })),
    { duration: ms, easing: "linear", fill: "forwards", pseudoElement: PSEUDO },
  );
  // A collapsed end state equals the stylesheet default, so drop the animation instead of piling them up.
  if (dropAtEnd) anim.onfinish = () => anim.cancel();
}

/**
 * Directional flood for rows and cards: spread `{...dh}` and merge `dh.className`. The sheet enters from the edge
 * the pointer entered by and leaves through the edge it left by. `flood: true` is the full ink/violet sheet for
 * cards and tiles that link somewhere; the default is the soft wash used on table rows.
 */
export function useDirectionalHover({ flood = false }: { flood?: boolean } = {}) {
  const onPointerEnter = useCallback((e: PointerEvent<HTMLElement>) => {
    if (prefersReducedMotion() || e.pointerType === "touch") return;
    const el = e.currentTarget;
    run(el, sweep(nearestSide(el, e.clientX, e.clientY), "in", Math.random() < 0.5), 420, false);
  }, []);
  const onPointerLeave = useCallback((e: PointerEvent<HTMLElement>) => {
    if (prefersReducedMotion() || e.pointerType === "touch") return;
    const el = e.currentTarget;
    run(el, sweep(nearestSide(el, e.clientX, e.clientY), "out", Math.random() < 0.5), 340, true);
  }, []);
  return { className: flood ? "dh dh-flood" : "dh", onPointerEnter, onPointerLeave };
}

