import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Order } from "@/lib/types";

const LABELS: Record<string, string> = {
  open: "Waiting",
  filled: "Filled",
  cancelled: "Cancelled",
  rejected: "Rejected",
};

function variant(status: string) {
  if (status === "filled") return "default" as const;
  if (status === "rejected") return "destructive" as const;
  return "secondary" as const;
}

export const statusLabel = (status: string) => LABELS[status] ?? status;

/** A rejected order explains itself in a tooltip. */
export function OrderStatusBadge({ order }: { order: Pick<Order, "status" | "reject_reason"> }) {
  const badge = <Badge variant={variant(order.status)}>{statusLabel(order.status)}</Badge>;
  if (!order.reject_reason) return badge;
  return (
    <Tooltip>
      <TooltipTrigger render={<span tabIndex={0} className="inline-flex cursor-help" />}>{badge}</TooltipTrigger>
      <TooltipContent>{order.reject_reason}</TooltipContent>
    </Tooltip>
  );
}
