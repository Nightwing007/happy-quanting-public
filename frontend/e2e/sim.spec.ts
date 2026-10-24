import type { Page } from "@playwright/test";
import { test, expect, go } from "./fixtures";

type Created = { id: number };

/** Creates a sim through the form: pick a symbol, a bar size, keep the suggested day. */
async function createSimViaForm(page: Page, symbol: string, bar: string, query: string) {
  await go(page, "/sim");
  await page.getByRole("button", { name: "Search symbols" }).filter({ hasText: "Search for a symbol" }).click();
  await page.getByPlaceholder("Search by name or symbol...").fill(query);
  await page.getByRole("option", { name: new RegExp(`^${symbol.replace(".", "\\.")}`) }).first().click();
  await page.getByRole("group", { name: "Bar size" }).getByRole("button", { name: bar, exact: true }).click();
  await page.getByRole("button", { name: "Start simulation" }).click();
  await expect(page).toHaveURL(/\/sim\/\d+/);
  await expect(page.getByRole("status").filter({ hasText: "SIMULATION" })).toBeVisible();
  return Number(new URL(page.url()).pathname.split("/").pop());
}

async function step(page: Page, bars: 1 | 10) {
  const button = page.getByRole("button", { name: `Step ${bars} bar${bars === 1 ? "" : "s"}` });
  await expect(button).toBeEnabled();
  await button.click();
}

/** Runs the sim's own trading routes (the same ones the page uses). */
async function simGet<T>(page: Page, id: number, path: string): Promise<T> {
  const res = await page.context().request.get(`/api/sim/sessions/${id}${path}`);
  expect(res.ok(), `${path}: ${res.status()}`).toBeTruthy();
  return res.json();
}

async function buyInSim(page: Page, symbol: string, quantity: string) {
  await page.getByLabel("Quantity", { exact: true }).fill(quantity);
  await expect(page.getByText("Charges total")).toBeVisible();
  await page.getByRole("button", { name: `Buy ${symbol}`, exact: true }).click();
  await expect(page.locator("[data-sonner-toast]").filter({ hasText: new RegExp(`Bought ${quantity} ${symbol}`) })).toBeVisible();
}

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  while (d.getUTCDay() === 0 || d.getUTCDay() === 6) d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

