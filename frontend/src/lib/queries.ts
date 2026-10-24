"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import * as api from "./api";
import { LIVE_BASE } from "./api";
import type { OrderFilters, TradeFilters } from "./api";
import { useTradingBase } from "./trading-scope";
import type { OrderIn, ProtectionIn, SimControl, SimSessionIn } from "./types";

const THIRTY_SECONDS = 30_000;

// Live keys stay as they are; a simulation's are nested under its base so the two never mix, and
// invalidating one account's keys never touches the other's.
export const scoped = (base: string, key: readonly unknown[]): readonly unknown[] =>
  base === LIVE_BASE ? key : ["scope", base, ...key];

export const queryKeys = {
  health: ["health"] as const,
  search: (q: string) => ["search", q] as const,
  quote: (symbol: string) => ["quote", symbol] as const,
  bars: (symbol: string, interval: string, range: string, indicators: string[]) =>
    ["bars", symbol, interval, range, indicators] as const,
  metrics: (symbol: string) => ["metrics", symbol] as const,
  portfolio: ["portfolio"] as const,
  orders: (filters: OrderFilters) => ["orders", filters] as const,
  ordersAll: ["orders"] as const,
  trades: (filters: TradeFilters) => ["trades", filters] as const,
  tradesAll: ["trades"] as const,
  payouts: ["payouts"] as const,
  exitPreview: (id: number, quantity: string | undefined) => ["order-preview", "exit", id, quantity ?? null] as const,
  protectionPreview: (id: number, body: ProtectionIn) => ["protection-preview", id, body] as const,
  watchlist: ["watchlist"] as const,
  settings: ["settings"] as const,
  brokers: ["brokers"] as const,
  previewAll: ["order-preview"] as const,
  preview: (body: OrderIn) => ["order-preview", body] as const,
  historyLimits: ["history-limits"] as const,
  simSessions: ["sim-sessions"] as const,
  simState: (id: number) => ["sim-state", id] as const,
};

export const useHealth = () =>
  useQuery({
    queryKey: queryKeys.health,
    queryFn: api.getHealth,
    refetchInterval: 15_000,
    retry: false,
  });

// The caller debounces `q`.
export const useSearch = (q: string) => {
  const trimmed = q.trim();
  return useQuery({
    queryKey: queryKeys.search(trimmed),
    queryFn: () => api.searchInstruments(trimmed),
    enabled: trimmed.length > 0,
    staleTime: 60_000,
  });
};

export const useQuote = (symbol: string | null) =>
  useQuery({
    queryKey: queryKeys.quote(symbol ?? ""),
    queryFn: () => api.getQuote(symbol!),
    enabled: !!symbol,
    refetchInterval: THIRTY_SECONDS,
  });

export const useBars = (symbol: string | null, interval: string, range: string, indicators: string[] = []) =>
  useQuery({
    queryKey: queryKeys.bars(symbol ?? "", interval, range, indicators),
    queryFn: () => api.getBars(symbol!, interval, range, indicators),
    enabled: !!symbol,
    placeholderData: keepPreviousData,
  });

// Company ratios move with filings, not ticks; the server caches them 15 minutes too.
export const useMetrics = (symbol: string | null) =>
  useQuery({
    queryKey: queryKeys.metrics(symbol ?? ""),
    queryFn: () => api.getMetrics(symbol!),
    enabled: !!symbol,
    staleTime: 15 * 60_000,
  });

// The trading hooks read which account they talk to from the surrounding <TradingScope>.
export const usePortfolio = () => {
  const base = useTradingBase();
  return useQuery({
    queryKey: scoped(base, queryKeys.portfolio),
    queryFn: () => api.getPortfolio(base),
    refetchInterval: THIRTY_SECONDS,
  });
};

export const useOrders = (filters: OrderFilters = {}, enabled = true) => {
  const base = useTradingBase();
  return useQuery({
    queryKey: scoped(base, queryKeys.orders(filters)),
    queryFn: () => api.getOrders(filters, base),
    enabled,
  });
};

export const usePayouts = () => {
  const base = useTradingBase();
  return useQuery({
    queryKey: scoped(base, queryKeys.payouts),
    queryFn: () => api.getPayouts(base),
    refetchInterval: THIRTY_SECONDS,
  });
};

export const useTrades = (filters: TradeFilters = {}) => {
  const base = useTradingBase();
  return useQuery({
    queryKey: scoped(base, queryKeys.trades(filters)),
    queryFn: () => api.getTrades(filters, base),
    refetchInterval: THIRTY_SECONDS,
  });
};

// The caller debounces `quantity`. Shares the order-preview key prefix so a fill refreshes it.
export const useExitPreview = (id: number | null, quantity: string | undefined, enabled = true) => {
  const base = useTradingBase();
  return useQuery({
    queryKey: scoped(base, queryKeys.exitPreview(id ?? 0, quantity)),
    queryFn: () => api.previewExit(id!, quantity, base),
    enabled: enabled && id !== null,
    placeholderData: keepPreviousData,
    retry: false,
  });
};

// The caller debounces the prices. Previews are of the current price, so they refetch with the quote.
export const useProtectionPreview = (id: number, body: ProtectionIn | null) => {
  const base = useTradingBase();
  return useQuery({
    queryKey: scoped(base, queryKeys.protectionPreview(id, body ?? {})),
    queryFn: () => api.previewProtection(id, body!, base),
    enabled: !!body,
    placeholderData: keepPreviousData,
    retry: false,
  });
};

