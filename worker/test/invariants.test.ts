import { env, SELF } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";

import sample from "../../tests/fixtures/sample_report.json";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const BASE = "https://example.com";

/** POST a report. `body` may be a pre-built object (JSON-encoded for you) or
 * a raw string (sent byte-for-byte, for malformed-body / key-order tests). */
async function post(path: string, body: unknown) {
  return SELF.fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

async function get(path: string) {
  return SELF.fetch(`${BASE}${path}`);
}

function freshFixture(): typeof sample {
  return structuredClone(sample);
}

/** A minimal, valid report — used where the full fixture would be noise. */
function minimalReport(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "0.1",
    document: { file: "min.pdf", text: "minimal report body text" },
    summary: { recommendation: "human_review" },
    ...overrides,
  };
}

/** Seed a submission + run directly via SQL, bypassing the app, so
 * constraint tests exercise exactly the table under test and nothing else. */
async function seedRun(): Promise<{ submissionId: string; runId: string }> {
  const now = Date.now();
  const submissionId = crypto.randomUUID();
  const runId = crypto.randomUUID();
  await env.DB.prepare(
    "INSERT INTO submissions (id, text_sha256, text_length, file, created_at) VALUES (?, ?, ?, ?, ?)",
  )
    .bind(submissionId, crypto.randomUUID(), 100, "seed.pdf", now)
    .run();
  await env.DB.prepare(
    "INSERT INTO runs (id, submission_id, report_sha256, schema_version, recommendation, created_at) VALUES (?, ?, ?, ?, ?, ?)",
  )
    .bind(runId, submissionId, crypto.randomUUID(), "0.1", "human_review", now)
    .run();
  return { submissionId, runId };
}

/** Build `INSERT INTO <table> (...) VALUES (...)` from a plain object, so each
 * constraint test only has to name the columns it cares about. */
async function rawInsert(table: string, values: Record<string, unknown>) {
  const cols = Object.keys(values);
  const placeholders = cols.map(() => "?").join(", ");
  return env.DB.prepare(`INSERT INTO ${table} (${cols.join(", ")}) VALUES (${placeholders})`)
    .bind(...cols.map((c) => values[c]))
    .run();
}

/** Insert one bare finding row (for finding_checks FK tests) and return its id. */
async function seedFinding(runId: string): Promise<string> {
  const findingId = crypto.randomUUID();
  await rawInsert("findings", {
    id: findingId,
    run_id: runId,
    ordinal: 0,
    finding_key: "C1",
    evidence: "{}",
  });
  return findingId;
}

async function tableCount(table: string): Promise<number> {
  const { results } = await env.DB.prepare(`SELECT COUNT(*) as c FROM ${table}`).all<{ c: number }>();
  return results[0]?.c ?? 0;
}

beforeEach(async () => {
  // Cascades to runs -> findings/ledger_rows -> finding_checks.
  await env.DB.exec("DELETE FROM submissions");
});

// ---------------------------------------------------------------------------
// HTTP failure modes
// ---------------------------------------------------------------------------

