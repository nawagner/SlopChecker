/**
 * Routes /api/runs* to D1 (report history), proxies the rest of /api/* to the
 * Railway-hosted Python service, and serves everything else from ./public.
 */

import { handleCache } from "./routes/cache";
import { handleRuns } from "./routes/runs";

export interface Env {
  ASSETS: Fetcher;
  RAILWAY_API_URL?: string;
  /**
   * D1 report history — see the [[d1_databases]] block in wrangler.toml.
   * Optional so a `wrangler dev` without the binding degrades to a 503 with a
   * usable message instead of a TypeError. "Degrade to gaps, never crash."
   */
  DB?: D1Database;
  /** Shared derived-result cache (#119) — see [[kv_namespaces]] in wrangler.toml. */
  CACHE?: KVNamespace;
  /**
   * Bearer token gating /api/cache. A secret, so it is NOT in wrangler.toml:
   *   wrangler secret put SLOPCHECK_CACHE_TOKEN
   * Unset means the cache endpoint is closed (503) rather than open — the
   * failure mode for a missing auth secret has to be "refuse", not "allow".
   */
  SLOPCHECK_CACHE_TOKEN?: string;
}

/**
 * Paths the Worker serves from its own bindings (D1 report history, KV cache).
 * These are intercepted BEFORE the Railway proxy and never reach FastAPI, so a
 * route added to web.py under one of these prefixes would be silently
 * unreachable. Keep the list explicit and greppable for exactly that reason.
 *
 * Every entry needs a matching branch in the dispatch below; membership here is
 * what takes a path away from FastAPI, so an entry with no branch is a 404 that
 * used to work.
 */
const WORKER_OWNED = ["/api/runs", "/api/cache"];

const unavailable = (error: string) =>
  new Response(JSON.stringify({ error }), {
    status: 503,
    headers: { "content-type": "application/json" },
  });

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const owns = (prefix: string) =>
      url.pathname === prefix || url.pathname.startsWith(`${prefix}/`);

    if (WORKER_OWNED.some(owns)) {
      if (owns("/api/cache")) {
        if (!env.CACHE) {
          return unavailable(
            "KV binding CACHE is not configured — check the [[kv_namespaces]] block in wrangler.toml",
          );
        }
        if (!env.SLOPCHECK_CACHE_TOKEN) {
          // Closed, not open. Callers treat any non-200 as a cache miss, so a
          // deploy that forgets the secret is slow, never insecure.
          return unavailable(
            "SLOPCHECK_CACHE_TOKEN is not set — run: wrangler secret put SLOPCHECK_CACHE_TOKEN",
          );
        }
        return handleCache(request, env.CACHE, env.SLOPCHECK_CACHE_TOKEN, url);
      }

      if (!env.DB) {
        return unavailable(
          "D1 binding DB is not configured — check the [[d1_databases]] block in wrangler.toml",
        );
      }
      return handleRuns(request, env.DB, url);
    }

    if (url.pathname.startsWith("/api/")) {
      if (!env.RAILWAY_API_URL) {
        return new Response(
          "RAILWAY_API_URL not set — run: wrangler secret put RAILWAY_API_URL",
          { status: 502 },
        );
      }
      const upstream = new URL(env.RAILWAY_API_URL);
      upstream.pathname = url.pathname.replace(/^\/api/, "");
      upstream.search = url.search;
      return fetch(new Request(upstream, request));
    }

    return env.ASSETS.fetch(request);
  },
};
