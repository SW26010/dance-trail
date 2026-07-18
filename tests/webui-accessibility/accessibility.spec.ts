import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const wcag22AATags = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22aa",
];

const primaryPages = [
  ["/home", "Home", "#home-live-status"],
  ["/timeline", "Timeline", "#view-timeline .panel"],
  ["/catalog", "Catalog", "#view-catalog .panel"],
  ["/lists", "Lists", "#view-lists .panel"],
  ["/insights", "Insights", "#view-insights .panel"],
  ["/data-operations", "Data Operations", "#view-operations .panel"],
  ["/settings", "Settings", "[data-field=overlay_port]"],
] as const;

async function openSettledPage(
  page: Page,
  path: string,
  heading: string,
  settledSelector: string,
) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  await expect(page.locator(settledSelector).first()).toBeVisible();
  await page.waitForLoadState("networkidle");
}

async function expectNoWcag22AAViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(wcag22AATags).analyze();
  const summary = results.violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    help: violation.help,
    targets: violation.nodes.map((node) => node.target),
  }));
  expect(summary).toEqual([]);
}

async function mockTimeline(page: Page) {
  await page.route("**/api/timeline*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        date: "2026-07-18",
        records: [
          {
            id: 1,
            time: "18:10:00",
            display: "First dance",
            line: "18:10:00 First dance",
            review_status: "needs_attention",
            effective_playback_status: "needs_attention",
            default_playback_status: "needs_attention",
            dance_system_key: "wannadance",
            source_type: "random",
          },
          {
            id: 2,
            time: "20:20:00",
            display: "Second dance",
            line: "20:20:00 Second dance",
            review_status: "accepted",
            effective_playback_status: "accepted",
            default_playback_status: "accepted",
            dance_system_key: "pypydance",
            source_type: "self",
            requester_display_name: "Local user",
          },
        ],
      },
    });
  });
}

