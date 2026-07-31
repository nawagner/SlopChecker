import { env, SELF } from "cloudflare:test";
import { describe, expect, it } from "vitest";

/**
 * `/api/cache` — the shared derived-result cache (#119).
 *
 * Runs against real workerd and Miniflare's real KV, so these exercise the
 * actual binding and the actual key/TTL semantics, not a mock.
 */

const BASE = "https://example.com";
const TOKEN = "test-cache-token"; // matches vitest.config.mts bindings

function cacheFetch(path: string, init: RequestInit = {}, token: string | null = TOKEN) {
  const headers = new Headers(init.headers);
  if (token !== null) headers.set("authorization", `Bearer ${token}`);
  return SELF.fetch(`${BASE}${path}`, { ...init, headers });
}

const put = (path: string, body: unknown) =>
  cacheFetch(path, {
    method: "PUT",
    body: typeof body === "string" ? body : JSON.stringify(body),
  });

describe("auth", () => {
  it("rejects a request with no Authorization header", async () => {
    const res = await cacheFetch("/api/cache/pangram/abc", {}, null);
    expect(res.status).toBe(401);
  });

  it("rejects a wrong token", async () => {
    const res = await cacheFetch("/api/cache/pangram/abc", {}, "not-the-token");
    expect(res.status).toBe(401);
  });

  it("rejects a token that is a prefix of the real one", async () => {
    // Guards the digest-then-compare in authorized(): a naive startsWith or a
    // length-mismatched timingSafeEqual would behave differently here.
    const res = await cacheFetch("/api/cache/pangram/abc", {}, TOKEN.slice(0, -1));
    expect(res.status).toBe(401);
  });

  it("checks auth before anything else, so a bad path still 401s", async () => {
    const res = await cacheFetch("/api/cache/no-key-segment", {}, null);
    expect(res.status).toBe(401);
  });
});

describe("round-trip", () => {
  it("stores and returns a value byte-for-byte", async () => {
    const value = { fraction_ai: 0.82, windows: [{ start_index: 0, end_index: 40 }] };
    expect((await put("/api/cache/pangram/deadbeef", value)).status).toBe(204);

    const res = await cacheFetch("/api/cache/pangram/deadbeef");
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("application/json");
    expect(await res.json()).toEqual(value);
  });

  it("misses on an absent key", async () => {
    const res = await cacheFetch("/api/cache/pangram/never-written");
    expect(res.status).toBe(404);
  });

  it("namespaces are independent", async () => {
    await put("/api/cache/pangram/shared-key", { from: "pangram" });
    await put("/api/cache/lens/shared-key", { from: "lens" });

    expect(await (await cacheFetch("/api/cache/pangram/shared-key")).json()).toEqual({
      from: "pangram",
    });
    expect(await (await cacheFetch("/api/cache/lens/shared-key")).json()).toEqual({ from: "lens" });
  });

  it("overwrites on repeat PUT", async () => {
    await put("/api/cache/doi/10.1234%2Fx", { resolves: false });
    await put("/api/cache/doi/10.1234%2Fx", { resolves: true });
    expect(await (await cacheFetch("/api/cache/doi/10.1234%2Fx")).json()).toEqual({
      resolves: true,
    });
  });

  it("DELETE removes the entry and is idempotent", async () => {
    await put("/api/cache/doi/purge-me", { resolves: true });
    expect((await cacheFetch("/api/cache/doi/purge-me", { method: "DELETE" })).status).toBe(204);
    expect((await cacheFetch("/api/cache/doi/purge-me")).status).toBe(404);
    // Second delete of an absent key still succeeds — #108 purge must be safe
    // to re-run.
    expect((await cacheFetch("/api/cache/doi/purge-me", { method: "DELETE" })).status).toBe(204);
  });
});

describe("keys", () => {
  it("keeps slashes inside a percent-encoded key instead of re-partitioning", async () => {
    // A URL cache key is the real case: only the first segment is the
    // namespace, and the rest must survive verbatim.
    const key = encodeURIComponent("https://example.org/a/b?c=d");
    await put(`/api/cache/url/${key}`, { status: 200 });

    expect((await cacheFetch(`/api/cache/url/${key}`)).status).toBe(200);
    // Stored under the composite key, not split across segments.
    expect(await env.CACHE.get("url:https://example.org/a/b?c=d")).not.toBeNull();
  });

  it("rejects a path with no key segment", async () => {
    expect((await cacheFetch("/api/cache/pangram")).status).toBe(400);
    expect((await cacheFetch("/api/cache/pangram/")).status).toBe(400);
  });

  it("rejects a key over KV's 512-byte ceiling as a 400, not a 500", async () => {
    const res = await cacheFetch(`/api/cache/pangram/${"x".repeat(600)}`);
    expect(res.status).toBe(400);
  });

  it("accepts a key just under the ceiling", async () => {
    // "pangram:" is 8 bytes, so 504 x's lands exactly on 512.
    const res = await put(`/api/cache/pangram/${"x".repeat(504)}`, { ok: true });
    expect(res.status).toBe(204);
  });
});

describe("body validation", () => {
  it("refuses a malformed JSON body rather than storing a poisoned entry", async () => {
    const res = await put("/api/cache/pangram/bad-json", "{not json");
    expect(res.status).toBe(400);
    expect((await cacheFetch("/api/cache/pangram/bad-json")).status).toBe(404);
  });

  it("refuses an oversized value — the privacy guard rail", async () => {
    // Over 1 MiB means document text leaked into a derived-values-only payload
    // (#119), so the write must fail rather than silently publish it.
    const res = await put("/api/cache/lens/too-big", { text: "x".repeat(1024 * 1024 + 10) });
    expect(res.status).toBe(413);
    expect((await cacheFetch("/api/cache/lens/too-big")).status).toBe(404);
  });
});

describe("ttl", () => {
  it("clamps a sub-minimum ttl to KV's 60s floor instead of erroring", async () => {
    // KV rejects expirationTtl < 60. Passing one through would turn a cache
    // write into a run-visible failure.
    const res = await put("/api/cache/pangram/short-ttl?ttl=5", { ok: true });
    expect(res.status).toBe(204);
    expect((await cacheFetch("/api/cache/pangram/short-ttl")).status).toBe(200);
  });

  it("ignores a non-numeric ttl and uses the default", async () => {
    const res = await put("/api/cache/pangram/bad-ttl?ttl=soon", { ok: true });
    expect(res.status).toBe(204);
    expect((await cacheFetch("/api/cache/pangram/bad-ttl")).status).toBe(200);
  });
});

describe("routing", () => {
  it("405s an unsupported method rather than falling through to Railway", async () => {
    const res = await cacheFetch("/api/cache/pangram/abc", { method: "POST" });
    expect(res.status).toBe(405);
  });

  it("does not shadow /api/runs", async () => {
    const res = await SELF.fetch(`${BASE}/api/runs`);
    expect(res.status).toBe(200);
  });
});
