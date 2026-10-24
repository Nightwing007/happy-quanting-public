"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import * as api from "./api";
import { LIVE_BASE } from "./api";
import type { OrderFilters, TradeFilters } from "./api";
import { useTradingBase } from "./trading-scope";
import type { BacktestIn, CompileIn, CustomBlockIn, ListingIn, ListingUpdateIn, OrderIn, ProtectionIn, SimControl, SimSessionIn, SubscribeIn, UserAlgoIn } from "./types";

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
  algoLibrary: ["algo-library"] as const,
  myAlgos: ["my-algos"] as const,
  backtests: ["backtests"] as const,
  backtest: (id: number) => ["backtest", id] as const,
  listings: (market: string | null, creator: string | null) => ["listings", market, creator] as const,
  listing: (id: number) => ["listing", id] as const,
  creator: (username: string) => ["creator", username] as const,
  subscriptions: ["subscriptions"] as const,
  earnings: ["earnings"] as const,
  algoRules: ["algo-rules"] as const,
  myListings: ["my-listings"] as const,
  blockCatalog: ["block-catalog"] as const,
};

export const useHealth = () =>
  useQuery({
    queryKey: queryKeys.health,
    queryFn: api.getHealth,
    refetchInterval: 15_000,
    retry: false,
  });

const ME_KEY = ["me"] as const;

// A 401 here just means "not logged in", so it becomes null rather than an error.
export const useMe = () =>
  useQuery({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await api.getMe();
      } catch (e) {
        if (e instanceof api.ApiError && e.status === 401) return null;
        throw e;
      }
    },
    retry: false,
    staleTime: 60_000,
  });

// Login, signup and logout empty the cache so one user's data is never shown to the next.
export const useLogin = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.login,
    onSuccess: (user) => {
      qc.clear();
      qc.setQueryData(ME_KEY, user);
    },
  });
};

export const useSignup = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.signup,
    onSuccess: (user) => {
      qc.clear();
      qc.setQueryData(ME_KEY, user);
    },
  });
};

export const useLogout = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      qc.clear();
      qc.setQueryData(ME_KEY, null);
    },
  });
};

export const useUpdateMe = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.updateMe,
    onSuccess: (user) => qc.setQueryData(ME_KEY, user),
  });
};

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

export const useAlgoLibrary = () =>
  useQuery({ queryKey: queryKeys.algoLibrary, queryFn: api.getAlgoLibrary, staleTime: 60 * 60_000 });

export const useMyAlgos = () => useQuery({ queryKey: queryKeys.myAlgos, queryFn: api.listMyAlgos });

export function useCreateMyAlgo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: UserAlgoIn) => api.createMyAlgo(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.myAlgos }),
  });
}

export function useUpdateMyAlgo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: UserAlgoIn & { id: number }) => api.updateMyAlgo(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.myAlgos }),
  });
}

export function useDeleteMyAlgo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteMyAlgo(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.myAlgos }),
  });
}

export function useRunBacktest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BacktestIn) => api.createBacktest(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.backtests }),
  });
}

export const useBacktests = () =>
  useQuery({
    queryKey: queryKeys.backtests,
    queryFn: api.listBacktests,
    // Queued and running ones move along; a finished list needs no polling.
    refetchInterval: (q) =>
      q.state.data?.some((b) => b.status === "queued" || b.status === "running") ? 1000 : false,
  });

// Polls every second until the run is done or has failed.
export const useBacktest = (id: number | null) =>
  useQuery({
    queryKey: queryKeys.backtest(id ?? 0),
    queryFn: () => api.getBacktest(id!),
    enabled: id !== null,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status === "done" || status === "failed" ? false : 1000;
    },
  });

export function useDeleteBacktest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteBacktest(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.backtests }),
  });
}

// Marketplace. Performance is measured on the server and changes rarely, so no polling here.
export const useListings = (market: string | null = null, creator: string | null = null) =>
  useQuery({
    queryKey: queryKeys.listings(market, creator),
    queryFn: () => api.listListings({ market: market ?? undefined, creator: creator ?? undefined }),
    staleTime: THIRTY_SECONDS,
  });

export const useListing = (id: number) =>
  useQuery({ queryKey: queryKeys.listing(id), queryFn: () => api.getListing(id), staleTime: THIRTY_SECONDS });

export const useCreator = (username: string) =>
  useQuery({ queryKey: queryKeys.creator(username), queryFn: () => api.getCreator(username), retry: false });

// A stopping subscription is waiting for markets to open, so it is polled a little faster.
export const useSubscriptions = () =>
  useQuery({
    queryKey: queryKeys.subscriptions,
    queryFn: api.listSubscriptions,
    refetchInterval: (q) => (q.state.data?.some((s) => s.status === "stopping") ? 10_000 : THIRTY_SECONDS),
  });

// Subscribing and stopping move cash between the live account and the sub-account.
function invalidateAfterSubscriptionChange(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: queryKeys.subscriptions });
  qc.invalidateQueries({ queryKey: queryKeys.portfolio });
  qc.invalidateQueries({ queryKey: queryKeys.earnings });
}

export function useSubscribe(listingId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SubscribeIn) => api.subscribeToListing(listingId, body),
    onSuccess: () => invalidateAfterSubscriptionChange(qc),
  });
}

export function useStopSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.stopSubscription(id),
    onSuccess: () => invalidateAfterSubscriptionChange(qc),
  });
}

export const useEarnings = (enabled = true) =>
  useQuery({ queryKey: queryKeys.earnings, queryFn: api.getEarnings, enabled, refetchInterval: THIRTY_SECONDS });

// Creator side. The rules are static text, so they are fetched once.
export const useAlgoRules = () =>
  useQuery({ queryKey: queryKeys.algoRules, queryFn: api.getAlgoRules, staleTime: Infinity });

export const useValidateCode = () => useMutation({ mutationFn: (source: string) => api.validateCode(source) });

export const useMyListings = () => useQuery({ queryKey: queryKeys.myListings, queryFn: api.listMyListings });

function invalidateAfterListingChange(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: queryKeys.myListings });
  qc.invalidateQueries({ queryKey: ["listings"] });
  qc.invalidateQueries({ queryKey: ["listing"] });
}

export function useCreateListing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ListingIn) => api.createListing(body),
    onSuccess: () => invalidateAfterListingChange(qc),
  });
}

export function useUpdateListing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { id: number } & ListingUpdateIn) => api.updateListing(body),
    onSuccess: () => invalidateAfterListingChange(qc),
  });
}

export function usePublishListing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.publishListing(id),
    onSuccess: () => invalidateAfterListingChange(qc),
  });
}

export function useRetireListing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.retireListing(id),
    onSuccess: () => invalidateAfterListingChange(qc),
  });
}

export function useUpgradeSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.upgradeSubscription(id),
    onSuccess: () => invalidateAfterSubscriptionChange(qc),
  });
}

// --- block editor ---

export const useBlockCatalog = () =>
  useQuery({ queryKey: queryKeys.blockCatalog, queryFn: api.getBlockCatalog, staleTime: 60_000 });

/** The graph compiled on the server. `enabled` stays false until the caller has settled on a graph. */
export const useCompileBlocks = (body: CompileIn, enabled: boolean) =>
  useQuery({
    queryKey: ["blocks-compile", body],
    queryFn: () => api.compileBlocks(body),
    enabled,
    placeholderData: keepPreviousData,
    gcTime: 30_000,
    staleTime: Infinity,
    retry: false,
  });

export function useCreateCustomBlock() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CustomBlockIn) => api.createCustomBlock(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.blockCatalog }),
  });
}
