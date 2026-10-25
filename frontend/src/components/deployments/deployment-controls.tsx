"use client";

import { useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { LiveDot } from "@/components/motion/live-dot";
import { useControlDeployment } from "@/lib/queries";
import type { Deployment } from "@/lib/types";

const STATUS_WORDS: Record<Deployment["status"], string> = {
  active: "Running",
  paused: "Paused",
  stopping: "Stopping",
  stopped: "Stopped",
};

/** The lamp: lit while running, amber while paused, dim once stopping or stopped. */
export function StatusLamp({ status }: { status: Deployment["status"] }) {
  const tone = status === "active" ? "accent" : status === "paused" ? "warn" : "off";
  return (
    <span className="t-meta inline-flex items-center gap-1.5">
      <LiveDot tone={tone} pulse={status === "active"} className="size-2" />
      {STATUS_WORDS[status]}
    </span>
  );
}

function StopButton({ dep }: { dep: Deployment }) {
  const control = useControlDeployment();
  const [open, setOpen] = useState(false);
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) control.reset();
      }}
    >
      <AlertDialogTrigger render={<Button variant="outline" size="sm" />}>Stop</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Stop {dep.name}?</AlertDialogTitle>
          <AlertDialogDescription>
            Any open trades are exited at market, and the cash returns to your account. If the markets are closed, it
            waits for them to open first.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {control.error && (
          <Alert variant="destructive">
            <AlertDescription>{control.error.message}</AlertDescription>
          </Alert>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>Keep it running</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={control.isPending}
            onClick={(e) => {
              e.preventDefault(); // stay open until the server answers, so a refusal can be shown
              control.mutate({ id: dep.id, action: "stop" }, { onSuccess: () => setOpen(false) });
            }}
          >
            {control.isPending ? "Stopping…" : "Stop deployment"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** Pause / Resume / Stop for a deployment that is still alive; nothing once it is stopping or stopped. */
export function DeploymentControls({ dep }: { dep: Deployment }) {
  const control = useControlDeployment();
  if (dep.status === "stopping" || dep.status === "stopped") return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {dep.status === "active" ? (
        <Button
          variant="outline"
          size="sm"
          disabled={control.isPending}
          onClick={() => control.mutate({ id: dep.id, action: "pause" })}
        >
          Pause
        </Button>
      ) : (
        <Button size="sm" disabled={control.isPending} onClick={() => control.mutate({ id: dep.id, action: "resume" })}>
          Resume
        </Button>
      )}
      <StopButton dep={dep} />
      {control.error && (
        <p role="alert" className="text-xs text-destructive">
          {control.error.message}
        </p>
      )}
    </div>
  );
}
