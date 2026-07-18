import { expect, test } from "@playwright/test";

test("StrictMode development remount still loads Home", async ({ page }) => {
  await page.route("**/api/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        counts: {},
        session: { watcher_state: "stopped", overlay_state: "stopped" },
        recent: [],
      },
    });
  });

  await page.goto("/assets/");

  await expect(page.getByRole("heading", { level: 1, name: "Home" })).toBeVisible();
  await expect(page.locator("#home-live-status")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Loading" })).toHaveCount(0);
});
