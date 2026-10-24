import { Suspense } from "react";
import { TradeView } from "./trade-view";

export default function TradePage() {
  // useSearchParams needs a Suspense boundary or `next build` fails.
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <TradeView />
    </Suspense>
  );
}
