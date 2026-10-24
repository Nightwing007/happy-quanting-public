"use client";

import { Term } from "@/components/term";
import { useState } from "react";
import { PauseIcon, PlayIcon, RotateCcwIcon, StepForwardIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useSimControl } from "@/lib/queries";
import { formatExchangeClock, STATUS_WORDS } from "@/lib/sim-format";
import type { SimSession } from "@/lib/types";

export function PlayerBar({ session, symbol }: { session: SimSession; symbol: string }) {
  const control = useSimControl(session.id);
  const [dragSpeed, setDragSpeed] = useState<number | null>(null);

  const running = session.status === "running";
  const finished = session.status === "finished";
  const canStep = session.status === "ready" || session.status === "paused";
  const speed = dragSpeed ?? session.speed;
  const zone = session.exchange_times.find((t) => t.symbol === symbol) ?? session.exchange_times[0];

  const send = (body: Parameters<typeof control.mutate>[0]) => control.mutate(body);
  // The route needs an action with a new speed: keep the current play state by repeating it.
  const commitSpeed = () => {
    if (dragSpeed === null) return;
    if (dragSpeed !== session.speed) send({ action: running ? "start" : "pause", speed: dragSpeed });
    setDragSpeed(null);
  };

  return (
    <Card size="sm">
      <CardContent className="grid min-w-0 gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={finished || control.isPending}
            onClick={() => send({ action: running ? "pause" : "start" })}
            aria-label={running ? "Pause" : "Play"}
          >
            {running ? <PauseIcon /> : <PlayIcon />}
            {running ? "Pause" : "Play"}
          </Button>
          <Button size="sm" variant="outline" disabled={!canStep || control.isPending} onClick={() => send({ action: "step", steps: 1 })}>
            <StepForwardIcon />
            Step 1 bar
          </Button>
          <Button size="sm" variant="outline" disabled={!canStep || control.isPending} onClick={() => send({ action: "step", steps: 10 })}>
            <StepForwardIcon />
            Step 10 bars
          </Button>
          <Button size="sm" variant="ghost" disabled={control.isPending} onClick={() => send({ action: "reset" })}>
            <RotateCcwIcon />
            Reset
          </Button>
          <label className="ml-auto flex min-w-0 basis-56 items-center gap-2 text-xs text-muted-foreground">
            <span className="shrink-0 tabular-nums">
              <Term id="speed">{speed} bars/sec</Term>
            </span>
            <input
              type="range"
              min={1}
              max={200}
              value={speed}
              aria-label="Speed in bars per second"
              onChange={(e) => setDragSpeed(Number(e.target.value))}
              onPointerUp={commitSpeed}
              onKeyUp={commitSpeed}
              onBlur={commitSpeed}
              className="min-w-0 flex-1 accent-primary"
            />
          </label>
        </div>

        <div className="grid gap-1">
          <div
            role="progressbar"
            aria-label="Replay progress"
            aria-valuenow={session.progress_percent}
            aria-valuemin={0}
            aria-valuemax={100}
            className="h-2 overflow-hidden rounded-full bg-muted"
          >
            <div className="h-full bg-primary transition-[width]" style={{ width: `${session.progress_percent}%` }} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="tabular-nums">
              {session.progress_percent}% played · {STATUS_WORDS[session.status]}
            </span>
            {zone && (
              <span className="tabular-nums">
                Replayed clock: <strong className="text-foreground">{formatExchangeClock(zone.local_time, zone.timezone)}</strong> (
                {zone.timezone})
              </span>
            )}
          </div>
        </div>

        {control.error && (
          <p role="alert" className="text-sm text-destructive">
            {control.error.message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
