"use client";

import { TriangleAlertIcon } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { ApiError } from "@/lib/api";
import { useHealth } from "@/lib/queries";

export function BackendStatusBanner() {
  const { data, isError, error } = useHealth();

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

  if (data?.data_source === "fake") {
    return (
      <div className="mx-auto flex w-full max-w-7xl justify-end px-4 pt-2">
        <Badge variant="secondary">Offline demo data</Badge>
      </div>
    );
  }

  return null;
}