for (const theme of ["light", "dark"] as const) {
  test.describe(`${theme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => {
        localStorage.setItem("dancing-log.language", "en");
        localStorage.setItem("dancing-log.theme", value);
      }, theme);
    });

    for (const [path, heading, settledSelector] of primaryPages) {
      test(`${heading} has no automated WCAG 2.2 A/AA violations`, async ({ page }) => {
        await openSettledPage(page, path, heading, settledSelector);
        await expectNoWcag22AAViolations(page);
      });
    }
  });
}

test("application shell preserves accessible roles, names, hierarchy, and state", async ({ page }) => {
  await openSettledPage(page, "/home", "Home", "#home-live-status");

  await expect(page.getByRole("navigation", { name: "Primary" })).toMatchAriaSnapshot(`
    - navigation "Primary":
      - link "Home"
      - link "Timeline"
      - link "Catalog"
      - link "Lists"
      - link "Insights"
      - link "Data Operations"
      - link "Settings"
  `);
  await expect(page.getByRole("group", { name: "Language" })).toMatchAriaSnapshot(`
    - group "Language":
      - button "EN"
      - button "中文"
  `);
  await expect(page.getByRole("button", { name: "EN" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("combobox", { name: "Theme" })).toHaveValue("system");
});

test("keyboard navigation moves focus to the destination heading", async ({ page }) => {
  await openSettledPage(page, "/home", "Home", "#home-live-status");
  const timelineLink = page.getByRole("link", { name: "Timeline" });
  await timelineLink.focus();
  await timelineLink.press("Enter");

  const heading = page.getByRole("heading", { level: 1, name: "Timeline" });
  await expect(page).toHaveURL(/\/timeline(?:\?.*)?$/);
  await expect(heading).toBeFocused();
  await expect(timelineLink).toHaveAttribute("aria-current", "page");
});

test("skip link reaches the main application content", async ({ page }) => {
  await openSettledPage(page, "/home", "Home", "#home-live-status");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
});

test("theme and language controls expose and update their state", async ({ page }) => {
  await openSettledPage(page, "/home", "Home", "#home-live-status");
  await page.getByRole("combobox", { name: "Theme" }).selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  await page.getByRole("button", { name: "中文" }).click();
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByRole("button", { name: "中文" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "中文" })).toBeFocused();
  await expect(page.getByRole("heading", { level: 1, name: "首页" })).toBeVisible();
  await expect(page).toHaveTitle("首页 — dancing-log");
  await expectNoWcag22AAViolations(page);
});

test("timeline table and toggle button preserve accessible structure and state", async ({ page }) => {
  await mockTimeline(page);

  await openSettledPage(page, "/timeline?date=2026-07-18", "Timeline", ".timeline-table");
  const table = page.getByRole("table", { name: "Playback records" });
  await expect(table).toBeVisible();
  await expect(table.getByRole("columnheader")).toHaveCount(4);
  await expect(table.getByRole("columnheader", { name: "Time" })).toBeVisible();

  const sort = page.getByRole("button", { name: "Reverse timeline order" });
  await expect(sort).toHaveAttribute("aria-pressed", "false");
  await expect(table.locator("tbody tr").first().locator("td").first()).toHaveText("18:10:00");
  await sort.press("Space");
  await expect(sort).toHaveAttribute("aria-pressed", "true");
  await expect(sort).toBeFocused();
  await expect(table.locator("tbody tr").first().locator("td").first()).toHaveText("20:20:00");
  await expectNoWcag22AAViolations(page);
});

test("timeline preserves headers and local keyboard scrolling at 320 CSS pixels", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await mockTimeline(page);
  await openSettledPage(page, "/timeline?date=2026-07-18", "Timeline", ".timeline-table");

  const table = page.getByRole("table", { name: "Playback records" });
  await expect(table.getByRole("columnheader")).toHaveCount(4);
  await expect(table.getByRole("columnheader", { name: "Time" })).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Actions" })).toBeVisible();

  const scrollRegion = page.getByRole("region", { name: "Playback records" });
  await expect(scrollRegion).toBeVisible();
  expect(
    await scrollRegion.evaluate((node) => node.scrollWidth > node.clientWidth),
    "The two-dimensional table should overflow only its local scroll region.",
  ).toBe(true);
  await scrollRegion.focus();
  await expect(scrollRegion).toBeFocused();
  await scrollRegion.press("ArrowRight");
  await expect.poll(() => scrollRegion.evaluate((node) => node.scrollLeft)).toBeGreaterThan(0);

  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
    "The page itself must not gain horizontal scrolling at the 400% reflow equivalent.",
  ).toBe(true);
  await expectNoWcag22AAViolations(page);
});

test("settings validation associates errors and moves focus to the invalid field", async ({ page }) => {
  await openSettledPage(page, "/settings", "Settings", "[data-field=overlay_port]");
  const reset = page.getByRole("button", { name: "Reset", exact: true });
  await reset.click();
  await expect(page.getByRole("button", { name: "Reset", exact: true })).toBeFocused();
  const port = page.getByRole("spinbutton", { name: "Standalone overlay port" });
  await port.fill("70000");
  await page.getByRole("button", { name: "Save", exact: true }).click();

  await expect(page.getByRole("alert").filter({ hasText: "Save failed" })).toBeVisible();
  await expect(port).toHaveAttribute("aria-invalid", "true");
  await expect(port).toBeFocused();
  await expectNoWcag22AAViolations(page);
});

test("operation failure is announced and returns focus to its trigger", async ({ page }) => {
  await page.route("**/api/operations/run", async (route) => {
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      json: { error: "Test operation was intentionally rejected" },
    });
  });
  await openSettledPage(page, "/data-operations", "Data Operations", "#view-operations .panel");
  const runButton = page.getByRole("button", { name: "Run" }).first();
  await runButton.click();

  await expect(page.getByRole("alert")).toContainText("Test operation was intentionally rejected");
  await expect(page.getByRole("button", { name: "Run" }).first()).toBeFocused();
  await expectNoWcag22AAViolations(page);
});

test("forced-colors mode keeps the primary page operable", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active" });
  await openSettledPage(page, "/home", "Home", "#home-live-status");
  expect(await page.evaluate(() => matchMedia("(forced-colors: active)").matches)).toBe(true);
  await expect(page.getByRole("link", { name: "Home" })).toBeVisible();
  await expectNoWcag22AAViolations(page);
});

test.describe("custom APG widget inventory", () => {
  for (const [path, heading, settledSelector] of primaryPages) {
    test(`${heading} requires dedicated tests for new custom complex widgets`, async ({ page }) => {
      await openSettledPage(page, path, heading, settledSelector);
      const explicitComplexWidgets = await page
        .locator('[role="dialog"], [role="tablist"], [role="menu"], [role="combobox"], [role="grid"]')
        .evaluateAll((nodes) => nodes.map((node) => node.outerHTML));
      expect(
        explicitComplexWidgets,
        `Add APG keyboard, focus-management, state, and ARIA tests before introducing a custom complex widget on ${heading}.`,
      ).toEqual([]);
    });
  }
});
