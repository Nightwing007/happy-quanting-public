// Friendly names over the generated API types. Edit these, never api-types.ts
// (regenerate that with `npm --prefix frontend run gen:api`).
import type { components } from "./api-types";

type Schemas = components["schemas"];

export type Quote = Schemas["QuoteOut"];
export type Instrument = Schemas["InstrumentOut"];
export type Bars = Schemas["BarsOut"];
export type Bar = Schemas["BarOut"];
export type IndicatorSeries = Schemas["IndicatorSeriesOut"];
export type Portfolio = Schemas["PortfolioOut"];
export type Holding = Schemas["HoldingOut"];
export type Trade = Schemas["TradeOut"];
export type OrderLeg = Schemas["OrderLegOut"];
export type Payouts = Schemas["PayoutsOut"];
export type Payout = Schemas["PayoutOut"];
export type MarketStatus = Schemas["MarketStatusOut"];
export type Order = Schemas["OrderOut"];
export type OrderIn = Schemas["OrderIn"];
export type Charge = Schemas["ChargeOut"];
export type OrderPreview = Schemas["OrderPreviewOut"];
export type Settings = Schemas["SettingsOut"];
export type SettingsIn = Schemas["SettingsIn"];
export type BrokerGroup = Schemas["SegmentBrokersOut"];
export type Broker = Schemas["BrokerOut"];
export type Metrics = Schemas["MetricsOut"];
export type Metric = Schemas["MetricOut"];
export type ProtectionIn = Schemas["ProtectionIn"];
export type ProtectionOutcome = Schemas["ProtectionOutcomeOut"];
export type ProtectionPreview = Schemas["ProtectionPreviewOut"];
export type WatchlistItem = Schemas["WatchlistItemOut"];

// /api/health is declared as a loose string map in the schema; pin down the real shape.
export type Health = {
  status: string;
  data_source: string;
  base_currency: string;
};
