"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import type { OrderFilters, TradeFilters } from "./api";
import type { OrderIn, ProtectionIn } from "./types";

const THIRTY_SECONDS = 30_000;

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

export const usePortfolio = () =>
  useQuery({
    queryKey: queryKeys.portfolio,
    queryFn: api.getPortfolio,
    refetchInterval: THIRTY_SECONDS,
  });

export const useOrders = (filters: OrderFilters = {}, enabled = true) =>
  useQuery({
    queryKey: queryKeys.orders(filters),
    queryFn: () => api.getOrders(filters),
    enabled,
  });

export const usePayouts = () =>
  useQuery({
    queryKey: queryKeys.payouts,
    queryFn: api.getPayouts,
    refetchInterval: THIRTY_SECONDS,
  });

export const useTrades = (filters: TradeFilters = {}) =>
  useQuery({
    queryKey: queryKeys.trades(filters),
    queryFn: () => api.getTrades(filters),
    refetchInterval: THIRTY_SECONDS,
  });

// The caller debounces `quantity`. Shares the order-preview key prefix so a fill refreshes it.
export const useExitPreview = (id: number | null, quantity: string | undefined, enabled = true) =>
  useQuery({
    queryKey: queryKeys.exitPreview(id ?? 0, quantity),
    queryFn: () => api.previewExit(id!, quantity),
    enabled: enabled && id !== null,
    placeholderData: keepPreviousData,
    retry: false,
  });

// The caller debounces the prices. Previews are of the current price, so they refetch with the quote.
export const useProtectionPreview = (id: number, body: ProtectionIn | null) =>
  useQuery({
    queryKey: queryKeys.protectionPreview(id, body ?? {}),
    queryFn: () => api.previewProtection(id, body!),
    enabled: !!body,
    placeholderData: keepPreviousData,
    retry: false,
  });

export const useWatchlist = () =>
  useQuery({
    queryKey: queryKeys.watchlist,
    queryFn: api.getWatchlist,
    refetchInterval: THIRTY_SECONDS,
  });

// The caller debounces `body`. A null body (nothing valid to quote yet) disables the query.
export const useOrderPreview = (body: OrderIn | null) =>
  useQuery({
    queryKey: queryKeys.preview(body ?? ({} as OrderIn)),
    queryFn: () => api.previewOrder(body!),
    enabled: !!body,
    placeholderData: keepPreviousData,
    retry: false,
  });

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

export function usePlaceOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.placeOrder,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.previewAll });
      qc.invalidateQueries({ queryKey: queryKeys.portfolio });
      qc.invalidateQueries({ queryKey: queryKeys.tradesAll });
      qc.invalidateQueries({ queryKey: queryKeys.payouts });
      qc.invalidateQueries({ queryKey: queryKeys.ordersAll });
    },
  });
}

export function useExitTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.exitTrade,
    onSuccess: (_order, { id }) => {
      // The exited trade's own previews are dropped, not refetched: it may be closed now and the
      // server would refuse. Other previews are stale because cash and holdings changed.
      qc.removeQueries({ queryKey: ["order-preview", "exit", id] });
      qc.invalidateQueries({ queryKey: queryKeys.previewAll, predicate: (q) => q.queryKey[1] !== "exit" });
      qc.invalidateQueries({ queryKey: queryKeys.portfolio });
      qc.invalidateQueries({ queryKey: queryKeys.tradesAll });
      qc.invalidateQueries({ queryKey: queryKeys.payouts });
      qc.invalidateQueries({ queryKey: queryKeys.ordersAll });
    },
  });
}

export function useSetProtection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.setProtection,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.portfolio });
      qc.invalidateQueries({ queryKey: queryKeys.tradesAll });
      qc.invalidateQueries({ queryKey: queryKeys.payouts });
    },
  });
}

export function useCancelOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.cancelOrder,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.portfolio });
      qc.invalidateQueries({ queryKey: queryKeys.ordersAll });
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
