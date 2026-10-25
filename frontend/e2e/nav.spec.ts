import { test, expect, go } from "./fixtures";

// The header, its HFT box and the profile menu; the editors' new home under /create; the Trade page without a symbol.

test.describe("navigation", () => {
  test("the top level is Dashboard, Trade, Sim and HFT, with no numbers", async ({ user }) => {
    const { page } = user;
    await go(page, "/");
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Trade" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Sim" })).toBeVisible();
    await expect(nav.getByRole("button", { name: "HFT menu" })).toBeVisible();
    await expect(nav.getByRole("link", { name: /^\d\d/ })).toHaveCount(0);
    for (const gone of ["Algos", "Market", "Create", "Orders", "Payouts", "Settings"]) {
      await expect(nav.getByRole("link", { name: gone, exact: true })).toHaveCount(0);
    }
  });

  test("the HFT box has Algo, Market and Create sections with a line for each entry", async ({ user }) => {
    const { page } = user;
    await go(page, "/");
    await page.getByRole("button", { name: "HFT menu" }).click();
    const box = page.locator("[data-slot=popover-content]");
    for (const section of ["Algo", "Market", "Create"]) {
      await expect(box.getByRole("heading", { name: section, exact: true })).toBeVisible();
    }
    const entries: [string, string][] = [
      ["Gallery", "/algos"],
      ["Lab", "/algos/lab"],
      ["My algorithms", "/algos#mine-heading"],
      ["Backtests", "/algos/backtests"],
      ["Deployments", "/deployments"],
      ["Marketplace", "/marketplace"],
      ["My subscriptions", "/marketplace/subscriptions"],
      ["Code editor", "/create/editor"],
      ["Block editor", "/create/blocks"],
      ["Upload", "/create/upload"],
      ["My listings", "/create"],
    ];
    for (const [name, href] of entries) {
      const link = box.getByRole("link", { name: new RegExp(`^${name}`) });
      await expect(link).toHaveAttribute("href", href);
      await expect(link.locator("span").last()).not.toHaveText("");
    }
    // Earnings are for creators only; a new account has no listing.
    await expect(box.getByRole("link", { name: /^Earnings/ })).toHaveCount(0);

    await box.getByRole("link", { name: /^Code editor/ }).click();
    await expect(page).toHaveURL(/\/create\/editor/);
    await expect(page.getByRole("heading", { name: "Code editor" })).toBeVisible();
  });

  test("Orders, Payouts and Settings live in the profile menu", async ({ user }) => {
    const { page } = user;
    await go(page, "/");
    for (const [name, url] of [
      ["Orders", /\/orders$/],
      ["Payouts", /\/payouts$/],
      ["Settings", /\/settings$/],
    ] as const) {
      await page.getByRole("button", { name: /Account menu/ }).click();
      await page.getByRole("link", { name, exact: true }).click();
      await expect(page).toHaveURL(url);
      await expect(page.getByRole("heading", { name })).toBeVisible();
    }
    await page.getByRole("button", { name: /Account menu/ }).click();
    await expect(page.getByRole("link", { name: "Profile" })).toBeVisible();
    await expect(page.getByRole("link", { name: /^Badges/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  });

  test("the old editor addresses redirect to Create and keep ?mine", async ({ user }) => {
    const { page } = user;
    await go(page, "/create/editor");
    await expect(page).toHaveURL(/\/create\/editor$/);
    await go(page, "/create/blocks?mine=999");
    await expect(page).toHaveURL(/\/create\/blocks\?mine=999$/);
  });

  test("/create is a hub: the editors, upload and my listings", async ({ user }) => {
    const { page } = user;
    await go(page, "/create");
    await expect(page.getByRole("heading", { name: "Create", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: /^Code editor/ })).toHaveAttribute("href", "/create/editor");
    await expect(page.getByRole("link", { name: /^Block editor/ })).toHaveAttribute("href", "/create/blocks");
    await expect(page.getByRole("link", { name: /^Upload/ }).first()).toHaveAttribute("href", "/create/upload");
    await expect(page.getByRole("heading", { name: "My listings", level: 2 })).toBeVisible();
  });
});

test.describe("trade without a symbol", () => {
  test("shows market status, the watchlist, popular symbols and recently viewed", async ({ user }) => {
    const { page } = user;
    await go(page, "/trade");
    await expect(page.getByRole("heading", { name: "Trade", level: 1 })).toBeVisible();

    const status = page.getByRole("region", { name: "Market status" });
    for (const region of ["India", "US", "Crypto", "London", "Hong Kong"]) {
      await expect(status.getByText(region, { exact: true })).toBeVisible();
    }
    // Crypto never closes, and the label comes from the quote itself.
    await expect(status.locator("li", { hasText: "Crypto" })).toContainText(/open/i, { timeout: 30_000 });

    // A new account starts with a default watchlist, priced live.
    const watchlist = page.getByRole("region", { name: "Your watchlist" });
    await expect(watchlist.getByRole("link", { name: /^AAPL/ })).toBeVisible();
    await expect(watchlist.getByRole("link", { name: /^AAPL/ })).toContainText("$", { timeout: 30_000 });

    for (const [group, symbol] of [
      ["India", "RELIANCE.NS"],
      ["US", "AAPL"],
      ["Crypto", "BTC-USD"],
      ["Global", "VOD.L"],
    ]) {
      const tile = page.getByRole("region", { name: `Popular in ${group}` }).getByRole("link", { name: new RegExp(`^${symbol}`) });
      await expect(tile).toHaveAttribute("href", `/trade?symbol=${encodeURIComponent(symbol)}`);
    }

    // Opening a symbol puts it under "Recently viewed" next time.
    await expect(page.getByRole("region", { name: "Recently viewed" })).toHaveCount(0);
    await page.getByRole("region", { name: "Popular in US" }).getByRole("link", { name: /^AAPL/ }).click();
    await expect(page.getByRole("heading", { name: "AAPL", exact: true })).toBeVisible();
    await go(page, "/trade");
    await expect(page.getByRole("region", { name: "Recently viewed" }).getByRole("link", { name: "AAPL" })).toBeVisible();
  });
});
