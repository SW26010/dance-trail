import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

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

function summaryPayload(session: Record<string, unknown> = {}) {
  return {
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
      ...session,
    },
  };
}

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

async function computedTextContrast(locator: Locator) {
  return locator.evaluate((node) => {
    type Rgba = [number, number, number, number];
    const parse = (value: string): Rgba => {
      const channels = value.match(/[\d.]+/g)?.map(Number) ?? [];
      if (channels.length < 3) throw new Error(`Unsupported computed color: ${value}`);
      return [channels[0], channels[1], channels[2], channels[3] ?? 1];
    };
    const composite = (foreground: Rgba, background: Rgba): Rgba => {
      const alpha = foreground[3] + background[3] * (1 - foreground[3]);
      if (alpha === 0) return [0, 0, 0, 0];
      return [
        (foreground[0] * foreground[3] + background[0] * background[3] * (1 - foreground[3])) / alpha,
        (foreground[1] * foreground[3] + background[1] * background[3] * (1 - foreground[3])) / alpha,
        (foreground[2] * foreground[3] + background[2] * background[3] * (1 - foreground[3])) / alpha,
        alpha,
      ];
    };
    const luminance = (color: Rgba) => {
      const linear = color.slice(0, 3).map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.04045
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
    };

    const foreground = parse(getComputedStyle(node).color);
    const layers: Rgba[] = [];
    let current: Element | null = node;
    while (current) {
      const background = parse(getComputedStyle(current).backgroundColor);
      if (background[3] > 0) layers.push(background);
      if (background[3] === 1) break;
      current = current.parentElement;
    }
    let background: Rgba = [255, 255, 255, 1];
    for (const layer of layers.reverse()) background = composite(layer, background);
    const foregroundLuminance = luminance(composite(foreground, background));
    const backgroundLuminance = luminance(background);
    return (Math.max(foregroundLuminance, backgroundLuminance) + 0.05)
      / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
  });
}

async function mockTimeline(page: Page) {
  await page.route("**/api/timeline*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        date: "2026-07-18",
        source: "all",
        database_exists: true,
        records: [
          {
            id: 1,
            time: "18:10:00",
            played_at: "2026-07-18T18:10:00+08:00",
            display: "First dance",
            line: "18:10:00 First dance",
            review_status: "needs_attention",
            default_playback_status: "needs_attention",
            manual_decision_status: null,
            effective_playback_status: "needs_attention",
            has_manual_decision: false,
            dance_system_key: "wannadance",
            dance_system_name: "WannaDance",
            source_type: "random",
            source_display_name: null,
            requester_display_name: null,
            requester_user_id: null,
          },
          {
            id: 2,
            time: "20:20:00",
            played_at: "2026-07-18T20:20:00+08:00",
            display: "Second dance",
            line: "20:20:00 Second dance",
            review_status: "accepted",
            default_playback_status: "accepted",
            manual_decision_status: null,
            effective_playback_status: "accepted",
            has_manual_decision: false,
            dance_system_key: "pypydance",
            dance_system_name: "PyPyDance",
            source_type: "self",
            source_display_name: null,
            requester_display_name: "Local user",
            requester_user_id: null,
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
  await expect(page.locator("#home-live-status")).not.toHaveAttribute("aria-live");
});

test("Home can retry an initial summary failure and clears the stale error", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/summary", async (route) => {
    requests += 1;
    if (requests === 1) {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        json: { error: "Summary temporarily unavailable" },
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      json: summaryPayload(),
    });
  });

  await page.goto("/home");
  const feedbackRegion = page.locator('[data-feedback-region]').first();
  await expect(feedbackRegion).toContainText("Summary temporarily unavailable");
  await page.getByRole("button", { name: "Refresh" }).click();

  await expect(page.locator("#home-live-status")).toBeVisible();
  await expect(feedbackRegion).toBeEmpty();
});

test("Home commits a terminal session returned by the final stopping poll", async ({ page }) => {
  let polling = false;
  let pollRequests = 0;
  await page.route("**/api/summary", async (route) => {
    if (!polling) {
      await route.fulfill({
        contentType: "application/json",
        json: summaryPayload({ watcher_running: true, watcher_state: "running" }),
      });
      return;
    }
    pollRequests += 1;
    const terminal = pollRequests === 20;
    await route.fulfill({
      contentType: "application/json",
      json: summaryPayload({
          watcher_running: !terminal,
          watcher_state: terminal ? "stopped" : "stopping",
      }),
    });
  });
  await page.route("**/api/live/watcher", async (route) => {
    polling = true;
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      json: {
        error: "Watcher is stopping",
        session: summaryPayload({ watcher_running: true, watcher_state: "stopping" }).session,
      },
    });
  });

  await openSettledPage(page, "/home", "Home", "#home-live-status");
  await page.getByRole("button", { name: "Stop watcher" }).click();

  await expect(page.getByRole("button", { name: "Start watcher" })).toBeEnabled({ timeout: 8_000 });
  expect(pollRequests).toBe(20);
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

test("success responses with a drifted shape fail at the HTTP contract boundary", async ({ page }) => {
  await page.route("**/api/summary", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: { counts: {} },
    });
  });

  await page.goto("/home");
  await expect(page.locator("[data-feedback-region]").first()).toContainText(
    "Invalid API response from /api/summary",
  );
});

test("error responses with a drifted shape fail at the HTTP contract boundary", async ({ page }) => {
  await page.route("**/api/summary", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      json: { message: "renamed error field" },
    });
  });

  await page.goto("/home");
  await expect(page.locator("[data-feedback-region]").first()).toContainText(
    "Invalid API response from /api/summary",
  );
});

