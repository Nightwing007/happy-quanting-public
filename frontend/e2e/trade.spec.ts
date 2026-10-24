import { test, expect, go, openTrade, buyViaTicket } from "./fixtures";

// BTC-USD trades around the clock, so it is the symbol for tests that need a fill. AAPL follows
// the real calendar, so its tests accept either outcome but demand that the UI is consistent.

test.describe("trade", () => {
  test("Ctrl+K searches and opens the AAPL chart with its quote", async ({ user }) => {
    const { page } = user;
    await go(page, "/");
    await page.keyboard.press("Control+k");
    await page.getByPlaceholder("Search by name or symbol...").fill("Apple");
    await page.getByRole("option", { name: /AAPL/ }).first().click();
    await expect(page).toHaveURL(/\/trade\?symbol=AAPL/);
    await expect(page.getByRole("heading", { name: "AAPL", exact: true })).toBeVisible();
    await expect(page.getByText("Apple Inc.").first()).toBeVisible();
    await expect(page.locator("canvas").first()).toBeVisible();
    await expect(page.getByText(/C \$/).first()).toBeVisible(); // OHLC strip
  });

  test("timeframe and indicator toggles change the chart controls", async ({ user }) => {
    const { page } = user;
    await openTrade(page, "AAPL");
    const tf = page.getByRole("group", { name: "Timeframe" });
    await expect(tf.getByRole("button", { name: "6M" })).toHaveAttribute("aria-pressed", "true");
    await tf.getByRole("button", { name: "1M" }).click();
    await expect(tf.getByRole("button", { name: "1M" })).toHaveAttribute("aria-pressed", "true");
    await expect(tf.getByRole("button", { name: "6M" })).toHaveAttribute("aria-pressed", "false");
    await expect(page.locator("canvas").first()).toBeVisible();

    const ind = page.getByRole("group", { name: "Indicators" });
    await expect(ind.getByRole("button", { name: "SMA 20" })).toHaveAttribute("aria-pressed", "true");
    await ind.getByRole("button", { name: "RSI 14" }).click();
    await expect(ind.getByRole("button", { name: "RSI 14" })).toHaveAttribute("aria-pressed", "true");
    await ind.getByRole("button", { name: "SMA 20" }).click();
    await expect(ind.getByRole("button", { name: "SMA 20" })).toHaveAttribute("aria-pressed", "false");
  });

  test("the order preview lists every charge before buying", async ({ user }) => {
    const { page } = user;
    await openTrade(page, "AAPL");
    await page.getByLabel("Quantity", { exact: true }).fill("3");
    await expect(page.getByText("Trade value").first()).toBeVisible();
    await expect(page.getByText("Charges total")).toBeVisible();
    await expect(page.getByText(/^Buys 3 shares/)).toBeVisible();
    await expect(page.getByText(/Cash you pay/)).toBeVisible();
    await expect(page.getByText(/via .* · /)).toBeVisible(); // broker and market
  });

  test("buying AAPL fills or waits, and the orders table agrees", async ({ user }) => {
    const { page } = user;
    await openTrade(page, "AAPL");
    const closedNotice = page.getByText("The market is closed. Your order will wait");
    const toast = await buyViaTicket(page, "AAPL", "2");
    const closed = await closedNotice.isVisible();
    const orders = page.locator("[data-slot=card]").filter({ hasText: "Your orders for AAPL" });
    if (/Bought/.test(toast)) {
      expect(closed).toBe(false);
      await expect(orders.getByText("Filled").first()).toBeVisible();
      await expect(page.getByRole("button", { name: "Exit", exact: true }).first()).toBeVisible();
    } else {
      expect(toast).toMatch(/waiting/i);
      await expect(orders.getByText("Waiting").first()).toBeVisible();
      await expect(orders.getByRole("button", { name: "Cancel" }).first()).toBeVisible();
    }
  });

  test("a resting limit order shows on the orders page and can be cancelled", async ({ user }) => {
    const { page } = user;
    await openTrade(page, "BTC-USD");
    await page.getByRole("button", { name: "Limit", exact: true }).click();
    await page.getByLabel("Quantity", { exact: true }).fill("0.01");
    await page.getByLabel(/Limit price/).fill("1000");
    await expect(page.getByText("Charges total")).toBeVisible();
    await page.getByRole("button", { name: "Buy BTC-USD (limit)" }).click();
    await expect(page.locator("[data-sonner-toast]").first()).toContainText(/Limit order placed/);

    await go(page, "/orders");
    const row = page.getByRole("row").filter({ hasText: "BTC-USD" });
    await expect(row.getByText("Waiting")).toBeVisible();
    await row.getByRole("button", { name: "Cancel" }).click();
    await expect(row.getByText("Cancelled")).toBeVisible();
    await expect(row.getByRole("button", { name: "Cancel" })).toHaveCount(0);
  });

  test("a filled BTC buy can be exited through the dialog with a payout preview", async ({ user }) => {
    const { page } = user;
    await openTrade(page, "BTC-USD");
    const toast = await buyViaTicket(page, "BTC-USD", "0.01");
    expect(toast).toMatch(/Bought 0\.01 BTC-USD/);
    const trades = page.getByRole("row").filter({ hasText: "Long" });
    await expect(trades).toHaveCount(1);
    await trades.getByRole("button", { name: "Exit", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Exit BTC-USD")).toBeVisible();
    await expect(dialog.getByText("Cash you receive")).toBeVisible();
    await expect(dialog.getByText("Realized P&L")).toBeVisible();
    await dialog.getByRole("button", { name: "Confirm exit" }).click();
    await expect(page.locator("[data-sonner-toast]").filter({ hasText: /Sold 0\.01 BTC-USD/ })).toBeVisible();
    await expect(page.getByText("No open trades in BTC-USD.")).toBeVisible();
  });

  test("the stop / target dialog rejects wrong-side prices and saves right-side ones", async ({ user }) => {
    const { page } = user;
    await openTrade(page, "BTC-USD");
    await buyViaTicket(page, "BTC-USD", "0.01");
    await page.getByRole("button", { name: "Stop / target" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Stop-loss and target for BTC-USD")).toBeVisible();

    // A long's stop belongs below the price and its target above; swap them on purpose.
    await dialog.getByLabel("Stop-loss price").fill("90000");
    await dialog.getByLabel("Target price").fill("1000");
    await expect(dialog.locator("p[role=alert]")).toHaveCount(2);
    await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();

    await dialog.getByLabel("Stop-loss price").fill("40000");
    await dialog.getByLabel("Target price").fill("90000");
    await expect(dialog.getByText(/If the stop-loss fires/)).toBeVisible();
    await expect(dialog.getByText(/If the target fires/)).toBeVisible();
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.locator("[data-sonner-toast]").filter({ hasText: /Saved the stop-loss and target/ })).toBeVisible();
    const row = page.getByRole("row").filter({ hasText: "Long" });
    await expect(row).toContainText("40,000");
    await expect(row).toContainText("90,000");
  });
});
