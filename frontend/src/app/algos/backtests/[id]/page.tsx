import { Suspense } from "react";
import { BacktestPage } from "@/components/algos/backtest-page";

export default function BacktestRoute() {
  // The id is read on the client (useParams), which needs a Suspense boundary or `next build` fails.
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <BacktestPage />
    </Suspense>
  );
}
