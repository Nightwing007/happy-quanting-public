import { test, expect, go, uniqueName, PASSWORD, signUp } from "./fixtures";

test.describe("auth", () => {
  test("signed-out visitors are redirected to the login page", async ({ page }) => {
    await go(page, "/");
    await expect(page).toHaveURL(/\/login\?next=%2F$/);
    await expect(page.getByRole("button", { name: "Log in", exact: true })).toBeVisible();
  });

  test("sign up lands on the dashboard, log out returns to login, log in works again", async ({ page }) => {
    const username = uniqueName("auth");
    await go(page, "/signup");
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Display name (optional)").fill("Auth Tester");
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByLabel("Confirm password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign up" }).click();
    await expect(page).toHaveURL(/\/$/);
    await page.getByRole("button", { name: "Account menu for Auth Tester" }).click();
    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page.getByRole("button", { name: "Log in", exact: true })).toBeVisible();

    // The signup page stays mounted (hidden) after navigating away, so address visible fields only.
    await page.locator("input#username:visible").fill(username);
    await page.locator("input#password:visible").fill(PASSWORD);
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("button", { name: "Account menu for Auth Tester" })).toBeVisible();
  });

  test("mismatched passwords are explained on the signup form", async ({ page }) => {
    await go(page, "/signup");
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByLabel("Confirm password").fill("something-else");
    await expect(page.locator("form [role=alert]")).toHaveText("The two passwords don't match.");
    await expect(page.getByRole("button", { name: "Sign up" })).toBeDisabled();
  });

  test("a wrong password shows a sentence, not a code", async ({ page }) => {
    const account = await signUp(page);
    await page.context().clearCookies();
    await go(page, "/login");
    await page.getByLabel("Username").fill(account.username);
    await page.getByLabel("Password").fill("not-the-password");
    await page.getByRole("button", { name: "Log in" }).click();
    const alert = page.locator("form [role=alert]");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/\w+ \w+ \w+/); // a sentence
    await expect(alert).not.toContainText(/^[a-z_]+$/); // not a bare error code
    await expect(page).toHaveURL(/\/login/);
  });

  test("two users are isolated", async ({ browser }) => {
    const ctxA = await browser.newContext();
    const ctxB = await browser.newContext();
    const a = await ctxA.newPage();
    const b = await ctxB.newPage();
    await signUp(a, "iso_a");
    await signUp(b, "iso_b");

    // A places an order; B's order list must stay empty.
    const placed = await a.context().request.post("/api/orders", {
      data: { symbol: "AAPL", side: "buy", type: "market", quantity: "1" },
    });
    expect(placed.ok()).toBeTruthy();
    const ordersA = await (await a.context().request.get("/api/orders")).json();
    const ordersB = await (await b.context().request.get("/api/orders")).json();
    expect(JSON.stringify(ordersA)).toContain("AAPL");
    expect(JSON.stringify(ordersB)).not.toContain("AAPL");

    // A creates a saved algo; B cannot open it by id.
    const algo = await a.context().request.post("/api/algos/mine", {
      data: { name: "iso algo", strategy: "sma_crossover", params: {} },
    });
    if (algo.ok()) {
      const { id } = await algo.json();
      const other = await b.context().request.get(`/api/algos/mine/${id}`);
      expect(other.status()).toBe(404);
    }

    await a.goto("/profile");
    await b.goto("/profile");
    await expect(a.locator("body")).not.toContainText("iso_b_");
    await expect(b.locator("body")).not.toContainText("iso_a_");
    await ctxA.close();
    await ctxB.close();
  });
});
