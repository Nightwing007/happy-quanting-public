import type { Page } from "@playwright/test";
import { test, expect, go } from "./fixtures";

const PASSES = "Your code passes every check.";

async function editorText(page: Page, text: string, where: "start" | "all") {
  const surface = page.locator(".monaco-editor .view-lines").first();
  await expect(surface).toBeVisible({ timeout: 60_000 });
  await surface.click();
  if (where === "all") await page.keyboard.press("Control+a");
  else await page.keyboard.press("Control+Home");
  await page.keyboard.insertText(text);
}

test.describe("editor", () => {
  test("the starter template validates and shows its summary", async ({ user }) => {
    const { page } = user;
    await go(page, "/create/editor");
    await expect(page.getByRole("heading", { name: "Code editor" })).toBeVisible();
    await expect(page.getByText(PASSES)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText(/Buy and wait/).first()).toBeVisible();
    await expect(page.getByText("Not saved yet")).toBeVisible();
  });

  test("a forbidden import is marked in the editor and listed as a problem", async ({ user }) => {
    const { page } = user;
    await go(page, "/create/editor");
    await expect(page.getByText(PASSES)).toBeVisible({ timeout: 60_000 });
    await editorText(page, "import os\n", "start");
    await page.getByRole("button", { name: "Validate" }).click();

    const alert = page.locator("div[role=alert]").filter({ hasText: /problems? to fix/ });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/Line 1/);
    await expect(alert).toContainText(/os/);
    await expect(page.locator(".monaco-editor .squiggly-error").first()).toBeAttached();
    await expect(page.getByText(PASSES)).toHaveCount(0);

    // Deleting the line fixes it: the problems and the markers go away. Clicking Validate took
    // the focus away, so put the caret back in the editor first.
    await page.locator(".monaco-editor .view-lines").first().click();
    await page.keyboard.press("Control+Home");
    await page.keyboard.press("Shift+ArrowDown");
    await page.keyboard.press("Delete");
    await page.getByRole("button", { name: "Validate" }).click();
    await expect(page.getByText(PASSES)).toBeVisible();
    await expect(alert).toHaveCount(0);
    await expect(page.locator(".monaco-editor .squiggly-error")).toHaveCount(0);
  });

  test("backtest the template on a symbol, then save it to My algorithms", async ({ user }) => {
    const { page } = user;
    await go(page, "/create/editor");
    await expect(page.getByText(PASSES)).toBeVisible({ timeout: 60_000 });

    await page.getByRole("button", { name: "Search symbols" }).filter({ hasText: "Add a symbol" }).click();
    await page.getByPlaceholder("Search by name or symbol...").fill("Reliance");
    await page.getByRole("option", { name: /^RELIANCE\.NS/ }).first().click();
    await expect(page.getByRole("button", { name: "Remove RELIANCE.NS" })).toBeVisible();
    await page.getByRole("button", { name: "Run preview backtest" }).click();
    await expect(page.getByText("What trading cost")).toBeVisible({ timeout: 90_000 });
    await expect(page.getByText("Total return", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Save", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel("Name")).toHaveValue("Buy and wait");
    await dialog.getByLabel("Name").fill("E2E editor algo");
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.locator("[data-sonner-toast]").filter({ hasText: 'Saved "E2E editor algo"' })).toBeVisible();
    await expect(page.getByText('Saved as "E2E editor algo"')).toBeVisible();

    await go(page, "/algos");
    const card = page.locator("[data-slot=card]").filter({ hasText: "E2E editor algo" });
    await expect(card).toContainText("Your own code");
    await card.locator("a", { hasText: "Edit in editor" }).click();
    await expect(page).toHaveURL(/\/create\/editor\?mine=\d+/);
    await expect(page.getByRole("heading", { name: "E2E editor algo" })).toBeVisible();
    await expect(page.getByText(PASSES)).toBeVisible({ timeout: 60_000 });
  });
});
