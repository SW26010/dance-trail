import { expect, test } from "@playwright/test";

test("StrictMode development remount still loads Home", async ({ page }) => {
  await page.route("**/api/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        database_path: "C:/tmp/dancing-log.sqlite3",
        database_exists: true,
        counts: {},
        recent: [],
        current_live: null,
        config_warnings: [],
        startup_warnings: [],
        session: {
          session_state: "idle",
          watcher_running: false,
          overlay_running: false,
          watcher_state: "stopped",
          overlay_state: "stopped",
          last_error: null,
          last_watcher_stats: null,
        },
      },
    });
  });

  await page.goto("/assets/");

  await expect(page.getByRole("heading", { level: 1, name: "Home" })).toBeVisible();
  await expect(page.locator("#home-live-status")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Loading" })).toHaveCount(0);
});
