import { defineConfig, devices } from "@playwright/test";

const port = 8792;

export default defineConfig({
  testDir: "./tests/webui-dev",
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    locale: "en-US",
    viewport: { width: 1280, height: 720 },
  },
  webServer: {
    command: `pnpm dev:webui --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}/assets/`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
