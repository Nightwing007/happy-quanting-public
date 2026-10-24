import type { Page } from "@playwright/test";
import { test, expect, go } from "./fixtures";
import { PAGE_ROUTES } from "./routes";

const WIDTH = 400;
const SIGNED_OUT = new Set(["/login", "/signup"]);

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  while (d.getUTCDay() === 0 || d.getUTCDay() === 6) d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

/** Real ids for the dynamic routes, so the pages are checked with data in them, not an error state. */
async function realRoutes(page: Page): Promise<string[]> {
  const api = page.context().request;
  const sim = await (
    await api.post("/api/sim/sessions", {
      data: { symbols: ["RELIANCE.NS"], interval: "1m", start_date: isoDaysAgo(1), end_date: isoDaysAgo(1), speed: 60 },
    })
  ).json();
  await api.post(`/api/sim/sessions/${sim.id}/control`, { data: { action: "step", steps: 5 } });

  const bt = await (
    await api.post("/api/backtests", {
      data: {
        strategy: "sma_crossover",
        params: { fast_period: 10, slow_period: 30, percent_of_cash: "50" },
        symbols: ["RELIANCE.NS"],
        interval: "1d",
        start_date: isoDaysAgo(300),
        end_date: isoDaysAgo(1),
      },
    })
  ).json();
  for (let i = 0; i < 60; i++) {
    const state = await (await api.get(`/api/backtests/${bt.id}`)).json();
    if (state.status === "done" || state.status === "failed") break;
    await page.waitForTimeout(1000);
  }
  const listings = await (await api.get("/api/marketplace/listings")).json();
  return PAGE_ROUTES.filter((r) => !SIGNED_OUT.has(r)).map((r) =>
    r === "/sim/1"
      ? `/sim/${sim.id}`
      : r === "/algos/backtests/1"
        ? `/algos/backtests/${bt.id}`
        : r === "/marketplace/1"
          ? `/marketplace/${listings[0].id}`
          : r === "/creators/someone"
            ? "/creators/electrode"
            : r,
  );
}

async function checkPage(page: Page, route: string, errors: string[]) {
  await page.setViewportSize({ width: WIDTH, height: 800 });
  const before = errors.length;
  await go(page, route);
  await page.waitForTimeout(500); // late charts and tables settle
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth, `${route} scrolls sideways at ${WIDTH}px (scrollWidth ${scrollWidth})`).toBeLessThanOrEqual(WIDTH);
  expect(errors.slice(before), `${route} logged console errors`).toEqual([]);
}

test.describe("layout", () => {
  test("every signed-in page fits 400px and logs no console errors", async ({ user, consoleErrors }) => {
    test.setTimeout(300_000);
    const { page } = user;
    const routes = await realRoutes(page);
    expect(routes.length).toBeGreaterThanOrEqual(20);
    for (const route of routes) await checkPage(page, route, consoleErrors);
  });

  test("the login and signup pages fit 400px", async ({ page, consoleErrors }) => {
    for (const route of SIGNED_OUT) await checkPage(page, route, consoleErrors);
  });

  test("the pages with a trade, a chart and tables still fit 400px", async ({ user, consoleErrors }) => {
    const { page } = user;
    // A BTC position gives the dashboard, trade and orders pages real rows to lay out.
    const placed = await page.context().request.post("/api/orders", {
      data: { symbol: "BTC-USD", side: "buy", type: "market", quantity: "0.01" },
    });
    expect(placed.ok()).toBeTruthy();
    for (const route of ["/", "/trade?symbol=BTC-USD", "/orders", "/payouts"]) await checkPage(page, route, consoleErrors);
  });
});
