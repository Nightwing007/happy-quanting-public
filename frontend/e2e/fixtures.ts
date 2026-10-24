import { test as base, expect, type Page } from "@playwright/test";

let counter = 0;

/** A username that is unique per run and per call: 3-30 chars of a-z, 0-9, _. */
export function uniqueName(prefix = "e2e"): string {
  counter += 1;
  return `${prefix}_${Date.now().toString(36)}${counter}`;
}

export const PASSWORD = "correct-horse-battery";

export type Account = { username: string; password: string };

/** Signs a new user up over the API; the session cookie lands in the page's context. */
export async function signUp(page: Page, prefix = "e2e"): Promise<Account> {
  let detail = "";
  // A few tries: the dev backend restarts when its files change, which refuses a request or two.
  for (let attempt = 0; attempt < 4; attempt++) {
    const username = uniqueName(prefix);
    try {
      const res = await page.context().request.post("/api/auth/signup", {
        data: { username, password: PASSWORD, display_name: null },
      });
      if (res.ok()) return { username, password: PASSWORD };
      detail = `${res.status()} ${await res.text()}`;
    } catch (e) {
      detail = String(e);
    }
    await page.waitForTimeout(1500);
  }
  throw new Error(`signup failed: ${detail}`);
}

// Console messages that are expected: the app deliberately probes with 401/404.
const ALLOWED_CONSOLE = [/status of 401/, /status of 404/, /Failed to load resource.*(401|404)/];

type Fixtures = {
  /** Page of a freshly signed-up user (cookie set). */
  user: { page: Page; account: Account };
  /** Console errors collected on the page so far. */
  consoleErrors: string[];
};

export const test = base.extend<Fixtures>({
  consoleErrors: async ({ page }, run) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const text = msg.text();
      if (ALLOWED_CONSOLE.some((re) => re.test(text))) return;
      errors.push(text);
    });
    page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
    await run(errors);
  },
  user: async ({ page, consoleErrors }, run) => {
    void consoleErrors;
    const account = await signUp(page);
    await run({ page, account });
  },
});

export { expect };

/**
 * Opens a page and waits until React has hydrated it. Filling a controlled input before
 * hydration is lost when React takes over, so forms must not be touched earlier.
 */
export async function go(page: Page, path: string) {
  await page.goto(path);
  await page.waitForLoadState("networkidle");
}

/** Opens the trade page for a symbol and waits for the order ticket. */
export async function openTrade(page: Page, symbol: string) {
  await go(page, `/trade?symbol=${encodeURIComponent(symbol)}`);
  await expect(page.getByRole("heading", { name: symbol, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: `Buy ${symbol}` })).toBeVisible();
}

/** Buys `quantity` of a symbol through the ticket and returns the toast text. */
export async function buyViaTicket(page: Page, symbol: string, quantity: string): Promise<string> {
  await page.getByLabel("Quantity", { exact: true }).fill(quantity);
  await expect(page.getByText("Charges total")).toBeVisible();
  const buy = page.getByRole("button", { name: `Buy ${symbol}`, exact: true });
  await expect(buy).toBeEnabled();
  await buy.click();
  // A badge toast may land beside the order toast; this helper reports the order's.
  const toast = page.locator("[data-sonner-toast]").filter({ hasNotText: /Badge!|past activity/ }).first();
  await expect(toast).toBeVisible();
  return (await toast.innerText()).trim();
}

/** Collects the body of every /api/ response the page receives (for leak checks). */
export function collectApiBodies(page: Page): { url: string; body: string }[] {
  const seen: { url: string; body: string }[] = [];
  page.on("response", async (res) => {
    if (!new URL(res.url()).pathname.startsWith("/api/")) return;
    try {
      seen.push({ url: `${res.request().method()} ${res.url()}`, body: await res.text() });
    } catch {
      // a redirect or an aborted request has no body to check
    }
  });
  return seen;
}
