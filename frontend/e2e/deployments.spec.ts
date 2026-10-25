import type { Page } from "@playwright/test";
import { test, expect, go } from "./fixtures";

// Deploying an algorithm to run live on its own paper account: from the lab (tweaked settings, nothing saved),
// from My algorithms, and the hosted demo that has no code entry points. Crypto trades round the clock, so
// BTC-USD is the symbol that works whatever the time.

async function pickSymbol(page: Page, query: string, symbol: string) {
  const dialog = page.getByRole("dialog", { name: /^Deploy / });
  await dialog.getByRole("button", { name: "Search symbols" }).click();
  await page.getByPlaceholder("Search by name or symbol...").fill(query);
  await page.getByRole("option", { name: new RegExp(`^${symbol}`) }).first().click();
  await expect(dialog.getByRole("button", { name: `Remove ${symbol}` })).toBeVisible();
}

test.describe("deployments", () => {
  test("deploy from the lab with tweaked settings, then pause, resume and stop it", async ({ user }) => {
    const { page } = user;
    await go(page, "/deployments");
    await expect(page.getByText("Deploy an algorithm from the lab or My algorithms.")).toBeVisible();

    await go(page, "/algos/lab?algo=rsi_reversion");
    await page.locator("#param-oversold").fill("25"); // not saved anywhere
    await page.getByRole("button", { name: "Deploy", exact: true }).click();

    const dialog = page.getByRole("dialog", { name: /^Deploy / });
    await expect(
      dialog.getByText("Runs live on a separate paper account every new bar during market hours, with real charges. Your manual trades are unaffected."),
    ).toBeVisible();
    await expect(dialog.getByLabel("Name")).toHaveValue("RSI mean reversion");
    // The tweaked setting is what gets deployed.
    await expect(dialog.getByLabel("Settings being deployed")).toContainText("oversold");
    await expect(dialog.getByLabel("Settings being deployed")).toContainText("25");
    await expect(dialog.getByRole("button", { name: "Deploy", exact: true })).toBeDisabled();
    await expect(dialog.getByText(/You have .* available/)).toBeVisible();

    await pickSymbol(page, "bitcoin", "BTC-USD");
    await dialog.getByLabel(/^Capital to give it/).fill("1000");
    await dialog.getByRole("button", { name: "Deploy", exact: true }).click();

    await expect(page).toHaveURL(/\/deployments\/\d+$/);
    const summary = page.getByRole("list", { name: "Summary" });
    await expect(page.getByRole("heading", { name: "RSI mean reversion", level: 1 })).toBeVisible();
    await expect(summary.getByText("Running")).toBeVisible();
    await expect(page.getByRole("log", { name: "Live log" })).toBeVisible();
    await expect(page.getByText(/empty after the server restarts/)).toBeVisible();
    await expect(page.getByText("Open trades", { exact: true })).toBeVisible();
    await expect(page.getByText("Recent orders", { exact: true })).toBeVisible();

    // It is listed, and the dashboard shows it while it runs.
    await go(page, "/deployments");
    const card = page.locator("li").filter({ hasText: "RSI mean reversion" }).filter({ hasText: "BTC-USD" });
    await expect(card).toBeVisible();
    await expect(card).toContainText("Running");
    await go(page, "/");
    await expect(page.getByRole("link", { name: "RSI mean reversion" })).toBeVisible();

    await go(page, "/deployments");
    await page.locator("li").filter({ hasText: "RSI mean reversion" }).getByRole("link", { name: "RSI mean reversion" }).click();
    await expect(page).toHaveURL(/\/deployments\/\d+$/);

    await page.getByRole("button", { name: "Pause", exact: true }).click();
    await expect(summary.getByText("Paused")).toBeVisible();
    await page.getByRole("button", { name: "Resume", exact: true }).click();
    await expect(summary.getByText("Running")).toBeVisible();

    await page.getByRole("button", { name: "Stop", exact: true }).click();
    const confirm = page.getByRole("alertdialog");
    await expect(confirm).toContainText("exited at market");
    await confirm.getByRole("button", { name: "Keep it running" }).click();
    await expect(summary.getByText("Running")).toBeVisible();
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Stop deployment" }).click();
    await expect(summary.getByText("Stopped")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Pause", exact: true })).toHaveCount(0);
  });

  test("deploy a saved algorithm from My algorithms", async ({ user }) => {
    const { page } = user;
    const saved = await page.context().request.post("/api/algos/mine", {
      data: { name: "E2E to deploy", strategy: "sma_crossover", params: { fast_period: 5, slow_period: 20, percent_of_cash: "40" } },
    });
    expect(saved.ok(), await saved.text()).toBeTruthy();

    await go(page, "/algos");
    const card = page.locator("[data-slot=card]").filter({ hasText: "E2E to deploy" });
    await card.getByRole("button", { name: "Deploy", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: /^Deploy / });
    await expect(dialog.getByLabel("Name")).toHaveValue("E2E to deploy");
    await expect(dialog.getByLabel("Settings being deployed")).toContainText("E2E to deploy");
    await pickSymbol(page, "bitcoin", "BTC-USD");
    await dialog.getByLabel(/^Capital to give it/).fill("500");
    await dialog.getByRole("button", { name: "Deploy", exact: true }).click();

    await expect(page).toHaveURL(/\/deployments\/\d+$/);
    await expect(page.getByRole("heading", { name: "E2E to deploy", level: 1 })).toBeVisible();
    await expect(page.getByRole("list", { name: "Summary" }).getByText("Running")).toBeVisible();
  });

  test("the server's refusal shows inside the dialog", async ({ user }) => {
    const { page } = user;
    await go(page, "/algos/lab?algo=rsi_reversion");
    await page.getByRole("button", { name: "Deploy", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: /^Deploy / });
    await pickSymbol(page, "bitcoin", "BTC-USD");
    await dialog.getByLabel(/^Capital to give it/).fill("999999999999");
    await dialog.getByRole("button", { name: "Deploy", exact: true }).click();
    await expect(dialog.locator("[role=alert]")).toBeVisible();
    await expect(page).not.toHaveURL(/\/deployments\//);
  });
});

test.describe("hosted demo", () => {
  // The flag comes from /api/health; answering it here tests the screens without a second backend (the
  // server's own refusals are covered by the backend tests).
  test("code entry points give way to a note, the block editor stays", async ({ user }) => {
    const { page } = user;
    await page.route("**/api/health", async (route) => {
      const res = await route.fetch();
      await route.fulfill({ response: res, json: { ...(await res.json()), hosted_mode: true } });
    });

    await go(page, "/");
    await page.getByRole("button", { name: "HFT menu" }).click();
    const box = page.locator("[data-slot=popover-content]");
    await expect(box.getByRole("link", { name: /^Block editor/ })).toBeVisible();
    await expect(box.getByRole("link", { name: /^Code editor/ })).toHaveCount(0);
    await expect(box.getByRole("link", { name: /^Upload/ })).toHaveCount(0);
    await expect(box.getByText("Code upload is turned off on this hosted demo")).toBeVisible();
    await expect(box.getByRole("link", { name: /^Deployments/ })).toBeVisible();
    await page.keyboard.press("Escape");

    await go(page, "/create/editor");
    await expect(page.getByText("Code upload is turned off on this hosted demo")).toBeVisible();
    await expect(page.getByRole("button", { name: "Validate" })).toHaveCount(0);

    await go(page, "/create/upload");
    await expect(page.getByText("Code upload is turned off on this hosted demo")).toBeVisible();

    await go(page, "/create/blocks");
    await expect(page.getByRole("button", { name: "Make a block" })).toBeVisible();
    await expect(page.getByRole("button", { name: /New code block/ })).toHaveCount(0);
  });
});
