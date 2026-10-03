import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        database_path: "C:/tmp/dance-trail.sqlite3",
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
});

test("StrictMode development remount still loads Home", async ({ page }) => {
  await expect(page.getByRole("heading", { level: 1, name: "Home" })).toBeVisible();
  await expect(page.locator("#home-live-status")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Loading" })).toHaveCount(0);
});

test("Home exit can be cancelled, retried, and disables controls after acceptance", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/app/exit", async (route) => {
    requests += 1;
    expect(route.request().method()).toBe("POST");
    await route.fulfill({
      status: requests === 1 ? 503 : 202,
      json: requests === 1 ? { error: "Exit unavailable" } : { status: "exiting" },
    });
  });
  const exit = page.getByRole("button", { name: "Exit application", exact: true });
  await exit.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("stop the watcher, overlay, and Web UI service");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  expect(requests).toBe(0);
  await expect(exit).toBeFocused();
  await exit.click();
  await dialog.getByRole("button", { name: "Exit application", exact: true }).click();
  await expect(dialog).toContainText("Exit unavailable");
  await expect(dialog.getByRole("button", { name: "Exit application", exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: "Exit application", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("Exit requested. You can close this tab.", { exact: false })).toBeVisible();
  for (const name of ["Refresh", "Start watcher", "Start overlay", "Exit application"]) {
    await expect(page.getByRole("button", { name, exact: true })).toBeDisabled();
  }
  expect(requests).toBe(2);
});