test.describe("sim", () => {
  test("AAPL on 15-minute bars: create, step, play and pause", async ({ user }) => {
    const { page } = user;
    await createSimViaForm(page, "AAPL", "15m", "Apple");
    await expect(page.getByText(/^0% played/)).toBeVisible();
    await expect(page.getByText("Nothing has been replayed yet")).toBeVisible();

    await step(page, 1);
    await expect(page.getByText("Nothing has been replayed yet")).toHaveCount(0);
    await expect(page.locator("canvas").first()).toBeVisible();
    await expect(page.getByText(/Replayed clock:/)).toBeVisible();
    await expect(page.getByText(/^O .* H .* L .* C /)).toBeVisible();
    await expect(page.getByText(/^0% played/)).toHaveCount(0);

    await step(page, 10);
    await page.getByRole("button", { name: "Play", exact: true }).click();
    await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Pause", exact: true }).click();
    await expect(page.getByRole("button", { name: "Play", exact: true })).toBeVisible();
    await expect(page.getByText(/Paused|Finished/)).toBeVisible();

    await page.getByRole("button", { name: "Reset" }).click();
    await expect(page.getByText(/^0% played/)).toBeVisible();
  });

  test("a sim appears in the list and can be deleted", async ({ user }) => {
    const { page } = user;
    await createSimViaForm(page, "AAPL", "5m", "Apple");
    await go(page, "/sim");
    const card = page.locator("div.rounded-lg.border").filter({ hasText: "AAPL" }).first();
    await expect(card.getByRole("button", { name: "Open" })).toBeVisible();
    await card.getByRole("button", { name: "Delete", exact: true }).click();
    await card.getByRole("button", { name: "Delete for good" }).click();
    await expect(page.getByText(/No simulations yet/)).toBeVisible();
  });

  test("RELIANCE.NS on 1-minute bars: buy, set a target and watch it fire", async ({ user }) => {
    const { page } = user;
    await createSimViaForm(page, "RELIANCE.NS", "1m", "Reliance");
    await step(page, 10);
    await expect(page.getByRole("button", { name: "Buy RELIANCE.NS" })).toBeVisible();
    await buyInSim(page, "RELIANCE.NS", "5");
    const open = page.locator("[data-slot=card]").filter({ hasText: "Open trades" }).last();
    await expect(open.getByRole("row").filter({ hasText: "RELIANCE.NS" })).toBeVisible();

    await open.getByRole("button", { name: "Stop / target" }).click();
    const dialog = page.getByRole("dialog");
    const hint = await dialog.getByText(/^Above .*it takes a profit/).innerText();
    const price = Number(hint.match(/([\d,]+\.\d+)/)![1].replace(/,/g, ""));
    await dialog.getByLabel("Target price").fill((price * 1.0004).toFixed(2));
    await dialog.getByLabel("Stop-loss price").fill((price * 0.5).toFixed(2));
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.locator("[data-sonner-toast]").filter({ hasText: /Saved the stop-loss and target/ })).toBeVisible();

    await page.getByRole("button", { name: "Play", exact: true }).click();
    await expect(page.getByText(/No open trades in this simulation\./)).toBeVisible({ timeout: 60_000 });
    // The close is a filled sell order on the replayed clock.
    const orders = page.locator("[data-slot=card]").filter({ hasText: "Orders" }).last();
    await expect(orders.getByRole("row").filter({ hasText: "sell" }).first()).toContainText("Filled");
  });

  test("exiting a sim trade through the dialog closes it", async ({ user }) => {
    const { page } = user;
    await createSimViaForm(page, "RELIANCE.NS", "1m", "Reliance");
    await step(page, 10);
    await buyInSim(page, "RELIANCE.NS", "3");
    await page.getByRole("row").filter({ hasText: "RELIANCE.NS" }).getByRole("button", { name: "Exit", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Cash you receive")).toBeVisible();
    await dialog.getByRole("button", { name: "Confirm exit" }).click();
    await expect(page.getByText("No open trades in this simulation.")).toBeVisible();
  });

  test("exiting the same sim trade twice never sells twice", async ({ user }) => {
    const { page } = user;
    const id = await createSimViaForm(page, "RELIANCE.NS", "1m", "Reliance");
    await step(page, 10);
    await buyInSim(page, "RELIANCE.NS", "3");
    const portfolio = await simGet<{ trades: { id: number }[] }>(page, id, "/portfolio");
    expect(portfolio.trades).toHaveLength(1);
    const tradeId = portfolio.trades[0].id;

    const exit = () => page.context().request.post(`/api/sim/sessions/${id}/trades/${tradeId}/exit`, { data: {} });
    const first = await exit();
    expect(first.ok()).toBeTruthy();
    const second = await exit();
    // A clean refusal, not a second sale and not a server error.
    expect(second.status(), await second.text()).toBeGreaterThanOrEqual(400);
    expect(second.status()).toBeLessThan(500);

    const orders = await simGet<{ side: string; status: string }[]>(page, id, "/orders");
    expect(orders.filter((o) => o.side === "sell" && o.status === "filled")).toHaveLength(1);
    const after = await simGet<{ trades: unknown[]; holdings: unknown[] }>(page, id, "/portfolio");
    expect(after.trades).toHaveLength(0);
    expect(after.holdings).toHaveLength(0);
  });

  test("a double-clicked Confirm exit sells once", async ({ user }) => {
    const { page } = user;
    const id = await createSimViaForm(page, "RELIANCE.NS", "1m", "Reliance");
    await step(page, 10);
    await buyInSim(page, "RELIANCE.NS", "3");
    await page.getByRole("row").filter({ hasText: "RELIANCE.NS" }).getByRole("button", { name: "Exit", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Confirm exit" }).dblclick();
    await expect(page.getByText("No open trades in this simulation.")).toBeVisible();
    const orders = await simGet<{ side: string; status: string }[]>(page, id, "/orders");
    expect(orders.filter((o) => o.side === "sell" && o.status === "filled")).toHaveLength(1);
  });

  test("a code strategy trades in the sim and writes its log", async ({ user }) => {
    const { page } = user;
    const source = `import hq


class LogsABuy(hq.Strategy):
    name = "Logs a buy"
    description = "Buys once and says so."
    markets = ("india", "international", "crypto")
    interval = "1d"
    warmup_bars = 1
    PARAMETERS = {
        "percent_of_cash": hq.Param("int", 10, min=1, max=100, label="Cash to spend (%)"),
    }

    def on_bar(self, ctx):
        for symbol in ctx.symbols:
            if ctx.position(symbol).quantity == 0:
                ctx.buy(symbol, percent_of_cash=ctx.params["percent_of_cash"])
                ctx.log(f"E2E buying {symbol}")
`;
    const res = await page.context().request.post("/api/sim/sessions", {
      data: {
        symbols: ["BTC-USD"],
        interval: "1d",
        start_date: isoDaysAgo(12),
        end_date: isoDaysAgo(2),
        speed: 200,
        strategy: { kind: "source", source },
      },
    });
    expect(res.ok(), await res.text()).toBeTruthy();
    const { id } = (await res.json()) as Created;
    await go(page, `/sim/${id}`);
    await expect(page.getByRole("heading", { name: "Logs a buy" })).toBeVisible();
    await expect(page.getByText("Your code", { exact: true })).toBeVisible();

    await step(page, 10);
    await expect(page.getByText(/Strategy log \([1-9]\d* lines?\)/)).toBeVisible();
    await page.getByText(/Strategy log/).click();
    await expect(page.locator("pre")).toContainText("E2E buying BTC-USD");
    const orders = page.locator("[data-slot=card]").filter({ hasText: "Orders" }).last();
    await expect(orders.getByRole("row").filter({ hasText: "buy" }).first()).toBeVisible();
  });
});
