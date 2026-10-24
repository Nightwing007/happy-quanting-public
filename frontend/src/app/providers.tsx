"use client";

import { useState } from "react";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";

let redirecting = false;

// Any 401 means the session is gone: send the user to log in once, then bring them back.
function sendToLogin(error: unknown) {
  if (!(error instanceof ApiError) || error.status !== 401 || redirecting) return;
  const { pathname, search } = window.location;
  if (pathname === "/login" || pathname === "/signup") return;
  redirecting = true;
  window.location.assign(`/login?next=${encodeURIComponent(pathname + search)}`);
}

export function Providers({ children }: { children: React.ReactNode }) {
  // Created in state so each browser session gets one client, not one per render.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({ onError: sendToLogin }),
        mutationCache: new MutationCache({ onError: sendToLogin }),
        defaultOptions: {
          queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
        <TooltipProvider>
          {children}
          <Toaster />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
