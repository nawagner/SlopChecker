/**
 * `/api/cache` — shared KV cache for expensive derived results (#119).
 *
 *   GET    /api/cache/:namespace/:key   -> 200 <stored JSON> | 404
 *   PUT    /api/cache/:namespace/:key   -> 204   body: JSON, ?ttl=<seconds>
 *   DELETE /api/cache/:namespace/:key   -> 204   (idempotent)
 *
 * Why this endpoint exists at all rather than Python calling KV directly:
 * KV's REST API needs a Cloudflare API token, and #23/#65 established that no
 * credential is minted or pasted in a session (this repo commits transcripts
 * publicly). Same reasoning as the `[[d1_databases]]` note in wrangler.toml.
 * So the Worker holds the binding and Python holds one narrow bearer token
 * that can do nothing but read and write cache entries.
 *
 * These paths are served by the Worker and never reach FastAPI — see the
 * WORKER_OWNED note in index.ts.
 */

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });

/**
 * KV's own key ceiling. Enforced here so an oversized key fails as a clean 400
 * rather than a KV exception surfacing as a 500 on a *cache* call — a cache
 * must never be able to fail a run.
 */
const MAX_KEY_BYTES = 512;

/**
 * Deliberately far below KV's 25 MiB value ceiling.
 *
 * This is a privacy guard rail, not a performance one. #119 decided only
 * derived values (scores, offsets, resolution status) may enter the shared
 * cache — never document text. Such payloads are small by construction, so a
 * megabyte-plus value means text leaked into one, and the write should fail
 * loudly instead of silently publishing it.
 */
const MAX_VALUE_BYTES = 1024 * 1024;

/** KV rejects any expirationTtl below 60s. */
const MIN_TTL_S = 60;

/** 30 days. Content-hash keys are immutable, but an unbounded cache is worse. */
const DEFAULT_TTL_S = 30 * 24 * 3600;

/**
 * Constant-time bearer check.
 *
 * `crypto.subtle.timingSafeEqual` throws on length mismatch, which would itself
 * leak the secret's length, so both sides are SHA-256'd to a fixed 32 bytes
 * first and the digests are compared.
 */
async function authorized(request: Request, secret: string): Promise<boolean> {
  const header = request.headers.get("authorization") ?? "";
  const presented = header.startsWith("Bearer ") ? header.slice(7) : "";
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(presented)),
    crypto.subtle.digest("SHA-256", enc.encode(secret)),
  ]);
  return crypto.subtle.timingSafeEqual(a, b);
}

/**
 * `:namespace/:key` -> the flat KV key.
 *
 * The key segment may itself contain slashes (a URL used as a cache key does),
 * so only the FIRST segment is the namespace and the rest is the key verbatim.
 * Each segment is decoded once — the client percent-encodes, so a key
 * containing `/` or `:` round-trips instead of silently re-partitioning.
 */
function parseKey(rest: string): { namespace: string; key: string } | null {
  const slash = rest.indexOf("/");
  if (slash <= 0 || slash === rest.length - 1) return null;
  let namespace: string;
  let key: string;
  try {
    namespace = decodeURIComponent(rest.slice(0, slash));
    key = decodeURIComponent(rest.slice(slash + 1));
  } catch {
    return null; // malformed percent-encoding
  }
  if (!namespace || !key) return null;
  return { namespace, key };
}

const byteLength = (s: string) => new TextEncoder().encode(s).length;

export async function handleCache(
  request: Request,
  kv: KVNamespace,
  secret: string,
  url: URL,
): Promise<Response> {
  if (!(await authorized(request, secret))) {
    return json({ error: "missing or invalid bearer token" }, 401);
  }

  const rest = url.pathname.replace(/^\/api\/cache\/?/, "");
  const parsed = parseKey(rest);
  if (!parsed) {
    return json({ error: "path must be /api/cache/:namespace/:key" }, 400);
  }

  const kvKey = `${parsed.namespace}:${parsed.key}`;
  if (byteLength(kvKey) > MAX_KEY_BYTES) {
    return json({ error: `key exceeds ${MAX_KEY_BYTES} bytes` }, 400);
  }

  switch (request.method) {
    case "GET": {
      // `type: "stream"` would avoid a parse, but "text" lets the stored value
      // pass through byte-for-byte as the response body: the client gets back
      // exactly what it PUT, and the Worker never needs to understand it.
      const value = await kv.get(kvKey, "text");
      if (value === null) return json({ error: "not found", key: kvKey }, 404);
      return new Response(value, {
        headers: { "content-type": "application/json; charset=utf-8" },
      });
    }

    case "PUT": {
      const body = await request.text();
      if (byteLength(body) > MAX_VALUE_BYTES) {
        return json(
          {
            error: `value exceeds ${MAX_VALUE_BYTES} bytes — cache entries hold derived values only, never document text (#119)`,
          },
          413,
        );
      }
      try {
        JSON.parse(body);
      } catch {
        // Validated, not stored-as-parsed: a malformed body must not become a
        // poisoned entry that every later reader fails to decode.
        return json({ error: "body must be valid JSON" }, 400);
      }
      const requested = Number(url.searchParams.get("ttl"));
      const ttl =
        Number.isFinite(requested) && requested > 0
          ? Math.max(MIN_TTL_S, Math.floor(requested))
          : DEFAULT_TTL_S;
      await kv.put(kvKey, body, { expirationTtl: ttl });
      return new Response(null, { status: 204 });
    }

    case "DELETE":
      // Idempotent by KV's own semantics — deleting an absent key is a no-op.
      // Wanted by #108 (cache purge as a data-handling control).
      await kv.delete(kvKey);
      return new Response(null, { status: 204 });

    default:
      return json({ error: `method ${request.method} not allowed on ${url.pathname}` }, 405);
  }
}