export const useWatchlist = () =>
  useQuery({
    queryKey: queryKeys.watchlist,
    queryFn: api.getWatchlist,
    refetchInterval: THIRTY_SECONDS,
  });

// The caller debounces `body`. A null body (nothing valid to quote yet) disables the query.
export const useOrderPreview = (body: OrderIn | null) => {
  const base = useTradingBase();
  return useQuery({
    queryKey: scoped(base, queryKeys.preview(body ?? ({} as OrderIn))),
    queryFn: () => api.previewOrder(body!, base),
    enabled: !!body,
    placeholderData: keepPreviousData,
    retry: false,
  });
};

export const useSettings = () => useQuery({ queryKey: queryKeys.settings, queryFn: api.getSettings });

export const useBrokers = () =>
  useQuery({ queryKey: queryKeys.brokers, queryFn: api.getBrokers, staleTime: 5 * 60_000 });

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.updateSettings,
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.settings, data);
      qc.invalidateQueries({ queryKey: queryKeys.portfolio });
      qc.invalidateQueries({ queryKey: queryKeys.previewAll });
    },
  });
}

/** Refetch everything an account's balances and lists are drawn from. */
export function invalidateAccount(qc: QueryClient, base: string) {
  qc.invalidateQueries({ queryKey: scoped(base, queryKeys.previewAll) });
  qc.invalidateQueries({ queryKey: scoped(base, queryKeys.portfolio) });
  qc.invalidateQueries({ queryKey: scoped(base, queryKeys.tradesAll) });
  qc.invalidateQueries({ queryKey: scoped(base, queryKeys.payouts) });
  qc.invalidateQueries({ queryKey: scoped(base, queryKeys.ordersAll) });
}

export function usePlaceOrder() {
  const qc = useQueryClient();
  const base = useTradingBase();
  return useMutation({
    mutationFn: (body: OrderIn) => api.placeOrder(body, base),
    onSuccess: () => invalidateAccount(qc, base),
  });
}

export function useExitTrade() {
  const qc = useQueryClient();
  const base = useTradingBase();
  return useMutation({
    mutationFn: (arg: { id: number; quantity?: string }) => api.exitTrade(arg, base),
    onSuccess: (_order, { id }) => {
      // The exited trade's own previews are dropped, not refetched: it may be closed now and the
      // server would refuse. Other previews are stale because cash and holdings changed.
      qc.removeQueries({ queryKey: scoped(base, ["order-preview", "exit", id]) });
      // A simulation's keys carry two extra leading parts ("scope", base).
      const kindAt = base === LIVE_BASE ? 1 : 3;
      qc.invalidateQueries({
        queryKey: scoped(base, queryKeys.previewAll),
        predicate: (q) => q.queryKey[kindAt] !== "exit",
      });
      qc.invalidateQueries({ queryKey: scoped(base, queryKeys.portfolio) });
      qc.invalidateQueries({ queryKey: scoped(base, queryKeys.tradesAll) });
      qc.invalidateQueries({ queryKey: scoped(base, queryKeys.payouts) });
      qc.invalidateQueries({ queryKey: scoped(base, queryKeys.ordersAll) });
    },
  });
}

export function useSetProtection() {
  const qc = useQueryClient();
  const base = useTradingBase();
  return useMutation({
    mutationFn: (arg: { id: number } & ProtectionIn) => api.setProtection(arg, base),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scoped(base, queryKeys.portfolio) });
      qc.invalidateQueries({ queryKey: scoped(base, queryKeys.tradesAll) });
      qc.invalidateQueries({ queryKey: scoped(base, queryKeys.payouts) });
    },
  });
}

export function useCancelOrder() {
  const qc = useQueryClient();
  const base = useTradingBase();
  return useMutation({
    mutationFn: (id: number) => api.cancelOrder(id, base),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: scoped(base, queryKeys.portfolio) });
      qc.invalidateQueries({ queryKey: scoped(base, queryKeys.ordersAll) });
    },
  });
}

export function useResetPortfolio() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.resetPortfolio,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.portfolio });
      qc.invalidateQueries({ queryKey: queryKeys.ordersAll });
      qc.invalidateQueries({ queryKey: queryKeys.tradesAll });
      qc.invalidateQueries({ queryKey: queryKeys.payouts });
      qc.invalidateQueries({ queryKey: queryKeys.watchlist });
    },
  });
}

export function useAddToWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.addToWatchlist,
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.watchlist }),
  });
}

export function useRemoveFromWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.removeFromWatchlist,
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.watchlist }),
  });
}

// Earliest date each interval can be replayed from.
export const useHistoryLimits = () =>
  useQuery({ queryKey: queryKeys.historyLimits, queryFn: api.getHistoryLimits, staleTime: 60 * 60_000 });

export const useSimSessions = () =>
  useQuery({ queryKey: queryKeys.simSessions, queryFn: api.listSimSessions, refetchInterval: THIRTY_SECONDS });

// Polls quickly while the replay is running and not at all when it is paused or finished.
export const useSimState = (id: number) =>
  useQuery({
    queryKey: queryKeys.simState(id),
    queryFn: () => api.getSimSession(id),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 500 : false),
    placeholderData: keepPreviousData,
  });

export function useCreateSimSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SimSessionIn) => api.createSimSession(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.simSessions }),
  });
}

export function useDeleteSimSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteSimSession(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.simSessions }),
  });
}

export function useSimControl(id: number) {
  const qc = useQueryClient();
  const base = api.simBase(id);
  return useMutation({
    mutationFn: (body: SimControl) => api.controlSimSession({ id, ...body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.simState(id) });
      invalidateAccount(qc, base);
    },
  });
}
