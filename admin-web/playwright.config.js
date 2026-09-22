import { defineConfig } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
const database = join(tmpdir(), `loyalty-browser-${randomUUID()}.db`).replaceAll("\\", "/");
export default defineConfig({
  testDir: "./tests", workers: 1, timeout: 45000,
  use: { baseURL: "http://127.0.0.1:5175", headless: true, trace: "retain-on-failure" },
  webServer: [
    { command: "python -m uvicorn app.main:app --host 127.0.0.1 --port 8015 --no-access-log", cwd: "../api", url: "http://127.0.0.1:8015/health", timeout: 60000, env: { DATABASE_URL: `sqlite:///${database}`, AUTH_ENABLED: process.env.BROWSER_AUTH_ENABLED || "true", BOOTSTRAP_ADMIN_USERNAME: "browser-admin", BOOTSTRAP_ADMIN_PASSWORD: "browser-test-password", PAN_HASH_SECRET: "browser-test-only" } },
    { command: "npm run dev -- --host 127.0.0.1 --port 5175 --strictPort", url: "http://127.0.0.1:5175", timeout: 60000, env: {API_TARGET: "http://127.0.0.1:8015"} },
  ],
});
