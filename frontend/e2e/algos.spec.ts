import type { Page } from "@playwright/test";
import { test, expect, go } from "./fixtures";

async function addSymbol(page: Page, query: string, symbol: string) {
  await page.getByRole("button", { name: "Search symbols" }).filter({ hasText: /Add a symbol|Add another/ }).click();
  await page.getByPlaceholder("Search by name or symbol...").fill(query);
  await page.getByRole("option", { name: new RegExp(`^${symbol.replace(".", "\\.")}`) }).first().click();
  await expect(page.getByRole("button", { name: `Remove ${symbol}` })).toBeVisible();
}

test.describe("algos", () => {
  test("the gallery lists the five ready-made algorithms and the editors", async ({ user }) => {
    const { page } = user;
    await go(page, "/algos");
    await expect(page.getByRole("heading", { name: "Algorithms", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Ready-made algorithms" })).toBeVisible();
    for (const name of [
      "SMA crossover",
      "RSI mean reversion",
      "Bollinger band reversion",
      "Donchian breakout",
      "Crypto volatility breakout",
    ]) {
      await expect(page.getByText(name, { exact: true }).first()).toBeVisible();
    }
    await expect(page.locator("a", { hasText: "Open in lab" })).toHaveCount(5);
    await expect(page.locator("a", { hasText: "Block editor" })).toBeVisible();
    await expect(page.locator("a", { hasText: "Code editor" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "My algorithms" })).toBeVisible();
    await expect(page.getByText(/Nothing saved yet/)).toBeVisible();
  });

  test("the lab refuses a settings combination the algorithm cannot use", async ({ user }) => {
    const { page } = user;
    await go(page, "/algos/lab?algo=sma_crossover");
    await expect(page.getByRole("heading", { name: "SMA crossover" })).toBeVisible();
    await addSymbol(page, "Reliance", "RELIANCE.NS");
    await page.locator("#param-fast_period").fill("40"); // above the slow period (30)
    await page.getByRole("button", { name: "Run backtest" }).click();
    await expect(page.locator("[role=alert]").filter({ hasText: /Fast period must be smaller/ })).toBeVisible();
  });

  test("lab: change a setting, backtest, read the results, save, then rerun from My algorithms", async ({ user }) => {
    const { page } = user;
    await go(page, "/algos/lab?algo=sma_crossover");
    await expect(page.getByRole("button", { name: "Run backtest" })).toBeDisabled();
    await expect(page.getByText("Add at least one symbol.")).toBeVisible();

    await page.locator("#param-fast_period").fill("8");
    await addSymbol(page, "Reliance", "RELIANCE.NS");
    await page.getByRole("button", { name: "Run backtest" }).click();

    await expect(page.getByText("What trading cost")).toBeVisible({ timeout: 90_000 });
    await expect(page.getByText("Total return", { exact: true })).toBeVisible();
    await expect(page.getByText("Max drawdown")).toBeVisible();
    await expect(page.getByText(/^Trades \(\d+\)/)).toBeVisible();
    await expect(page.getByText(/Strategy log \(\d+ lines\)/)).toBeVisible();
    await expect(page.getByText(/8\.? ?bars|RELIANCE\.NS/).first()).toBeVisible();
    await expect(page.locator("canvas").first()).toBeVisible();

    await page.getByRole("button", { name: "Save as my algorithm" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    await dialog.getByLabel("Name").fill("E2E fast eight");
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.locator("[data-sonner-toast]").filter({ hasText: 'Saved "E2E fast eight"' })).toBeVisible();

    // My algorithms lists it; opening it restores the saved setting.
    await go(page, "/algos");
    const card = page.locator("[data-slot=card]").filter({ hasText: "E2E fast eight" });
    await expect(card).toContainText("Built on SMA crossover");
    await card.locator("a", { hasText: "Open in lab" }).click();
    await expect(page).toHaveURL(/\/algos\/lab\?mine=\d+/);
    await expect(page.getByRole("heading", { name: "E2E fast eight" })).toBeVisible();
    await expect(page.locator("#param-fast_period")).toHaveValue("8");

    // Rerun with the saved settings.
    await addSymbol(page, "Reliance", "RELIANCE.NS");
    await page.getByRole("button", { name: "Run backtest" }).click();
    await expect(page.getByText("What trading cost")).toBeVisible({ timeout: 90_000 });

    // Both runs are in the history.
    await go(page, "/algos/backtests");
    await expect(page.locator("div.rounded-lg.border").filter({ hasText: "RELIANCE.NS" })).toHaveCount(2);
    await page.locator("div.rounded-lg.border").first().locator("a", { hasText: "Open" }).click();
    await expect(page).toHaveURL(/\/algos\/backtests\/\d+/);
    await expect(page.getByText("What trading cost")).toBeVisible({ timeout: 30_000 });
  });

  test("a saved algorithm can be deleted", async ({ user }) => {
    const { page } = user;
    const res = await page.context().request.post("/api/algos/mine", {
      data: { name: "E2E to delete", strategy: "sma_crossover", params: { fast_period: 5, slow_period: 20, percent_of_cash: "40" } },
    });
    expect(res.ok(), await res.text()).toBeTruthy();
    await go(page, "/algos");
    const card = page.locator("[data-slot=card]").filter({ hasText: "E2E to delete" });
    await card.getByRole("button", { name: "Delete", exact: true }).click();
    await card.getByRole("button", { name: "Delete for good" }).click();
    await expect(page.getByText("E2E to delete")).toHaveCount(0);
  });
});
