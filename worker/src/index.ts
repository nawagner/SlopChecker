/**
 * Routes /api/runs* to D1 (report history), proxies the rest of /api/* to the
 * Railway-hosted Python service, and serves everything else from ./public.
 */

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
}

/**
 * Paths the Worker serves from D1. These are intercepted BEFORE the Railway
 * proxy and never reach FastAPI, so a route added to web.py under one of these
 * prefixes would be silently unreachable. Keep the list explicit and greppable
 * for exactly that reason.
 */
const WORKER_OWNED = ["/api/runs"];

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (WORKER_OWNED.some((p) => url.pathname === p || url.pathname.startsWith(`${p}/`))) {
      if (!env.DB) {
        return new Response(
          JSON.stringify({
            error:
              "D1 binding DB is not configured — check the [[d1_databases]] block in wrangler.toml",
          }),
          { status: 503, headers: { "content-type": "application/json" } },
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