describe("HTTP failure modes", () => {
  it("rejects malformed JSON with 400, not 500", async () => {
    const res = await post("/api/runs", "{ this is not json");
    expect(res.status).toBe(400);
    const body = await res.json<{ error: string }>();
    expect(body.error).toMatch(/valid JSON/i);
  });

  it("rejects a JSON array body with 400", async () => {
    const res = await post("/api/runs", "[1, 2, 3]");
    expect(res.status).toBe(400);
    const body = await res.json<{ error: string }>();
    expect(body.error).toMatch(/object/i);
  });

  it("rejects a bare JSON string body with 400", async () => {
    const res = await post("/api/runs", '"just a string"');
    expect(res.status).toBe(400);
    const body = await res.json<{ error: string }>();
    expect(body.error).toMatch(/object/i);
  });

  it("rejects a report missing document with 400 naming the path", async () => {
    const res = await post("/api/runs", { schema_version: "0.1" });
    expect(res.status).toBe(400);
    const body = await res.json<{ error: string; path: string }>();
    expect(body.path).toBe("document");
  });

  it("rejects a report missing document.file with 400 naming the path", async () => {
    const res = await post("/api/runs", { document: { text: "hello" } });
    expect(res.status).toBe(400);
    const body = await res.json<{ error: string; path: string }>();
    expect(body.path).toBe("document.file");
  });

  it("rejects a report missing document.text with 400 naming the path", async () => {
    const res = await post("/api/runs", { document: { file: "x.pdf" } });
    expect(res.status).toBe(400);
    const body = await res.json<{ error: string; path: string }>();
    expect(body.path).toBe("document.text");
  });

  it("rejects a string result on a check with 400 naming the path", async () => {
    const report = minimalReport({
      findings: [{ id: "C1", checks: [{ name: "doi_resolves", result: "true" }] }],
    });
    const res = await post("/api/runs", report);
    expect(res.status).toBe(400);
    const body = await res.json<{ error: string; path: string }>();
    expect(body.path).toBe("findings[0].checks[0].result");
  });

  it("returns JSON, not a 500, for every failure mode above", async () => {
    // Belt-and-suspenders: none of the malformed bodies above should ever
    // produce a 5xx or a non-JSON body.
    const bodies = ["{ bad", "[1]", '"str"', "{}", JSON.stringify({ document: { file: "x" } })];
    for (const b of bodies) {
      const res = await post("/api/runs", b);
      expect(res.status).toBeLessThan(500);
      expect(res.headers.get("content-type")).toMatch(/application\/json/);
    }
  });

  it("returns 405 for an unsupported method on /api/runs", async () => {
    const res = await SELF.fetch(`${BASE}/api/runs`, { method: "DELETE" });
    expect(res.status).toBe(405);
    const body = await res.json<{ error: string }>();
    expect(body.error).toMatch(/DELETE/);
  });

  it("returns 405 for an unsupported method on /api/runs/:id", async () => {
    const res = await SELF.fetch(`${BASE}/api/runs/some-id`, { method: "PATCH" });
    expect(res.status).toBe(405);
    const body = await res.json<{ error: string }>();
    expect(body.error).toMatch(/PATCH/);
  });

  it("returns 404 for an unknown run id", async () => {
    const res = await get("/api/runs/does-not-exist");
    expect(res.status).toBe(404);
    const body = await res.json<{ error: string; run_id: string }>();
    expect(body.error).toMatch(/not found/i);
    expect(body.run_id).toBe("does-not-exist");
  });

  it("URL-decodes a run id before the 404 lookup", async () => {
    // A run id containing an encoded slash must be decoded, not treated as a
    // path segment boundary or left percent-encoded in the response.
    const res = await get("/api/runs/abc%2Fdef");
    expect(res.status).toBe(404);
    const body = await res.json<{ run_id: string }>();
    expect(body.run_id).toBe("abc/def");
  });

  it("URL-decodes a run id before a successful lookup", async () => {
    const created = await (await post("/api/runs", minimalReport())).json<{ run_id: string }>();
    // Percent-encode one character of an otherwise-valid id (hyphens are
    // legal unencoded, so this proves decode runs rather than being a no-op).
    const escaped = created.run_id.replace("-", "%2D");
    expect(escaped).not.toBe(created.run_id); // sanity: the encoding actually changed the string
    const res = await get(`/api/runs/${escaped}`);
    expect(res.status).toBe(200);
    const body = await res.json<{ run_id: string }>();
    expect(body.run_id).toBe(created.run_id);
  });
});

// ---------------------------------------------------------------------------
// Idempotency
// ---------------------------------------------------------------------------