test("navigation scrolls the focused heading into a 320 by 225 CSS-pixel viewport", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 225 });
  await openSettledPage(page, "/home", "Home", "#home-live-status");
  const timelineLink = page.getByRole("link", { name: "Timeline" });
  await timelineLink.focus();
  await timelineLink.press("Enter");

  const heading = page.getByRole("heading", { level: 1, name: "Timeline" });
  await expect(heading).toBeFocused();
  const visibility = await heading.evaluate((node) => {
    const bounds = node.getBoundingClientRect();
    return { top: bounds.top, bottom: bounds.bottom, viewportHeight: innerHeight };
  });
  expect(visibility.top).toBeGreaterThanOrEqual(0);
  expect(visibility.bottom).toBeLessThanOrEqual(visibility.viewportHeight);
});

test("dark-theme primary button text keeps AA contrast while pressed", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("dancing-log.language", "en");
    localStorage.setItem("dancing-log.theme", "dark");
  });
  await openSettledPage(page, "/home", "Home", "#home-live-status");
  const button = page.getByRole("button", { name: "Start watcher" });
  const bounds = await button.boundingBox();
  if (!bounds) throw new Error("Start watcher button has no rendered bounds");
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  const ratio = await computedTextContrast(button);
  await page.mouse.move(0, 0);
  await page.mouse.up();

  expect(ratio, `Pressed text contrast was ${ratio.toFixed(3)}:1`).toBeGreaterThanOrEqual(4.5);
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

test("timeline clears loading when an invalid date cancels an in-flight request", async ({ page }) => {
  await page.route("**/api/timeline*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 250));
    await route.fulfill({
      contentType: "application/json",
      json: { date: "2026-07-18", source: "all", database_exists: true, records: [] },
    });
  });

  await page.goto("/timeline?date=2026-07-18");
  await expect(page.locator("#view-timeline .panel")).toContainText("Loading");
  await page.getByRole("textbox", { name: "Timeline date" }).fill("2026-07-");

  await expect(page.locator("#view-timeline .panel")).not.toContainText("Loading");
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

for (const [path, heading, settledSelector] of [
  ["/data-operations", "Data Operations", "#view-operations .panel"],
  ["/settings", "Settings", "[data-field=overlay_port]"],
] as const) {
  test(`${heading} reflows without page-level horizontal scrolling at 320 CSS pixels`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 900 });
    await openSettledPage(page, path, heading, settledSelector);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
      `${heading} must reflow inside the viewport at the 400% equivalent.`,
    ).toBe(true);
    await expectNoWcag22AAViolations(page);
  });
}

test("settings validation associates errors and moves focus to the invalid field", async ({ page }) => {
  await openSettledPage(page, "/settings", "Settings", "[data-field=overlay_port]");
  const reset = page.getByRole("button", { name: "Reset", exact: true });
  await reset.click();
  await expect(page.getByRole("button", { name: "Reset", exact: true })).toBeFocused();
  const port = page.getByRole("spinbutton", { name: "Standalone overlay port" });
  await port.fill("70000");
  await page.getByRole("button", { name: "Save", exact: true }).click();

  await expect(page.locator("[data-feedback-region]").filter({ hasText: "Save failed" })).toBeVisible();
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
  const feedbackRegion = page.locator(".panel").first().locator("[data-feedback-region]");
  await expect(feedbackRegion).toBeEmpty();
  await feedbackRegion.evaluate((node) => {
    (window as Window & { operationFeedbackRegion?: Element }).operationFeedbackRegion = node;
  });
  await runButton.click();

  await expect(feedbackRegion).toContainText("Test operation was intentionally rejected");
  expect(await feedbackRegion.evaluate(
    (node) => node === (window as Window & { operationFeedbackRegion?: Element }).operationFeedbackRegion,
  )).toBe(true);
  await expect(feedbackRegion).not.toHaveAttribute("role");
  await expect(feedbackRegion).not.toHaveAttribute("aria-live");
  await expect(page.locator(".panel").first().locator("[data-live-region]")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Run" }).first()).toBeFocused();
  await expectNoWcag22AAViolations(page);
});

test("optional operation row limits stay blank until explicitly set", async ({ page }) => {
  const payloads: Array<Record<string, unknown>> = [];
  await page.route("**/api/operations/run", async (route) => {
    payloads.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.fulfill({
      contentType: "application/json",
      json: {
        result: {
          operation_key: "import-vrcx",
          title: "Import VRCX history",
          status: "completed",
          summary: "done",
          lines: [],
          metrics: {},
        },
      },
    });
  });
  await openSettledPage(page, "/data-operations", "Data Operations", "#view-operations .panel");
  const operation = page.locator(".panel").filter({ hasText: "Import VRCX history" });
  const limit = operation.getByRole("spinbutton", { name: "Row limit" });

  await expect(limit).toHaveValue("");
  await operation.getByRole("button", { name: "Run" }).click();
  await expect.poll(() => payloads.length).toBe(1);
  expect(payloads[0]).toMatchObject({ operation: "import-vrcx", parameters: {} });
  expect((payloads[0].parameters as Record<string, unknown>).limit).toBeUndefined();

  await limit.fill("0");
  await operation.getByRole("button", { name: "Run" }).click();
  await expect.poll(() => payloads.length).toBe(2);
  expect(payloads[1]).toMatchObject({ operation: "import-vrcx", parameters: { limit: 0 } });
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
