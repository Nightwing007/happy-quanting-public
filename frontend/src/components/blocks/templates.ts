import type { Graph, GraphEdge, GraphNode } from "./graph";

// Prebuilt graphs people can start from. Each is plain data, the same shape the server stores.

const node = (id: string, type: string, x: number, y: number, params: GraphNode["params"] = {}): GraphNode => ({
  id,
  type,
  params,
  position: { x, y },
});
const signal = (source: string, target: string, port = "signal"): GraphEdge => ({
  source,
  source_port: "signal",
  target,
  target_port: port,
});
const attach = (source: string, target: string): GraphEdge => ({
  source,
  source_port: "trigger",
  target,
  target_port: "trigger",
});

export type Template = { key: string; name: string; blurb: string; graph: Graph };

export const TEMPLATES: Template[] = [
  {
    key: "rsi-dip-buyer",
    name: "RSI dip-buyer",
    blurb: "Buys when the RSI shows a hard drop, with a 5% stop-loss, and sells when it recovers.",
    graph: {
      nodes: [
        node("universe_1", "universe", 0, 150, { interval: "1d", markets: "all" }),
        node("rsi_below_1", "rsi_below", 260, 0, { period: 14, level: 30 }),
        node("rsi_above_1", "rsi_above", 260, 300, { period: 14, level: 55 }),
        node("buy_1", "buy", 560, 0, { percent_of_cash: 50 }),
        node("stop_loss_1", "stop_loss", 860, 0, { percent: 5 }),
        node("sell_all_1", "sell_all", 560, 300),
      ],
      edges: [
        signal("rsi_below_1", "buy_1"),
        attach("buy_1", "stop_loss_1"),
        signal("rsi_above_1", "sell_all_1"),
      ],
    },
  },
  {
    key: "sma-trend-follower",
    name: "SMA trend follower",
    blurb: "Buys when the fast average crosses above the slow one, sells when it crosses back below.",
    graph: {
      nodes: [
        node("universe_1", "universe", 0, 130, { interval: "1d", markets: "all" }),
        node("sma_cross_1", "sma_cross", 260, 0, { fast_period: 10, slow_period: 30, direction: "up" }),
        node("sma_cross_2", "sma_cross", 260, 300, { fast_period: 10, slow_period: 30, direction: "down" }),
        node("buy_1", "buy", 580, 0, { percent_of_cash: 50 }),
        node("sell_all_1", "sell_all", 580, 300),
      ],
      edges: [signal("sma_cross_1", "buy_1"), signal("sma_cross_2", "sell_all_1")],
    },
  },
  {
    key: "breakout-with-stop",
    name: "Breakout with stop",
    blurb: "Buys a new 20-bar high with a stop-loss and a profit target, and sells on a new 10-bar low.",
    graph: {
      nodes: [
        node("universe_1", "universe", 0, 150, { interval: "1d", markets: "all" }),
        node("breakout_1", "breakout", 260, 0, { period: 20, direction: "high" }),
        node("breakout_2", "breakout", 260, 320, { period: 10, direction: "low" }),
        node("buy_1", "buy", 560, 0, { percent_of_cash: 50 }),
        node("stop_loss_1", "stop_loss", 860, -60, { percent: 5 }),
        node("target_1", "target", 860, 100, { percent: 15 }),
        node("sell_all_1", "sell_all", 560, 320),
      ],
      edges: [
        signal("breakout_1", "buy_1"),
        attach("buy_1", "stop_loss_1"),
        attach("buy_1", "target_1"),
        signal("breakout_2", "sell_all_1"),
      ],
    },
  },
];
