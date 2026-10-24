import { test, expect, go, openTrade, buyViaTicket } from "./fixtures";

test.describe("dashboard", () => {
  test("a new account shows its cards and every empty state", async ({ user }) => {
    const { page } = user;
    await go(page, "/");
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    for (const title of ["Total value", "Cash", "Margin used", "Available cash", "Invested (cost)", "Profit / loss"]) {
      await expect(page.getByText(title, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText(/Started with/)).toBeVisible();
    await expect(page.getByText("Getting started")).toBeVisible();
    await expect(page.getByText(/You don't hold anything yet/)).toBeVisible();
    await expect(page.getByText(/No open trades\. Every buy or short/)).toBeVisible();
    await expect(page.getByText(/You haven't paid any charges yet/)).toBeVisible();
  });

  test("the watchlist lists symbols and one can be removed", async ({ user }) => {
    const { page } = user;
    await go(page, "/");
    const first = page.getByRole("button", { name: /^Remove .* from watchlist$/ }).first();
    await expect(first).toBeVisible();
    const label = (await first.getAttribute("aria-label")) ?? "";
    const symbol = label.replace("Remove ", "").replace(" from watchlist", "");
    await first.click();
    await expect(page.getByRole("button", { name: `Remove ${symbol} from watchlist` })).toHaveCount(0);
  });

  test("after a buy the holdings, open trades and costs card fill in", async ({ user }) => {
    const { page } = user;
    await openTrade(page, "BTC-USD");
    await buyViaTicket(page, "BTC-USD", "0.02");
    await go(page, "/");

    const holdings = page.locator("[data-slot=card]").filter({ hasText: "Holdings" }).last();
    await expect(holdings.getByRole("row").filter({ hasText: "BTC-USD" })).toContainText("Long");
    await expect(holdings.getByRole("row").filter({ hasText: "BTC-USD" })).toContainText("0.02");

    const trades = page.locator("[data-slot=card]").filter({ hasText: "Open trades" }).last();
    const tradeRow = trades.getByRole("row").filter({ hasText: "BTC-USD" });
    await expect(tradeRow).toBeVisible();
    await expect(tradeRow.getByRole("button", { name: "Exit", exact: true })).toBeVisible();
    await expect(tradeRow.getByRole("button", { name: "Stop / target" })).toBeVisible();

    const costs = page.locator("[data-slot=card]").filter({ hasText: "Trading costs" }).last();
    await expect(costs.getByText("Total paid")).toBeVisible();
    await expect(costs.getByText(/You haven't paid any charges yet/)).toHaveCount(0);
    await expect(page.getByText("Getting started")).toHaveCount(0);
  });

  test("exiting from the dashboard empties the open trades again", async ({ user }) => {
    const { page } = user;
    await openTrade(page, "BTC-USD");
    await buyViaTicket(page, "BTC-USD", "0.01");
    await go(page, "/");
    await page.getByRole("button", { name: "Exit", exact: true }).first().click();
    await page.getByRole("dialog").getByRole("button", { name: "Confirm exit" }).click();
    await expect(page.getByText(/No open trades\. Every buy or short/)).toBeVisible();
    // The exit is a second charge: the costs card keeps its total.
    await expect(page.getByText("Total paid")).toBeVisible();
  });
});
