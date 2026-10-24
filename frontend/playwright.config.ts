import { defineConfig } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// A private stack on free ports (8040 / 3040), never the dev ports 8000 / 3000.
const BACKEND_PORT = 8040;
const FRONTEND_PORT = 3040;
const TMP = path.join(__dirname, "e2e", ".tmp");
const DB_FILE = path.join(TMP, "e2e.db").split(path.sep).join("/");

// A fresh database every run. The web servers start right after the config loads, so this
// cannot wait for globalSetup; worker processes load the config too and must not wipe it.
const REUSE = !!process.env.E2E_REUSE; // iterate against stacks started by hand
if (process.env.TEST_WORKER_INDEX === undefined && !REUSE) {
  fs.rmSync(TMP, { recursive: true, force: true });
  fs.mkdirSync(TMP, { recursive: true });
}

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  testMatch: /.*\.spec\.ts/,
  outputDir: "./test-results",
  // One shared database, so one worker; no retries so flakiness shows up.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [["line"]],
  timeout: 90_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: "off",
    screenshot: "off",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: [
    {
      command: ".venv\\Scripts\\python dev.py", // Windows cmd needs backslashes here
      cwd: "../backend",
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      env: {
        PORT: String(BACKEND_PORT),
        MARKET_DATA_PROVIDER: "fake",
        BACKGROUND_JOBS: "true",
        SEED_DEMO_MARKETPLACE: "true",
        DATABASE_URL: `sqlite:///${DB_FILE}`,
        PYTHONIOENCODING: "utf-8",
      },
      reuseExistingServer: REUSE,
      timeout: 180_000,
    },
    {
      command: `npx next dev -p ${FRONTEND_PORT}`,
      cwd: ".",
      url: `http://127.0.0.1:${FRONTEND_PORT}/login`,
      env: {
        BACKEND_URL: `http://127.0.0.1:${BACKEND_PORT}`,
        NEXT_DIST_DIR: ".next-e2e",
      },
      reuseExistingServer: REUSE,
      timeout: 180_000,
    },
  ],
});
