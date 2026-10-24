import { PAGE_ROUTES } from "./routes";

// `next dev` compiles a route on its first request, which can take many seconds and would make
// the first test to touch each page flaky. Request every page once before any test runs.
export default async function globalSetup() {
  const base = "http://localhost:3040";
  for (const route of PAGE_ROUTES) {
    try {
      await fetch(base + route, { signal: AbortSignal.timeout(120_000) });
    } catch {
      // a failed warm-up is not a test failure; the test that needs the page will say so
    }
  }
}
