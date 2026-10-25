"use client";

import { useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function subscribe(onChange: () => void) {
  const mq = window.matchMedia(QUERY);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

/** Non-hook form for effects and event handlers. */
export const prefersReducedMotion = () => typeof window !== "undefined" && window.matchMedia(QUERY).matches;

/** True when the user asked for less motion. Server render assumes no preference. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, prefersReducedMotion, () => false);
}
