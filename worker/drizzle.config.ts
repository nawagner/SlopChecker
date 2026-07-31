import { defineConfig } from "drizzle-kit";

/**
 * Migration GENERATION only. Note what is deliberately absent: no `driver`, no
 * `dbCredentials`.
 *
 *   - `driver: "d1-http"` (and therefore `drizzle-kit push` / `studio`) needs
 *     CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_D1_TOKEN. Per #23 and #65, no
 *     credential is ever minted or pasted in a session in this repo —
 *     transcripts land in a public directory and CLAUDE.md is explicit that
 *     the scrubber is best-effort, not a guarantee. Omitting the driver makes
 *     this config structurally incapable of touching the network: it reads
 *     schema.ts, diffs against the snapshot, writes SQL. That's all.
 *
 *   - `out` MUST match `migrations_dir` in wrangler.toml. drizzle-kit writes
 *     NNNN_*.sql here and `wrangler d1 migrations apply` reads it. Wrangler
 *     globs *.sql non-recursively, so the `meta/` subfolder is invisible to
 *     it — but `meta/` must still be COMMITTED: it's drizzle-kit's diff
 *     snapshot, and without it every `generate` re-emits the whole schema.
 */
export default defineConfig({
  dialect: "sqlite",
  schema: "./src/db/schema.ts",
  out: "./migrations",
  strict: true,
  verbose: true,
});
