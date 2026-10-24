import { test, expect, go, openTrade } from "./fixtures";

test.describe("glossary", () => {
  test("hovering SMA 20 on the chart explains it", async ({ user }) => {
    const { page } = user;
    await openTrade(page, "AAPL");
    const ind = page.getByRole("group", { name: "Indicators" });
    await ind.getByText("SMA 20", { exact: true }).hover();
    const tip = page.locator("[data-slot=tooltip-content]");
    await expect(tip).toContainText("average");
    await expect(tip).toContainText("isn't a score");
  });

  test("hovering Sharpe ratio on algo results shows the term and a rule of thumb", async ({ user }) => {
    const { page } = user;
    await go(page, "/algos/lab?algo=sma_crossover");
    await page.getByRole("button", { name: "Search symbols" }).filter({ hasText: /Add a symbol|Add another/ }).click();
    await page.getByPlaceholder("Search by name or symbol...").fill("Reliance");
    await page.getByRole("option", { name: /^RELIANCE\.NS/ }).first().click();
    await page.getByRole("button", { name: "Run backtest" }).click();
    await expect(page.getByText("What trading cost")).toBeVisible({ timeout: 90_000 });

    await page.getByText("Sharpe ratio", { exact: true }).hover();
    const tip = page.locator("[data-slot=tooltip-content]");
    await expect(tip).toContainText("Sharpe ratio");
    await expect(tip).toContainText("above 1");
  });
});
