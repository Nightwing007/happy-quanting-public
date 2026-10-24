"use client";

import { TriangleAlertIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import type { BacktestDetail } from "@/lib/types";
import { ResultsView } from "./results-view";

/** A backtest as it stands: how far it has got, why it failed, or its results. */
export function BacktestOutcome({ detail }: { detail: BacktestDetail }) {
  if (detail.status === "failed") {
    return (
      <Alert variant="destructive">
        <TriangleAlertIcon />
        <AlertTitle>The backtest failed</AlertTitle>
        <AlertDescription>{detail.error ?? "No reason was recorded."}</AlertDescription>
      </Alert>
    );
  }
  if (detail.status !== "done") {
    return (
      <Card>
        <CardContent className="grid gap-2" role="status">
          <p className="text-sm font-medium">
            {detail.status === "queued" ? "Waiting to start..." : `Running the backtest... ${detail.progress}%`}
          </p>
          <div
            role="progressbar"
            aria-label="Backtest progress"
            aria-valuenow={detail.progress}
            aria-valuemin={0}
            aria-valuemax={100}
            className="h-2 overflow-hidden rounded-full bg-muted"
          >
            <div className="h-full bg-primary transition-[width]" style={{ width: `${detail.progress}%` }} />
          </div>
        </CardContent>
      </Card>
    );
  }
  return <ResultsView detail={detail} />;
}
