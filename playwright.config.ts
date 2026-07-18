import { defineConfig, devices } from "@playwright/test";

const port = 8791;

export default defineConfig({
  testDir: "./tests/webui-accessibility",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "line",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    colorScheme: "light",
    locale: "en-US",
    screenshot: "only-on-failure",
    trace: "on-first-retry",
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: `uv run --locked --cache-dir .uv-cache python -m scripts.run_webui_test_server --port ${port} --app-root .playwright-runtime`,
    url: `http://127.0.0.1:${port}/home`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
