import type { Page } from "@playwright/test";
import { test, expect, go } from "./fixtures";

async function loadRsiTemplate(page: Page) {
  await go(page, "/algos/blocks");
  await page.getByRole("button", { name: "RSI dip-buyer" }).first().click();
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  await expect(page.getByText("No problems.")).toBeVisible({ timeout: 30_000 });
}

test.describe("blocks", () => {
  test("the RSI template loads with six blocks, three connections and no problems", async ({ user }) => {
    const { page } = user;
    await loadRsiTemplate(page);
    await expect(page.locator(".react-flow__edge")).toHaveCount(3);
    await expect(page.getByText("Not saved yet")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
  });

  test("removing a connection shows a problem and blocks saving", async ({ user }) => {
    const { page } = user;
    await loadRsiTemplate(page);
    await page.locator(".react-flow__edge").first().dispatchEvent("click");
    await page.getByRole("button", { name: "Delete selected" }).click();
    await expect(page.locator(".react-flow__edge")).toHaveCount(2);

    const problems = page.locator("div[role=alert]").filter({ hasText: /problems? to fix/ });
    await expect(problems).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("[data-problem]").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
    await expect(page.getByText("Available once your blocks have no problems.")).toBeVisible();

    // Clicking a problem selects the block it names.
    await problems.getByRole("button").first().click();
  });

  test("an invalid connection is refused", async ({ user }) => {
    const { page } = user;
    await loadRsiTemplate(page);
    // A signal output cannot feed a risk block's trigger input.
    const from = page.locator('.react-flow__node[data-id="rsi_above_1"] .react-flow__handle.source').first();
    const to = page.locator('.react-flow__node[data-id="stop_loss_1"] .react-flow__handle.target').first();
    const a = (await from.boundingBox())!;
    const b = (await to.boundingBox())!;
    await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
    await page.mouse.down();
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 });
    await page.mouse.up();
    await expect(page.locator("[data-sonner-toast]").filter({ hasText: "Those can't connect" })).toBeVisible();
    await expect(page.locator(".react-flow__edge")).toHaveCount(3);
    await expect(page.getByText("No problems.")).toBeVisible();
  });

  test("View code shows the Python the blocks compile to", async ({ user }) => {
    const { page } = user;
    await loadRsiTemplate(page);
    await expect(page.getByText("The code appears once")).toHaveCount(0);
    await page.getByRole("button", { name: "View code" }).click();
    await expect(page.locator(".monaco-editor .view-lines").first()).toContainText("import hq", { timeout: 60_000 });
  });

  test("save the blocks, then reopen them from My algorithms", async ({ user }) => {
    const { page } = user;
    await loadRsiTemplate(page);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name").fill("E2E blocks algo");
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.locator("[data-sonner-toast]").filter({ hasText: 'Saved "E2E blocks algo"' })).toBeVisible();
    await expect(page.getByText('Saved as "E2E blocks algo"')).toBeVisible();

    await go(page, "/algos");
    const card = page.locator("[data-slot=card]").filter({ hasText: "E2E blocks algo" });
    await expect(card).toContainText("Built with blocks");
    await card.locator("a", { hasText: "Edit in block editor" }).click();
    await expect(page).toHaveURL(/\/algos\/blocks\?mine=\d+/);
    await expect(page.getByRole("heading", { name: "E2E blocks algo" })).toBeVisible();
    await expect(page.locator(".react-flow__node")).toHaveCount(6);
    await expect(page.getByText('Saved as "E2E blocks algo"')).toBeVisible();
  });
});
