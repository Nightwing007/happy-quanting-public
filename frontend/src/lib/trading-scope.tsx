"use client";

import { createContext, useContext } from "react";
import { LIVE_BASE } from "./api";

const TradingScopeContext = createContext<string>(LIVE_BASE);

/** Which account the trading components talk to: the live one by default, or a simulation's. */
export function TradingScope({ base, children }: { base: string; children: React.ReactNode }) {
  return <TradingScopeContext.Provider value={base}>{children}</TradingScopeContext.Provider>;
}

export const useTradingBase = () => useContext(TradingScopeContext);
