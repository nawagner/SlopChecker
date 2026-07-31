import type { D1Migration } from "@cloudflare/vitest-pool-workers";

import type { Env as WorkerEnv } from "../src/index";

/**
 * Types the bindings `cloudflare:test` hands to tests.
 *
 * Note the interface: @cloudflare/vitest-pool-workers 0.20 types `env` as
 * `Cloudflare.Env`. Older guides declare-merge into `ProvidedEnv`, which this
 * version no longer references — verified in
 * node_modules/@cloudflare/vitest-pool-workers/types/cloudflare-test.d.ts.
 *
 * `DB`, `CACHE` and `SLOPCHECK_CACHE_TOKEN` are non-optional here (they're
 * optional on the Worker's own Env, so an unbound dev session degrades
 * gracefully) because the test config always binds them and every test would
 * otherwise need a null check.
 */
declare global {
  namespace Cloudflare {
    interface Env extends WorkerEnv {
      DB: D1Database;
      CACHE: KVNamespace;
      SLOPCHECK_CACHE_TOKEN: string;
      TEST_MIGRATIONS: D1Migration[];
    }
  }
}

/** Vite's `?raw` suffix — used to load the fixture as text. */
declare module "*.json?raw" {
  const content: string;
  export default content;
}

export {};