describe("idempotency", () => {
  it("returns created:false and the same run_id on an identical replay", async () => {
    const report = freshFixture();
    const first = await post("/api/runs", report);
    expect(first.status).toBe(201);
    const firstBody = await first.json<{ run_id: string; created: boolean }>();
    expect(firstBody.created).toBe(true);

    const second = await post("/api/runs", freshFixture()); // fresh clone, identical content
    expect(second.status).toBe(200);
    const secondBody = await second.json<{ run_id: string; created: boolean }>();
    expect(secondBody.created).toBe(false);
    expect(secondBody.run_id).toBe(firstBody.run_id);

    expect(await tableCount("runs")).toBe(1);
    expect(await tableCount("submissions")).toBe(1);
  });

  it("treats a re-indented (whitespace-only) replay as the same report", async () => {
    const canonical = JSON.stringify(minimalReport());
    const rePrettied = JSON.stringify(minimalReport(), null, 4); // same key order, different whitespace

    const first = await post("/api/runs", canonical);
    const firstBody = await first.json<{ run_id: string; created: boolean }>();
    expect(firstBody.created).toBe(true);

    const second = await post("/api/runs", rePrettied);
    const secondBody = await second.json<{ run_id: string; created: boolean }>();
    expect(second.status).toBe(200);
    expect(secondBody.created).toBe(false);
    expect(secondBody.run_id).toBe(firstBody.run_id);
  });

  // BUG (confirmed against pristine source, not a test defect — see report):
  // the contract says a report re-serialized with different key order should
  // still be recognised as the same report, "because it is re-stringified
  // before hashing" (src/routes/runs.ts: `sha256Hex(JSON.stringify(report))`).
  // But `JSON.stringify` preserves each object's OWN key insertion order — it
  // only normalizes whitespace, never key order — so two payloads that differ
  // solely in top-level key order hash differently and silently create a
  // Regression test for a real bug found during review: the hash was computed
  // with plain JSON.stringify, which normalizes whitespace but preserves key
  // insertion order — so the same report from a different producer created a
  // duplicate run. Fixed by hashing a canonical (key-sorted) form.
  it("treats a key-order-shuffled replay as the same report", async () => {
    const bodyA = '{"document":{"file":"x.pdf","text":"key order replay text"},"schema_version":"0.1"}';
    const bodyB = '{"schema_version":"0.1","document":{"file":"x.pdf","text":"key order replay text"}}';

    const first = await post("/api/runs", bodyA);
    const firstBody = await first.json<{ run_id: string; created: boolean }>();
    expect(firstBody.created).toBe(true);

    const second = await post("/api/runs", bodyB);
    const secondBody = await second.json<{ run_id: string; created: boolean }>();
    expect(secondBody.created).toBe(false);
    expect(secondBody.run_id).toBe(firstBody.run_id);
  });

  it("creates two runs for two genuinely different reports on the same document", async () => {
    const text = "shared document text for the two-different-reports test";
    const reportA = minimalReport({ document: { file: "same.pdf", text }, schema_version: "0.1" });
    const reportB = minimalReport({ document: { file: "same.pdf", text }, schema_version: "0.2" });

    const first = await post("/api/runs", reportA);
    const firstBody = await first.json<{ run_id: string; submission_id: string; created: boolean }>();
    expect(firstBody.created).toBe(true);

    const second = await post("/api/runs", reportB);
    expect(second.status).toBe(201);
    const secondBody = await second.json<{ run_id: string; submission_id: string; created: boolean }>();
    expect(secondBody.created).toBe(true);
    expect(secondBody.run_id).not.toBe(firstBody.run_id);
    // Same document -> same submission, reused rather than duplicated.
    expect(secondBody.submission_id).toBe(firstBody.submission_id);

    expect(await tableCount("runs")).toBe(2);
    expect(await tableCount("submissions")).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// 409 metadata divergence
// ---------------------------------------------------------------------------

describe("409 divergence on same text, different metadata", () => {
  const text = "text shared across the 409-divergence tests, held constant";

  it("409s when the file name diverges for identical text", async () => {
    const first = await post("/api/runs", minimalReport({ document: { file: "a.pdf", text } }));
    expect(first.status).toBe(201);

    const second = await post("/api/runs", minimalReport({ document: { file: "b.pdf", text } }));
    expect(second.status).toBe(409);
    const body = await second.json<{ error: string; fields: string[] }>();
    expect(body.fields).toEqual(["file"]);
    expect(body.error).toMatch(/diverges/i);

    // The conflicting write must not have landed.
    expect(await tableCount("submissions")).toBe(1);
    expect(await tableCount("runs")).toBe(1);
  });

  it("names every field that diverged, not just the first", async () => {
    const first = await post(
      "/api/runs",
      minimalReport({ document: { file: "a.pdf", text, title: "T1", byline: "B1" } }),
    );
    expect(first.status).toBe(201);

    const second = await post(
      "/api/runs",
      minimalReport({ document: { file: "a.pdf", text, title: "T2", byline: "B2" } }),
    );
    expect(second.status).toBe(409);
    const body = await second.json<{ fields: string[] }>();
    expect(new Set(body.fields)).toEqual(new Set(["title", "byline"]));
    expect(body.fields).not.toContain("file"); // file was NOT changed, must not be named
  });

  it("does not conflict when text and metadata both match — reuses the submission", async () => {
    const doc = { file: "a.pdf", text, title: "T1", submitter: "S1" };
    const first = await post("/api/runs", minimalReport({ document: doc, schema_version: "0.1" }));
    const firstBody = await first.json<{ submission_id: string }>();

    // A genuinely different report (different schema_version -> different
    // report hash) but byte-identical metadata must NOT 409.
    const second = await post("/api/runs", minimalReport({ document: doc, schema_version: "0.2" }));
    expect(second.status).toBe(201);
    const secondBody = await second.json<{ submission_id: string; created: boolean }>();
    expect(secondBody.created).toBe(true);
    expect(secondBody.submission_id).toBe(firstBody.submission_id);
  });
});

// ---------------------------------------------------------------------------
// Database-level constraints (rules 3 & 4)
// ---------------------------------------------------------------------------

describe("database constraints reject what the model rejects", () => {
  it("rejects anchor.page < 1", async () => {
    const { runId } = await seedRun();
    await expect(
      rawInsert("findings", {
        id: crypto.randomUUID(),
        run_id: runId,
        ordinal: 0,
        finding_key: "C1",
        evidence: "{}",
        anchor_quote: "a real quote",
        anchor_page: 0,
      }),
    ).rejects.toThrow(/CHECK constraint failed: findings_page_ge1/);
  });

  it("rejects span end < start", async () => {
    const { runId } = await seedRun();
    await expect(
      rawInsert("findings", {
        id: crypto.randomUUID(),
        run_id: runId,
        ordinal: 0,
        finding_key: "C1",
        evidence: "{}",
        anchor_quote: "a real quote",
        span_start: 5,
        span_end: 3,
      }),
    ).rejects.toThrow(/CHECK constraint failed: findings_span_valid/);
  });

  it("rejects span start < 0", async () => {
    const { runId } = await seedRun();
    await expect(
      rawInsert("findings", {
        id: crypto.randomUUID(),
        run_id: runId,
        ordinal: 0,
        finding_key: "C1",
        evidence: "{}",
        anchor_quote: "a real quote",
        span_start: -1,
        span_end: 5,
      }),
    ).rejects.toThrow(/CHECK constraint failed: findings_span_valid/);
  });

  it("rejects an unknown verdict", async () => {
    const { runId } = await seedRun();
    await expect(
      rawInsert("findings", {
        id: crypto.randomUUID(),
        run_id: runId,
        ordinal: 0,
        finding_key: "C1",
        evidence: "{}",
        verdict: "maybe",
      }),
    ).rejects.toThrow(/CHECK constraint failed: findings_verdict_enum/);
  });

  it("rejects a status outside {ok, skipped, errored}", async () => {
    const { runId } = await seedRun();
    await expect(
      rawInsert("ledger_rows", {
        id: crypto.randomUUID(),
        run_id: runId,
        ordinal: 0,
        check_name: "some_check",
        status: "bogus",
        reason: "irrelevant — status itself is invalid",
      }),
    ).rejects.toThrow(/CHECK constraint failed: ledger_rows_status_enum/);
  });

  it("rejects a result present on a skipped row", async () => {
    const { runId } = await seedRun();
    await expect(
      rawInsert("ledger_rows", {
        id: crypto.randomUUID(),
        run_id: runId,
        ordinal: 0,
        check_name: "some_check",
        status: "skipped",
        result_kind: "bool",
        result_num: 1,
      }),
    ).rejects.toThrow(/CHECK constraint failed: ledger_rows_status_consistent/);
  });

  it("rejects a missing result on an ok row", async () => {
    const { runId } = await seedRun();
    await expect(
      rawInsert("ledger_rows", {
        id: crypto.randomUUID(),
        run_id: runId,
        ordinal: 0,
        check_name: "some_check",
        status: "ok",
      }),
    ).rejects.toThrow(/CHECK constraint failed: ledger_rows_status_consistent/);
  });

  it("rejects a missing reason on an errored row", async () => {
    const { runId } = await seedRun();
    await expect(
      rawInsert("ledger_rows", {
        id: crypto.randomUUID(),
        run_id: runId,
        ordinal: 0,
        check_name: "some_check",
        status: "errored",
      }),
    ).rejects.toThrow(/CHECK constraint failed: ledger_rows_status_consistent/);
  });

  it("rejects result_kind='bool' paired with a non-0/1 number", async () => {
    const { runId } = await seedRun();
    const findingId = await seedFinding(runId);
    await expect(
      rawInsert("finding_checks", {
        id: crypto.randomUUID(),
        finding_id: findingId,
        ordinal: 0,
        check_name: "pangram_span",
        status: "ok",
        result_kind: "bool",
        result_num: 0.98, // exactly the "score reads back as a pass" bug this column exists to prevent
      }),
    ).rejects.toThrow(/CHECK constraint failed: finding_checks_bool_domain/);
  });

  // --- Permissive cases: the model allows these, so the DB must too. ---

  it("accepts a reason present on an ok row (permitted by the model)", async () => {
    const { runId } = await seedRun();
    await expect(
      rawInsert("ledger_rows", {
        id: crypto.randomUUID(),
        run_id: runId,
        ordinal: 0,
        check_name: "some_check",
        status: "ok",
        result_kind: "bool",
        result_num: 1,
        reason: "an incidental note the model does not forbid",
      }),
    ).resolves.toBeDefined();
  });

  it("accepts duplicate finding ids within one run (the model does not enforce uniqueness)", async () => {
    const { runId } = await seedRun();
    await rawInsert("findings", {
      id: crypto.randomUUID(),
      run_id: runId,
      ordinal: 0,
      finding_key: "C1",
      evidence: "{}",
    });
    await rawInsert("findings", {
      id: crypto.randomUUID(),
      run_id: runId,
      ordinal: 1, // different ordinal — only finding_key repeats
      finding_key: "C1",
      evidence: "{}",
    });
    const { results } = await env.DB.prepare(
      "SELECT COUNT(*) as c FROM findings WHERE run_id = ? AND finding_key = 'C1'",
    )
      .bind(runId)
      .all<{ c: number }>();
    expect(results[0]?.c).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// Cascade delete
// ---------------------------------------------------------------------------

describe("cascade delete", () => {
  it("cascades a run delete to findings, finding_checks, and ledger_rows", async () => {
    const res = await post("/api/runs", freshFixture());
    expect(res.status).toBe(201);
    const { run_id } = await res.json<{ run_id: string }>();

    // Sanity: the fixture actually populated all three child tables, so the
    // cascade assertion below is meaningful and not vacuously true.
    expect(await tableCount("findings")).toBeGreaterThan(0);
    expect(await tableCount("finding_checks")).toBeGreaterThan(0);
    expect(await tableCount("ledger_rows")).toBeGreaterThan(0);

    await env.DB.prepare("DELETE FROM runs WHERE id = ?").bind(run_id).run();

    expect(await tableCount("findings")).toBe(0);
    expect(await tableCount("finding_checks")).toBe(0);
    expect(await tableCount("ledger_rows")).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Text is never stored
// ---------------------------------------------------------------------------

describe("document text is never stored", () => {
  it("does not persist the document body in any column of submissions", async () => {
    const res = await post("/api/runs", freshFixture());
    expect(res.status).toBe(201);

    // A long, distinctive substring of the fixture's document.text. If this
    // ever shows up in `submissions`, the text — not just its hash — leaked in.
    const distinctivePhrase =
      "Meridian will deliver twelve regional trainings, a 40-country monitoring network";
    expect(sample.document.text).toContain(distinctivePhrase); // sanity check on the fixture itself

    const { results } = await env.DB.prepare("SELECT * FROM submissions").all<Record<string, unknown>>();
    expect(results.length).toBeGreaterThan(0);
    for (const row of results) {
      for (const value of Object.values(row)) {
        if (typeof value === "string") {
          expect(value).not.toContain(distinctivePhrase);
        }
      }
    }
  });

  it("has no passed/failed/scores/skipped/errored column on any table", async () => {
    const forbidden = ["passed", "failed", "scores", "skipped", "errored"];
    const tables = ["submissions", "runs", "findings", "finding_checks", "ledger_rows"];
    for (const table of tables) {
      const { results } = await env.DB.prepare(`PRAGMA table_info(${table})`).all<{ name: string }>();
      const columnNames = results.map((r) => r.name.toLowerCase());
      for (const bad of forbidden) {
        expect(columnNames, `table ${table} column list: ${columnNames.join(", ")}`).not.toContain(bad);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

describe("routing", () => {
  it("does not let the runs handler swallow other /api/* paths", async () => {
    // /api/runs is WORKER_OWNED; every other /api/* path must reach the
    // Railway proxy, never handleRuns's own 404/405 responses. We can't
    // control the live upstream's exact reply, so accept either a response
    // that doesn't carry our handler's fingerprint, or a network error
    // (proof the request actually left the Worker rather than being
    // synthesized locally).
    let sawRunsHandlerShape = false;
    try {
      const res = await SELF.fetch(`${BASE}/api/some-other-endpoint`);
      const text = await res.text();
      sawRunsHandlerShape = text.includes('"run not found"') || text.includes("not allowed on");
    } catch {
      sawRunsHandlerShape = false; // network error: definitely not our handler
    }
    expect(sawRunsHandlerShape).toBe(false);
  });

  it("routes /api/runs itself to the local handler, not the proxy", async () => {
    const res = await get("/api/runs/definitely-not-a-real-id");
    expect(res.status).toBe(404);
    const body = await res.json<{ error: string }>();
    expect(body.error).toMatch(/not found/i); // our shape, not FastAPI's {"detail": "Not Found"}
  });

  it("serves non-/api paths from static assets, not the runs handler", async () => {
    const res = await get("/some-page-that-does-not-exist.html");
    const text = await res.text();
    expect(text).not.toContain('"run not found"');
    expect(res.headers.get("content-type") ?? "").not.toMatch(/application\/json/);
  });
});
