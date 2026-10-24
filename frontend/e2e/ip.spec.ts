import fs from "node:fs";
import path from "node:path";
import { test, expect, go, signUp, collectApiBodies } from "./fixtures";
import { creatorCode, SECRET_PARAM } from "./creator-code";

// A subscriber must never receive a creator's code or settings from any /api/ response.

const SEED_DIR = path.join(__dirname, "..", "..", "backend", "seed", "algos");

/** Distinctive code lines of the five seeded strategies (descriptions are public, so skipped). */
function seededCodeLines(): string[] {
  const lines = new Set<string>();
  for (const file of fs.readdirSync(SEED_DIR).filter((f) => f.endsWith(".py"))) {
    for (const raw of fs.readFileSync(path.join(SEED_DIR, file), "utf8").split(/\r?\n/)) {
      const line = raw.trim();
      if (line.length >= 25 && (/ctx\./.test(line) || /hq\.Param\(/.test(line))) lines.add(line);
    }
  }
  return [...lines];
}

test.describe("ip", () => {
  test("seeded strategies never leak to a non-owner browsing, subscribing and stopping", async ({ user }) => {
    const { page } = user;
    const lines = seededCodeLines();
    expect(lines.length, "the seed files should yield code lines to look for").toBeGreaterThan(20);
    const bodies = collectApiBodies(page);

    await go(page, "/marketplace");
    const links = page.locator('a[href^="/marketplace/"]').filter({ hasNotText: /subscriptions|earnings/ });
    const hrefs = [...new Set(await links.evaluateAll((els) => els.map((e) => e.getAttribute("href") ?? "")))].filter((h) =>
      /^\/marketplace\/\d+$/.test(h),
    );
    expect(hrefs.length).toBeGreaterThanOrEqual(5);
    for (const href of hrefs) {
      await go(page, href);
      await expect(page.getByText("What stays private")).toBeVisible();
    }
    for (const creator of ["zangoose", "slowking", "shuckle", "sharpedo", "electrode"]) await go(page, `/creators/${creator}`);

    // Subscribe to the crypto strategy and stop it again.
    await go(page, "/marketplace");
    await page.getByRole("link", { name: "Crypto ATR breakout", exact: true }).click();
    await page.getByRole("button", { name: "Subscribe", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Search symbols" }).click();
    await page.getByPlaceholder("Search by name or symbol...").fill("BTC");
    await page.getByRole("option", { name: /^BTC-USD/ }).first().click();
    await dialog.getByLabel(/Capital to give it/).fill("30000");
    await dialog.getByRole("button", { name: "Confirm" }).click();
    await expect(page).toHaveURL(/\/marketplace\/subscriptions/);
    await expect(page.getByText("Running version 1")).toBeVisible();
    await go(page, "/marketplace/subscriptions");
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Stop subscription" }).click();
    await expect(page.getByText(/Stopped|Stopping/).first()).toBeVisible({ timeout: 30_000 });

    // A sim of a listing hides its code, settings and log too.
    const listings = await (await page.context().request.get("/api/marketplace/listings")).json();
    const electrode = listings.find((l: { name: string }) => l.name === "Crypto ATR breakout");
    const sim = await page.context().request.post("/api/sim/sessions", {
      data: {
        symbols: ["BTC-USD"],
        interval: "1h",
        start_date: new Date(Date.now() - 4 * 86_400_000).toISOString().slice(0, 10),
        end_date: new Date(Date.now() - 2 * 86_400_000).toISOString().slice(0, 10),
        speed: 200,
        strategy: { kind: "listing", listing_id: electrode.id },
      },
    });
    expect(sim.ok(), await sim.text()).toBeTruthy();
    const { id } = await sim.json();
    await go(page, `/sim/${id}`);
    await expect(page.getByText("The creator keeps the code and its log private.")).toBeVisible();

    expect(bodies.length).toBeGreaterThan(20);
    for (const { url, body } of bodies) {
      for (const line of lines) expect(body.includes(line), `${url} leaked a seeded source line: ${line}`).toBe(false);
    }
  });

  test("a creator's uploaded code and settings never reach a subscriber (the owner's own view does)", async ({ user, browser }) => {
    const { page } = user; // the creator
    const name = `E2E Secret Holder ${Date.now().toString(36)}`;
    const create = await page.context().request.post("/api/marketplace/listings", {
      data: {
        name,
        tagline: "Secret",
        description: "A strategy whose code stays private.",
        markets: ["crypto"],
        test_symbols: ["BTC-USD"],
        interval: "1d",
        fee_percent: "10",
        source: creatorCode({ name }),
      },
    });
    expect(create.ok(), await create.text()).toBeTruthy();
    const listing = await create.json();
    const publish = await page.context().request.post(`/api/marketplace/listings/${listing.id}/publish`);
    expect(publish.ok(), await publish.text()).toBeTruthy();

    // The owner's /mine view is the one place the code lives.
    const mine = await (await page.context().request.get("/api/marketplace/mine")).text();
    expect(mine).toContain("E2E_SECRET_LINE_4f9a2c");

    const context = await browser.newContext();
    const other = await context.newPage();
    await signUp(other, "e2e_ip");
    const bodies = collectApiBodies(other);
    await go(other, "/marketplace");
    await go(other, `/marketplace/${listing.id}`);
    await expect(other.getByText("What stays private")).toBeVisible();
    await go(other, `/creators/${(await (await page.context().request.get("/api/me")).json()).username}`);
    await other.getByRole("button", { name: "Subscribe", exact: true }).isVisible().catch(() => false);
    await go(other, `/marketplace/${listing.id}`);
    await other.getByRole("button", { name: "Subscribe", exact: true }).click();
    const dialog = other.getByRole("dialog");
    await dialog.getByRole("button", { name: "Search symbols" }).click();
    await other.getByPlaceholder("Search by name or symbol...").fill("BTC");
    await other.getByRole("option", { name: /^BTC-USD/ }).first().click();
    await dialog.getByLabel(/Capital to give it/).fill("10000");
    await dialog.getByRole("button", { name: "Confirm" }).click();
    await expect(other).toHaveURL(/\/marketplace\/subscriptions/);
    await expect(other.getByText("Running version 1")).toBeVisible();

    // Direct probes of the owner-only routes: refused, and nothing leaks in the refusal.
    for (const probe of [
      `/api/marketplace/listings/${listing.id}`,
      `/api/marketplace/mine`,
      `/api/marketplace/listings/${listing.id}/versions`,
      `/api/marketplace/subscriptions`,
    ]) {
      const res = await other.context().request.get(probe);
      bodies.push({ url: `GET ${probe}`, body: await res.text() });
    }

    expect(bodies.length).toBeGreaterThan(5);
    for (const { url, body } of bodies) {
      expect(body.includes("E2E_SECRET_LINE_4f9a2c"), `${url} leaked the code`).toBe(false);
      expect(body.includes(SECRET_PARAM), `${url} leaked the settings`).toBe(false);
    }
    await context.close();
  });
});
