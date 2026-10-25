"use client";

import { TriangleAlertIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ApiError } from "@/lib/api";
import { useHealth } from "@/lib/queries";

export function BackendStatusBanner() {
  const { isError, error } = useHealth();

  // A 401 means "log in", not "server down"; the redirect to /login handles it.
  if (isError && !(error instanceof ApiError && error.status === 401)) {
    return (
      <Alert variant="destructive" className="rounded-none border-x-0">
        <TriangleAlertIcon />
        <AlertTitle>Server unreachable</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }

  return null;
}
