/**
 * Proxies /api/* to the Railway-hosted Python service; everything else is
 * static assets from ./public. Placeholder until #27's real frontend lands.
 */

export interface Env {
  ASSETS: Fetcher;
  RAILWAY_API_URL?: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

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
