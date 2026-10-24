import { test, expect, go, openTrade, buyViaTicket } from "./fixtures";

// BTC-USD fills around the clock on the fake provider, so the first buy earns Hoenn's Stone.

test.describe("badges", () => {
  test("a first crypto buy toasts the Stone badge, and the case shows it earned and the rest locked", async ({ user }) => {
    const { page } = user;
    await openTrade(page, "BTC-USD");
    await buyViaTicket(page, "BTC-USD", "0.01");

    const toast = page.locator("[data-sonner-toast]").filter({ hasText: "You earned the Stone Badge!" });
    await expect(toast).toBeVisible({ timeout: 20_000 });
    await expect(toast).toContainText("First crypto trade");

    await go(page, "/badges");
    await page.getByRole("tab", { name: "Hoenn · Crypto" }).click();
    const stone = page.getByTestId("badge-stone");
    await expect(stone.locator("[data-state=earned]")).toBeVisible();
    await expect(stone).toContainText("Earned");
    const knuckle = page.getByTestId("badge-knuckle");
    await expect(knuckle.locator("[data-state=locked]")).toBeVisible();
    await expect(knuckle).toContainText("First stop-loss or target on crypto");
    await expect(page.getByTestId("badge-count")).toContainText(/\d+ of 37 badges/);

    // Hovering shows the name, hint and date.
    await stone.hover();
    await expect(page.locator("[data-slot=tooltip-content]")).toContainText("First crypto trade");

    // Toasted once: the badge is marked seen, so it is no longer new.
    const me = await (await page.context().request.get("/api/badges/me")).json();
    expect(me.new).not.toContain("stone");
  });

  test("the Elite Four tab holds four badges and the Champion, all locked for a new user", async ({ user }) => {
    const { page } = user;
    await go(page, "/badges");
    await page.getByRole("tab", { name: "Elite Four" }).click();
    for (const id of ["debut", "trusted", "consistent", "craftsman", "champion"]) {
      await expect(page.getByTestId(`badge-${id}`).locator("[data-state=locked]")).toBeVisible();
    }
  });

  test("a creator's Elite Four badges show on their listing card and profile", async ({ user }) => {
    const { page } = user;
    const res = await page.context().request.get("/api/marketplace/listings");
    const listings = (await res.json()) as { id: number; name: string; creator: { username: string; badges: string[] } }[];
    const withBadges = listings.find((l) => l.creator.badges.length > 0);
    test.skip(!withBadges, "no seeded creator has earned an Elite Four badge yet");
    const badges = withBadges!.creator.badges;

    await go(page, "/marketplace");
    const card = page.locator("div[data-slot=card]").filter({ hasText: withBadges!.name }).first();
    for (const id of badges) await expect(card.getByTestId(`creator-badge-${id}`)).toBeVisible();

    await go(page, `/creators/${withBadges!.creator.username}`);
    await expect(page.getByRole("heading", { name: "Badges", level: 2 })).toBeVisible();
    await page.getByRole("tab", { name: "Elite Four" }).click();
    await expect(page.getByTestId(`badge-${badges[0]}`).locator("[data-state=earned]")).toBeVisible();
  });

  test("/badges and the user menu fit 400px", async ({ user, consoleErrors }) => {
    const { page } = user;
    await page.setViewportSize({ width: 400, height: 800 });
    await go(page, "/badges");
    for (const tab of ["Kanto · India", "Johto · US", "Hoenn · Crypto", "Sinnoh · Global", "Elite Four"]) {
      await page.getByRole("tab", { name: tab }).click();
      const width = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(width, `${tab} scrolls sideways`).toBeLessThanOrEqual(400);
    }
    await page.getByRole("button", { name: /Account menu/ }).click();
    await expect(page.getByRole("link", { name: /^Badges/ })).toBeVisible();
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(400);
    expect(consoleErrors).toEqual([]);
  });
});
