import { formatQuantity } from "@/lib/format";
import type { Order } from "@/lib/types";

/**
 * What an order really did, in a sentence: "Sell 8: closed 5 of trade #3, opened short #7 (3)".
 * Worked out from the order's legs (the record of every trade it touched); an order that has not
 * filled has none, so it reads as the plain Buy or Sell it will become.
 */
export function orderHeadline(order: Pick<Order, "side" | "origin" | "legs">): string {
  switch (order.origin) {
    case "exit":
      return "Exit";
    case "stop_loss":
      return "Stop-loss";
    case "target":
      return "Target";
    case "square_off":
      return "Square off";
  }
  const kinds = order.legs.map((l) => l.kind);
  if (order.side === "buy") return kinds.length > 0 && kinds.every((k) => k === "close_short") ? "Cover" : "Buy";
  return kinds.length > 0 && kinds.every((k) => k === "open_short") ? "Short" : "Sell";
}

export function orderTouches(order: Pick<Order, "legs">): string[] {
  return order.legs.map((l) => {
    const qty = formatQuantity(l.quantity);
    switch (l.kind) {
      case "open_long":
        return `opened trade #${l.trade_id} (${qty})`;
      case "open_short":
        return `opened short #${l.trade_id} (${qty})`;
      case "close_long":
        return `closed ${qty} of trade #${l.trade_id}`;
      case "close_short":
        return `closed ${qty} of short #${l.trade_id}`;
    }
  });
}

export function describeOrder(order: Pick<Order, "side" | "origin" | "legs" | "quantity" | "status">): string {
  const head = `${orderHeadline(order)} ${formatQuantity(order.quantity)}`;
  const touched = orderTouches(order);
  return touched.length > 0 ? `${head}: ${touched.join(", ")}` : head;
}
