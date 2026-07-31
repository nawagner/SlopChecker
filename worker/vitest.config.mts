import path from "node:path";

import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

/**
 * Tests run in real workerd against real D1 (Miniflare's SQLite, the engine D1
 * itself runs), so they exercise the actual binding, the actual db.batch()
 * semantics, and — the reason it's worth the dependency — the actual generated
 * migration SQL. A better-sqlite3 harness would test a different engine through
 * a different driver and would not catch a CHECK constraint that D1 rejects.
 *
 * Two notes for anyone comparing this against a blog post or the Cloudflare
 * docs, both verified against
 * node_modules/@cloudflare/vitest-pool-workers/dist/pool/index.d.mts:
 *
 *   - 0.20 removed `defineWorkersConfig` and the `/config` subpath. The current
 *     API is the `cloudflareTest()` Vite plugin.
 *   - The migrations must be read inside the async options factory, not at
 *     module top level: Vite bundles this config as CJS, where top-level await
 *     is a build error.
 *
 * Migrations are read from disk and applied per test file (test/setup.ts), so
 * the tests fail if schema.ts and migrations/ have drifted — the generated SQL
 * is what's under test, not the TypeScript.
 */
export default defineConfig({
  plugins: [
    cloudflareTest(async () => ({
      wrangler: { configPath: "./wrangler.toml" },
      miniflare: {
        bindings: {
          TEST_MIGRATIONS: await readD1Migrations(path.join(process.cwd(), "migrations")),
          // The real value is a Worker secret (`wrangler secret put`), so it is
          // absent from wrangler.toml and therefore from the test env too.
          // Without it every /api/cache test would assert against the 503
          // "token not set" branch instead of the route.
          SLOPCHECK_CACHE_TOKEN: "test-cache-token",
        },
      },
    })),
  ],
  test: {
    setupFiles: ["./test/setup.ts"],
  },
});
