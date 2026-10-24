import type { Browser, Page } from "@playwright/test";
import { test, expect, go, signUp } from "./fixtures";
import { creatorCode, SECRET_V2_LINE } from "./creator-code";

const SEEDED = [
  { creator: "Zangoose", listing: "Hourly momentum breakout" },
  { creator: "Slowking", listing: "Weekly trend follower" },
  { creator: "Shuckle", listing: "Uptrend dip buyer" },
  { creator: "Sharpedo", listing: "Oversold ambush" },
  { creator: "Electrode", listing: "Crypto ATR breakout" },
];

/** Opens a listing card from the marketplace by its name. */
async function openListing(page: Page, name: string) {
  await go(page, "/marketplace");
  await page.getByRole("link", { name, exact: true }).click();
  await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();
}

async function subscribe(page: Page, symbol: string, query: string, capital: string) {
  await page.getByRole("button", { name: "Subscribe", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Search symbols" }).click();
  await page.getByPlaceholder("Search by name or symbol...").fill(query);
  await page.getByRole("option", { name: new RegExp(`^${symbol}`) }).first().click();
  await expect(dialog.getByRole("button", { name: `Remove ${symbol}` })).toBeVisible();
  await dialog.getByLabel(/Capital to give it/).fill(capital);
  await dialog.getByRole("button", { name: "Confirm" }).click();
  await expect(page).toHaveURL(/\/marketplace\/subscriptions/);
}

/** Uploads a strategy through /create/upload and publishes it. Returns the listing id. */
async function publishListing(page: Page, name: string, fixFirst: boolean) {
  await go(page, "/create/upload");
  const code = page.getByLabel("Strategy code");
  const validate = page.getByRole("button", { name: "Validate" });
  if (fixFirst) {
    await code.fill(creatorCode({ name, bad: true }));
    await validate.click();
    const problems = page.locator("div[role=alert]").filter({ hasText: /problems? to fix/ });
    await expect(problems).toBeVisible({ timeout: 60_000 });
    await expect(problems).toContainText("Line 1");
    await expect(page.getByRole("button", { name: "Create and publish" })).toBeDisabled();
  }
  await code.fill(creatorCode({ name }));
  await validate.click();
  await expect(page.getByText("Your code passes every check.")).toBeVisible({ timeout: 60_000 });

  await page.getByLabel("Tagline").fill("Buys bitcoin once.");
  await page.getByRole("button", { name: "Crypto", exact: true }).first().isVisible();
  // Test symbols: the symbol picker of stage 3 (the second "Add a symbol" button on the page).
  await page.getByRole("button", { name: "Search symbols" }).filter({ hasText: "Add a symbol" }).last().click();
  await page.getByPlaceholder("Search by name or symbol...").fill("BTC");
  await page.getByRole("option", { name: /^BTC-USD/ }).first().click();
  await page.getByRole("button", { name: "Create and publish" }).click();
  await expect(page).toHaveURL(/\/marketplace\/\d+$/, { timeout: 60_000 });
  return Number(new URL(page.url()).pathname.split("/").pop());
}

async function otherUser(browser: Browser, prefix: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signUp(page, prefix);
  return { context, page };
}

test.describe("marketplace", () => {
  test("the five seeded creators and their listings are shown, and the market filter narrows them", async ({ user }) => {
    const { page } = user;
    await go(page, "/marketplace");
    for (const s of SEEDED) {
      await expect(page.getByRole("link", { name: s.listing, exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: s.creator, exact: true }).first()).toBeVisible();
    }
    await page.getByRole("group", { name: "Market" }).getByRole("button", { name: "Crypto" }).click();
    await expect(page.getByRole("link", { name: "Crypto ATR breakout", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Weekly trend follower", exact: true })).toHaveCount(0);
  });

  test("a creator page lists their listing", async ({ user }) => {
    const { page } = user;
    await go(page, "/creators/electrode");
    await expect(page.getByRole("heading", { name: "Electrode", level: 1 })).toBeVisible();
    await expect(page.getByText("@electrode")).toBeVisible();
    await expect(page.getByRole("link", { name: "Crypto ATR breakout", exact: true })).toBeVisible();
  });

  test("a listing shows performance and the private-code notice, never the code", async ({ user }) => {
    const { page } = user;
    await openListing(page, "Crypto ATR breakout");
    await expect(page.getByText("What stays private")).toBeVisible();
    await expect(page.getByText(/code and settings are never shown/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "How it has performed" })).toBeVisible();
    await expect(page.getByText(/Crypto/).first()).toBeVisible();
    await expect(page.getByText(/Fee|keep|profit/).first()).toBeVisible();
    await expect(page.locator("pre, .monaco-editor")).toHaveCount(0);
  });

  test("subscribe to a listing, see it under My subscriptions, then stop it", async ({ user }) => {
    const { page } = user;
    await openListing(page, "Crypto ATR breakout");
    await subscribe(page, "BTC-USD", "BTC", "50000");

    // The marketplace page stays mounted (hidden) behind this one, so count visible cards only.
    const card = page.locator("[data-slot=card]").filter({ hasText: "Crypto ATR breakout" }).filter({ visible: true });
    await expect(card).toBeVisible();
    await expect(card.getByText("Running", { exact: true })).toBeVisible();
    await expect(card).toContainText("BTC-USD");
    await expect(card).toContainText("Running version 1");
    await expect(card).toContainText("Electrode");

    await card.getByRole("button", { name: "Stop", exact: true }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Stop subscription" }).click();
    await expect(card.getByText(/Stopped|Stopping/).first()).toBeVisible({ timeout: 30_000 });
    await expect(card.getByRole("button", { name: "Stop", exact: true })).toHaveCount(0);
  });

  test("subscribing needs a symbol and capital", async ({ user }) => {
    const { page } = user;
    await openListing(page, "Crypto ATR breakout");
    await page.getByRole("button", { name: "Subscribe", exact: true }).click();
    await expect(page.getByRole("dialog").getByRole("button", { name: "Confirm" })).toBeDisabled();
  });

  test("an empty My subscriptions page invites browsing", async ({ user }) => {
    const { page } = user;
    await go(page, "/marketplace/subscriptions");
    await expect(page.getByText(/You aren't subscribed to anything yet/)).toBeVisible();
  });

  test("creator flow: upload with problems, fix, publish, then a new version reaches a subscriber", async ({ user, browser }) => {
    const { page } = user;
    const name = `E2E Bitcoin Holder ${Date.now().toString(36)}`;
    const listingId = await publishListing(page, name, true);

    // The creator sees their own listing in My listings and cannot subscribe to it.
    await expect(page.getByText(/your own listing/)).toBeVisible();
    await go(page, "/create");
    const mine = page.locator("[data-slot=card]").filter({ hasText: name });
    await expect(mine).toContainText("Published");
    await expect(mine.getByText("Version", { exact: true })).toBeVisible();

    // Someone else finds it and subscribes to version 1.
    const sub = await otherUser(browser, "e2e_sub");
    await openListing(sub.page, name);
    await subscribe(sub.page, "BTC-USD", "BTC", "20000");
    await expect(sub.page.getByText("Running version 1.")).toBeVisible();
    await expect(sub.page.getByText(/Version 2 available/)).toHaveCount(0);

    // The creator uploads version 2.
    await go(page, `/create/upload?listing=${listingId}`);
    await expect(page.getByRole("heading", { name: `New version of ${name}` })).toBeVisible();
    await page.getByLabel("Strategy code").fill(creatorCode({ name, extra: SECRET_V2_LINE }));
    await page.getByRole("button", { name: "Validate" }).click();
    await expect(page.getByText("Your code passes every check.")).toBeVisible({ timeout: 60_000 });
    const publishV2 = page.getByRole("button", { name: "Publish version 2" });
    await expect(publishV2).toBeDisabled(); // a changelog is required
    await page.getByLabel(/Changelog/).fill("Now also writes a marker line.");
    await publishV2.click();
    await expect(page).toHaveURL(new RegExp(`/marketplace/${listingId}$`), { timeout: 60_000 });

    // The subscriber is offered the upgrade and keeps running version 1 until they accept.
    await go(sub.page, "/marketplace/subscriptions");
    const card = sub.page.locator("[data-slot=card]").filter({ hasText: name });
    await expect(card.getByText("Version 2 available")).toBeVisible();
    await expect(card.getByText("Now also writes a marker line.")).toBeVisible();
    await expect(card).toContainText("Running version 1.");
    await card.getByRole("button", { name: "Upgrade", exact: true }).click();
    await sub.page.getByRole("alertdialog").getByRole("button", { name: "Upgrade", exact: true }).click();
    await expect(card).toContainText("Running version 2.", { timeout: 30_000 });
    await expect(card.getByText("Version 2 available")).toHaveCount(0);
    await sub.context.close();
  });
});
