/**
 * Acceptance tests for the D1 report store.
 *
 * The headline test is the round-trip: POST the real fixture, GET it back,
 * assert deep equality. Vitest's `toEqual` is key-order-insensitive but
 * array-order-sensitive, which is exactly the contract — it proves `ordinal`
 * works on findings/ledger/checks while tolerating harmless key reordering.
 *
 * Why that's sufficient to prove pydantic will accept the output: the fixture
 * already validates (tests/test_models.py), and the output deep-equals the
 * fixture, so the output validates. No cross-language harness needed.
 */

import { env, SELF } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";

import fixtureJson from "../../tests/fixtures/sample_report.json";

// Cloned per access: tests splice `document.text` back in, and a shared module
// object would leak that mutation into the next test.
const fixtureSource = fixtureJson as unknown as Record<string, any>;
const loadFixture = () => structuredClone(fixtureSource);
const fixture = loadFixture();

const post = (body: unknown) =>
  SELF.fetch("https://example.com/api/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });

const get = (id: string) => SELF.fetch(`https://example.com/api/runs/${id}`);

/** Tests share one D1 instance; clear it so ordering can't couple them. */
beforeEach(async () => {
  // ON DELETE CASCADE clears runs -> findings -> finding_checks and ledger_rows.
  await env.DB.exec("DELETE FROM submissions");
});

describe("POST /api/runs", () => {
  it("round-trips the sample report losslessly", async () => {
    const res = await post(fixture);
    expect(res.status).toBe(201);
    const { run_id, created, counts } = await res.json<any>();
    expect(created).toBe(true);

    // Matches EvidenceReport.counts() for this fixture.
    expect(counts).toEqual({ passed: 2, failed: 5, scores: 2, skipped: 1, errored: 0 });

    const back = await get(run_id);
    expect(back.status).toBe(200);
    const payload = await back.json<any>();

    // document.text never enters D1 by design — splice it back to compare.
    const report = payload.report;
    expect(report.document.text).toBeUndefined();
    const expected = loadFixture();
    report.document.text = expected.document.text;

    expect(report).toEqual(expected);
  });

  it("keeps booleans and numbers in separate lanes", async () => {
    // The fixture has no integer result, so it cannot catch the bug this
    // column exists to prevent. This is that test.
    const probe = {
      schema_version: "0.1",
      document: { file: "probe.pdf", text: "probe" },
      ledger: [
        { check: "bool_true", result: true },
        { check: "bool_false", result: false },
        { check: "int_one", result: 1 },
        { check: "int_zero", result: 0 },
        { check: "float_mid", result: 0.5 },
      ],
      summary: { recommendation: "human_review" },
    };
    const { run_id, counts } = await (await post(probe)).json<any>();

    // 1 and 0 are SCORES, not a pass and a fail.
    expect(counts).toEqual({ passed: 1, failed: 1, scores: 3, skipped: 0, errored: 0 });

    const { report } = await (await get(run_id)).json<any>();
    const byName = Object.fromEntries(report.ledger.map((r: any) => [r.check, r.result]));

    expect(byName.bool_true).toBe(true);
    expect(byName.bool_false).toBe(false);
    expect(byName.int_one).toBe(1);
    expect(byName.int_one).not.toBe(true); // the bug this all exists to prevent
    expect(byName.int_zero).toBe(0);
    expect(byName.int_zero).not.toBe(false);
    expect(byName.float_mid).toBe(0.5);
  });

  it("preserves coverage gaps as gaps, with no result", async () => {
    const probe = {
      document: { file: "gaps.pdf", text: "gaps" },
      ledger: [
        { check: "skipped_one", status: "skipped", reason: "no API key" },
        { check: "errored_one", status: "errored", reason: "upstream 503" },
      ],
      summary: { recommendation: "human_review" },
    };
    const { run_id, counts } = await (await post(probe)).json<any>();
    expect(counts).toEqual({ passed: 0, failed: 0, scores: 0, skipped: 1, errored: 1 });

    const { report } = await (await get(run_id)).json<any>();
    expect(report.ledger[0]).toEqual({
      check: "skipped_one",
      status: "skipped",
      reason: "no API key",
    });
    expect(report.ledger[0].result).toBeUndefined();
  });

  it("is idempotent — a retried POST returns the same run", async () => {
    const first = await (await post(fixture)).json<any>();
    const second = await post(fixture);
    expect(second.status).toBe(200);
    const body = await second.json<any>();
    expect(body.created).toBe(false);
    expect(body.run_id).toBe(first.run_id);

    const { results } = await env.DB.prepare("SELECT COUNT(*) AS n FROM runs").all();
    expect((results[0] as any).n).toBe(1);
  });

  it("rejects a non-boolean, non-numeric result with the offending path", async () => {
    const res = await post({
      document: { file: "x.pdf", text: "x" },
      ledger: [{ check: "bad", result: "definitely-true" }],
    });
    expect(res.status).toBe(400);
    expect(await res.json<any>()).toMatchObject({ path: "ledger[0].result" });
  });

  it("rejects malformed JSON without a 500", async () => {
    const res = await post("{not json");
    expect(res.status).toBe(400);
  });

  it("409s when the same text arrives with different metadata", async () => {
    await post({ document: { file: "a.pdf", text: "same text" } });
    const res = await post({ document: { file: "b.pdf", text: "same text" } });
    expect(res.status).toBe(409);
    expect((await res.json<any>()).fields).toContain("file");
  });
});

describe("the storage rules the schema exists to enforce", () => {
  it("never stores document.text", async () => {
    await post(fixture);
    const { results } = await env.DB.prepare("SELECT * FROM submissions").all();
    const row = JSON.stringify(results[0]);
    // A distinctive phrase from the fixture's body text.
    expect(row).not.toContain("coordinated inauthentic behavior");
    expect((results[0] as any).text_length).toBe(fixture.document.text.length);
  });

  it("never stores derived counts as columns", async () => {
    // #3: counts are derived from the ledger, never stored. A column would drift.
    for (const table of ["runs", "ledger_rows", "submissions"]) {
      const { results } = await env.DB.prepare(`PRAGMA table_info(${table})`).all();
      const columns = results.map((c: any) => c.name);
      for (const forbidden of ["passed", "failed", "scores", "skipped", "errored"]) {
        expect(columns).not.toContain(forbidden);
      }
    }
  });

  it("cascades deletes from runs to every child table", async () => {
    const { run_id } = await (await post(fixture)).json<any>();
    await env.DB.prepare("DELETE FROM runs WHERE id = ?").bind(run_id).run();

    for (const table of ["findings", "finding_checks", "ledger_rows"]) {
      const { results } = await env.DB.prepare(`SELECT COUNT(*) AS n FROM ${table}`).all();
      expect((results[0] as any).n, `${table} should be empty`).toBe(0);
    }
  });

  it("rejects a score masquerading as a boolean at the database level", async () => {
    await env.DB.prepare(
      "INSERT INTO submissions (id,text_sha256,text_length,file,created_at) VALUES ('s','h',1,'f',1)",
    ).run();
    await env.DB.prepare(
      "INSERT INTO runs (id,submission_id,report_sha256,schema_version,recommendation,created_at) VALUES ('r','s','rh','0.1','human_review',1)",
    ).run();

    await expect(
      env.DB.prepare(
        "INSERT INTO ledger_rows (id,run_id,ordinal,check_name,result_kind,result_num,status) VALUES ('l','r',0,'c','bool',0.96,'ok')",
      ).run(),
    ).rejects.toThrow(/CHECK constraint failed/);
  });
});

describe("routing", () => {
  it("does not swallow the Railway proxy paths", async () => {
    // /api/runs is Worker-owned; everything else under /api/ must still be
    // proxied. Without RAILWAY_API_URL bound in tests that surfaces as a 502,
    // which is enough to prove the request was NOT handled by the D1 route.
    const res = await SELF.fetch("https://example.com/api/health");
    expect(res.status).not.toBe(404);
    expect([502, 200, 503]).toContain(res.status);
  });

  it("405s on an unsupported method", async () => {
    const res = await SELF.fetch("https://example.com/api/runs", { method: "DELETE" });
    expect(res.status).toBe(405);
  });
});
