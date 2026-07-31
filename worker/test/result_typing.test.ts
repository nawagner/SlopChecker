/**
 * Result typing and derived counts (issue #3 / schema.ts rules 2 and 4).
 *
 * Two contract rules, tested from the outside (POST/GET the JSON, never
 * import codec.ts directly — a bug in the wire format is only real if the
 * HTTP boundary exposes it):
 *
 *   - A check result is `true`, `false`, or a number, and the kind travels
 *     with the value all the way through SQLite's 1/0 collapse. A score of
 *     1 must never read back as `true`.
 *   - `counts` (passed/failed/scores/skipped/errored) is derived from the
 *     ledger ONLY, on every read, never stored as a column.
 *
 * Several tests also peek at the raw D1 row (`result_kind`/`result_num`)
 * rather than trusting the JSON round-trip alone — a decode bug that
 * happens to cancel out on the way back out would otherwise hide here.
 */

import { env, SELF } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";

import fixtureJson from "../../tests/fixtures/sample_report.json";

const fixtureSource = fixtureJson as unknown as Record<string, any>;
const loadFixture = () => structuredClone(fixtureSource);

const post = (body: unknown) =>
  SELF.fetch("https://example.com/api/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });

const get = (id: string) => SELF.fetch(`https://example.com/api/runs/${id}`);

/** A minimal, valid report with an empty ledger/findings — each test fills in only what it needs. */
function baseReport(): Record<string, any> {
  const r = loadFixture();
  r.findings = [];
  r.ledger = [];
  return r;
}

/** Storage-level read, bypassing decodeResult entirely — proves what actually landed in the row. */
async function storedLedgerRow(runId: string, checkName: string) {
  const { results } = await env.DB.prepare(
    "SELECT result_kind, result_num FROM ledger_rows WHERE run_id = ? AND check_name = ?",
  )
    .bind(runId, checkName)
    .all();
  return results[0] as { result_kind: string | null; result_num: number | null };
}

/** Tests share one D1 instance; clear it so ordering can't couple them. */
beforeEach(async () => {
  // ON DELETE CASCADE clears runs -> findings -> finding_checks and ledger_rows.
  await env.DB.exec("DELETE FROM submissions");
});

describe("result typing: bool vs number survives storage", () => {
  it("true and false round-trip as JSON booleans, not 1/0", async () => {
    const report = baseReport();
    report.ledger = [
      { check: "bool_true", result: true },
      { check: "bool_false", result: false },
    ];

    const postRes = await post(report);
    expect(postRes.status).toBe(201);
    const { run_id } = await postRes.json<any>();

    // Storage layer: kind must say 'bool', never 'number', for a boolean input.
    expect(await storedLedgerRow(run_id, "bool_true")).toEqual({ result_kind: "bool", result_num: 1 });
    expect(await storedLedgerRow(run_id, "bool_false")).toEqual({ result_kind: "bool", result_num: 0 });

    // API layer: the reconstructed report must hand back real booleans.
    const { report: got } = await (await get(run_id)).json<any>();
    const byCheck = Object.fromEntries(got.ledger.map((r: any) => [r.check, r.result]));
    expect(byCheck.bool_true).toBe(true);
    expect(typeof byCheck.bool_true).toBe("boolean");
    expect(byCheck.bool_false).toBe(false);
    expect(typeof byCheck.bool_false).toBe("boolean");
  });

  it("integer results 1 and 0 round-trip as numbers, never as true/false", async () => {
    const report = baseReport();
    report.ledger = [
      { check: "score_one", result: 1 },
      { check: "score_zero", result: 0 },
    ];

    const postRes = await post(report);
    expect(postRes.status).toBe(201);
    const { run_id } = await postRes.json<any>();

    expect((await storedLedgerRow(run_id, "score_one")).result_kind).toBe("number");
    expect((await storedLedgerRow(run_id, "score_zero")).result_kind).toBe("number");

    const { report: got } = await (await get(run_id)).json<any>();
    const byCheck = Object.fromEntries(got.ledger.map((r: any) => [r.check, r.result]));

    // The load-bearing assertion is `typeof`, not just `===`: `1 === true` is
    // already false in JS, but `toBe(1)` alone wouldn't catch a decode that
    // mistakenly hands back the boolean `true` for a bool-kind row that
    // happens to share the number 1 — checking both value AND type closes
    // that gap explicitly.
    expect(byCheck.score_one).toBe(1);
    expect(typeof byCheck.score_one).toBe("number");
    expect(byCheck.score_one).not.toBe(true);
    expect(byCheck.score_zero).toBe(0);
    expect(typeof byCheck.score_zero).toBe("number");
    expect(byCheck.score_zero).not.toBe(false);
  });

  it("float results (0.0, 0.5, negative) round-trip exactly and stay numbers", async () => {
    const report = baseReport();
    report.ledger = [
      { check: "float_zero", result: 0.0 },
      { check: "float_half", result: 0.5 },
      { check: "float_negative", result: -3.25 },
    ];

    const postRes = await post(report);
    expect(postRes.status).toBe(201);
    const { run_id } = await postRes.json<any>();

    const { report: got } = await (await get(run_id)).json<any>();
    const byCheck = Object.fromEntries(got.ledger.map((r: any) => [r.check, r.result]));

    // 0.0 is the sharp edge: it's a NUMBER-kind result whose value is falsy in
    // JS, so a decode that does `Boolean(num)` instead of switching on kind
    // would silently turn this into `false`.
    expect(byCheck.float_zero).toBe(0);
    expect(typeof byCheck.float_zero).toBe("number");
    expect(byCheck.float_half).toBe(0.5);
    expect(byCheck.float_negative).toBe(-3.25);
  });

  it('rejects a string result like "true" with 400 instead of coercing it', async () => {
    const report = baseReport();
    report.ledger = [{ check: "stringly_typed", result: "true" }];

    const res = await post(report);
    expect(res.status).toBe(400);
    const body = await res.json<any>();
    expect(body.path).toBe("ledger[0].result");

    // Nothing should have been written for a rejected report.
    const { results } = await env.DB.prepare("SELECT COUNT(*) AS n FROM runs").all();
    expect((results[0] as any).n).toBe(0);
  });
});

describe("derived counts", () => {
  it("tallies passed/failed/scores/skipped/errored across a mixed ledger", async () => {
    const report = baseReport();
    report.ledger = [
      { check: "b1", result: true },
      { check: "b2", result: true },
      { check: "b3", result: false },
      { check: "n1", result: 1 }, // a numeric 1 must land in scores, NOT passed
      { check: "n2", result: 0.5 },
      { check: "s1", status: "skipped", reason: "no API key configured" },
      { check: "e1", status: "errored", reason: "upstream timeout" },
    ];

    const postRes = await post(report);
    expect(postRes.status).toBe(201);
    const posted = await postRes.json<any>();
    const expected = { passed: 2, failed: 1, scores: 2, skipped: 1, errored: 1 };
    expect(posted.counts).toEqual(expected);

    // GET must agree with POST's own counts — same derivation, same result.
    const got = await (await get(posted.run_id)).json<any>();
    expect(got.counts).toEqual(expected);
  });

  it("returns all-zero counts for an empty ledger", async () => {
    const report = baseReport();
    // Findings still has checks — this doubles as half of the "ledger only"
    // proof below, since an all-zero result here rules out findings leaking in.
    report.findings = [{ id: "F1", checks: [{ name: "x", result: true }] }];

    const postRes = await post(report);
    expect(postRes.status).toBe(201);
    const posted = await postRes.json<any>();
    expect(posted.counts).toEqual({ passed: 0, failed: 0, scores: 0, skipped: 0, errored: 0 });
  });

  it("counts a repeated check name once per ledger row, never deduped by name", async () => {
    const report = baseReport();
    report.ledger = [
      { check: "dupe", result: true },
      { check: "dupe", result: 0.5 },
      { check: "dupe", result: false },
    ];

    const postRes = await post(report);
    expect(postRes.status).toBe(201);
    const posted = await postRes.json<any>();
    expect(posted.counts).toEqual({ passed: 1, failed: 1, scores: 1, skipped: 0, errored: 0 });
  });

  it("computes counts over the ledger only — findings' checks never leak in", async () => {
    const report = baseReport();
    report.ledger = [{ check: "only_ledger_check", result: true }];
    // Deliberately larger and lopsided than the ledger so any leakage shows up
    // clearly in the assertion rather than by coincidence.
    report.findings = [
      {
        id: "F1",
        checks: [
          { name: "a", result: true },
          { name: "b", result: true },
          { name: "c", result: false },
          { name: "d", result: 0.9 },
          { name: "e", status: "skipped", reason: "n/a" },
        ],
      },
    ];

    const postRes = await post(report);
    expect(postRes.status).toBe(201);
    const posted = await postRes.json<any>();
    expect(posted.counts).toEqual({ passed: 1, failed: 0, scores: 0, skipped: 0, errored: 0 });
  });
});

describe("coverage gaps: skipped/errored", () => {
  it("skipped and errored rows carry a reason, no result, and are excluded from pass/fail/score", async () => {
    const report = baseReport();
    report.ledger = [
      { check: "plagiarism_scan", status: "skipped", reason: "no API key configured" },
      { check: "similarity_check", status: "errored", reason: "upstream 500" },
    ];

    const postRes = await post(report);
    expect(postRes.status).toBe(201);
    const { run_id, counts } = await postRes.json<any>();
    expect(counts).toEqual({ passed: 0, failed: 0, scores: 0, skipped: 1, errored: 1 });

    const { report: got } = await (await get(run_id)).json<any>();
    const skipped = got.ledger.find((r: any) => r.check === "plagiarism_scan");
    const errored = got.ledger.find((r: any) => r.check === "similarity_check");

    // "no result" means the key is absent, not present-and-null — compact()
    // drops undefined keys the way pydantic's exclude_none does.
    expect("result" in skipped).toBe(false);
    expect(skipped.reason).toBe("no API key configured");
    expect(skipped.status).toBe("skipped");

    expect("result" in errored).toBe(false);
    expect(errored.reason).toBe("upstream 500");
    expect(errored.status).toBe("errored");
  });

  it('omits status "ok" from serialized output — it is the default, not a value', async () => {
    const report = baseReport();
    report.ledger = [
      { check: "explicit_ok", result: true, status: "ok" }, // status given explicitly
      { check: "implicit_ok", result: false }, // status omitted entirely (same default)
    ];

    const postRes = await post(report);
    expect(postRes.status).toBe(201);
    const { run_id } = await postRes.json<any>();

    const { report: got } = await (await get(run_id)).json<any>();
    const explicit = got.ledger.find((r: any) => r.check === "explicit_ok");
    const implicit = got.ledger.find((r: any) => r.check === "implicit_ok");

    expect("status" in explicit).toBe(false);
    expect("status" in implicit).toBe(false);
    // Sanity: both still carry their (very much present) results, so the
    // missing key above is really about status, not a wholesale drop.
    expect(explicit.result).toBe(true);
    expect(implicit.result).toBe(false);
  });
});
