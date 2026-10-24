import type {
  Bars,
  BrokerGroup,
  Health,
  HistoryLimits,
  Instrument,
  Metrics,
  Order,
  OrderIn,
  OrderPreview,
  Payouts,
  Portfolio,
  ProtectionIn,
  ProtectionPreview,
  Quote,
  Settings,
  SettingsIn,
  SimControl,
  SimSession,
  SimSessionIn,
  SimSessionState,
  Trade,
  WatchlistItem,
} from "./types";

const UNREACHABLE = "Can't reach the Happy Quanting server. Is the backend running (npm run dev)?";

/** `message` is always safe to show to the user as-is. */
export class ApiError extends Error {
  status: number;
  /** Stable snake_case name for the problem (e.g. "broker_unavailable"); null when the server sent none. */
  code: string | null;
  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function errorCode(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("code" in body)) return null;
  const { code } = body as { code: unknown };
  return typeof code === "string" && code ? code : null;
}

function detailMessage(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("detail" in body)) return null;
  const { detail } = body as { detail: unknown };
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean);
    if (msgs.length) return msgs.join(" ");
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(UNREACHABLE, 0);
  }

  if (!res.ok) {
    // The Next proxy answers 500/502-504 with a non-JSON body when the backend is down,
    // so a 5xx without a JSON detail means "can't reach it", not "it said no".
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // fall through to the generic message
    }
    if (res.status >= 500 && detailMessage(body) === null) throw new ApiError(UNREACHABLE, res.status);
    throw new ApiError(detailMessage(body) ?? `The server returned an error (${res.status}).`, res.status, errorCode(body));
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// Symbols contain ^ and =, so they only ever travel as encoded query parameters.
function qs(params: Record<string, string | number | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

const JSON_HEADERS = { "Content-Type": "application/json" };

/** Where the trading routes live. The live account is /api; a simulation is /api/sim/sessions/{id}. */
export const LIVE_BASE = "/api";
export const simBase = (id: number) => `/api/sim/sessions/${id}`;

export const getHealth = () => request<Health>("/api/health");

export const searchInstruments = (q: string) =>
  request<Instrument[]>(`/api/market/search${qs({ q })}`);

export const getQuote = (symbol: string) => request<Quote>(`/api/market/quote${qs({ symbol })}`);

export const getBars = (symbol: string, interval: string, range: string, indicators: string[] = []) =>
  request<Bars>(`/api/market/bars${qs({ symbol, interval, range, indicators: indicators.join(",") })}`);

export const getMetrics = (symbol: string) =>
  request<Metrics>(`/api/market/metrics${qs({ symbol })}`);

export const getPortfolio = (base = LIVE_BASE) => request<Portfolio>(`${base}/portfolio`);

export const resetPortfolio = () => request<Portfolio>("/api/portfolio/reset", { method: "POST" });

export type OrderFilters = { status?: string; symbol?: string; limit?: number };

export const getOrders = (filters: OrderFilters = {}, base = LIVE_BASE) =>
  request<Order[]>(`${base}/orders${qs(filters)}`);

export const placeOrder = (body: OrderIn, base = LIVE_BASE) =>
  request<Order>(`${base}/orders`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });

export const previewOrder = (body: OrderIn, base = LIVE_BASE) =>
  request<OrderPreview>(`${base}/orders/preview`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });

export const getPayouts = (base = LIVE_BASE) => request<Payouts>(`${base}/payouts`);

export type TradeFilters = { status?: string; symbol?: string; limit?: number };

export const getTrades = (filters: TradeFilters = {}, base = LIVE_BASE) =>
  request<Trade[]>(`${base}/trades${qs(filters)}`);

// `quantity` omitted means the whole open part.
export const exitTrade = ({ id, quantity }: { id: number; quantity?: string }, base = LIVE_BASE) =>
  request<Order>(`${base}/trades/${id}/exit`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ quantity: quantity ?? null }),
  });

export const previewExit = (id: number, quantity?: string, base = LIVE_BASE) =>
  request<OrderPreview>(`${base}/trades/${id}/exit/preview`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ quantity: quantity ?? null }),
  });

// Null clears that price. The preview checks the prices and shows what each would leave you with; saves nothing.
export const previewProtection = (id: number, body: ProtectionIn, base = LIVE_BASE) =>
  request<ProtectionPreview>(`${base}/trades/${id}/protection/preview`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });

export const setProtection = ({ id, ...body }: { id: number } & ProtectionIn, base = LIVE_BASE) =>
  request<Trade>(`${base}/trades/${id}/protection`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });

export const getSettings = () => request<Settings>("/api/settings");

export const updateSettings = (body: SettingsIn) =>
  request<Settings>("/api/settings", { method: "PUT", headers: JSON_HEADERS, body: JSON.stringify(body) });

export const getBrokers = () => request<BrokerGroup[]>("/api/brokers");

export const cancelOrder = (id: number, base = LIVE_BASE) =>
  request<Order>(`${base}/orders/${id}`, { method: "DELETE" });

export const getWatchlist = () => request<WatchlistItem[]>("/api/watchlist");

export const addToWatchlist = (symbol: string) =>
  request<WatchlistItem>("/api/watchlist", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ symbol }),
  });

export const removeFromWatchlist = (symbol: string) =>
  request<void>(`/api/watchlist${qs({ symbol })}`, { method: "DELETE" });

export const getHistoryLimits = () => request<HistoryLimits>("/api/market/history-limits");

export const listSimSessions = () => request<SimSession[]>("/api/sim/sessions");

export const createSimSession = (body: SimSessionIn) =>
  request<SimSession>("/api/sim/sessions", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });

export const getSimSession = (id: number, barsLimit = 1000) =>
  request<SimSessionState>(`/api/sim/sessions/${id}${qs({ bars_limit: barsLimit })}`);

export const controlSimSession = ({ id, ...body }: { id: number } & SimControl) =>
  request<SimSession>(`/api/sim/sessions/${id}/control`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });

export const deleteSimSession = (id: number) => request<void>(`/api/sim/sessions/${id}`, { method: "DELETE" });
