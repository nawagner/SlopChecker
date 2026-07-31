/**
 * Round-trip fidelity and ordering tests for /api/runs.
 *
 * Scope (see the task brief): a report POSTed to D1 must GET back byte-for-byte
 * equivalent (modulo `document.text`, which is never stored), in exactly the
 * order it was submitted, with optional fields staying absent when absent and
 * exact when present. This file does not test validation/rejection paths,
 * counts arithmetic, or anything outside that contract.
 */

import { env, SELF } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";

import fixture from "../../tests/fixtures/sample_report.json";

const BASE = "https://example.com";

async function post(report: unknown): Promise<any> {
  const res = await SELF.fetch(`${BASE}/api/runs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(report),
  });
  expect(res.status, `POST /api/runs should 201 for ${JSON.stringify(report).slice(0, 200)}`).toBe(
    201,
  );
  return res.json();
}

async function get(runId: string): Promise<any> {
  const res = await SELF.fetch(`${BASE}/api/runs/${runId}`);
  expect(res.status).toBe(200);
  return res.json();
}

/** Independent SHA-256 implementation (not imported from the codec under test). */
async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Recursively asserts no `null` appears anywhere in a JSON-shaped value. */
function assertNoNulls(value: unknown, path = "$"): void {
  if (value === null) throw new Error(`unexpected null at ${path}`);
  if (Array.isArray(value)) {
    value.forEach((v, i) => assertNoNulls(v, `${path}[${i}]`));
  } else if (typeof value === "object" && value !== undefined) {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      assertNoNulls(v, `${path}.${k}`);
    }
  }
}

beforeEach(async () => {
  // submissions cascades to runs -> findings -> finding_checks, and to ledger_rows.
  await env.DB.exec("DELETE FROM submissions");
});

describe("full fixture round-trip", () => {
  it("round-trips the full fixture exactly", async () => {
    const input = structuredClone(fixture);

    const posted = await post(input);
    const body = await get(posted.run_id);

    const reconstructed = structuredClone(body.report);
    // document.text is deliberately never stored; splice it back before comparing.
    expect(reconstructed.document.text).toBeUndefined();
    reconstructed.document.text = input.document.text;

    expect(reconstructed).toEqual(input);
  });
});

describe("ordering is contract data", () => {
  function orderedReport() {
    return {
      document: { file: "order.pdf", text: "Ordering test document body." },
      findings: [
        {
          id: "zeta",
          label: "Zeta finding",
          checks: [
            { name: "zzz_check", result: true },
            { name: "aaa_check", result: false },
            { name: "mmm_check", result: 0.5 },
          ],
        },
        {
          id: "alpha",
          label: "Alpha finding",
          checks: [
            { name: "second_check", result: true },
            { name: "first_check", result: 2 },
          ],
        },
        {
          id: "middle",
          label: "Middle finding",
          checks: [{ name: "solo_check", result: 1 }],
        },
      ],
      ledger: [
        { check: "zzz_ledger", result: true },
        { check: "aaa_ledger", result: false },
        { check: "mmm_ledger", result: 0.3 },
      ],
    };
  }

  it("returns findings in submitted order, not sorted by id", async () => {
    const posted = await post(orderedReport());
    const body = await get(posted.run_id);
    expect(body.report.findings.map((f: any) => f.id)).toEqual(["zeta", "alpha", "middle"]);
  });

  it("returns each finding's checks in submitted order, not sorted by name", async () => {
    const posted = await post(orderedReport());
    const body = await get(posted.run_id);
    const [zeta, alpha, middle] = body.report.findings;
    expect(zeta.checks.map((c: any) => c.name)).toEqual(["zzz_check", "aaa_check", "mmm_check"]);
    expect(alpha.checks.map((c: any) => c.name)).toEqual(["second_check", "first_check"]);
    expect(middle.checks.map((c: any) => c.name)).toEqual(["solo_check"]);
  });

  it("returns ledger rows in submitted order, not sorted by check name", async () => {
    const posted = await post(orderedReport());
    const body = await get(posted.run_id);
    expect(body.report.ledger.map((r: any) => r.check)).toEqual([
      "zzz_ledger",
      "aaa_ledger",
      "mmm_ledger",
    ]);
  });
});

describe("optional fields absent on input stay absent on output", () => {
  it("omits every unset optional key and never leaks a null", async () => {
    const input = {
      document: { file: "min.pdf", text: "Minimal text with no extras." },
      findings: [{ id: "F1", checks: [{ name: "only_check", result: true }] }],
      ledger: [{ check: "only_ledger", result: false }],
    };

    const posted = await post(input);
    const body = await get(posted.run_id);
    const report = body.report;

    assertNoNulls(report);

    expect(report).toEqual({
      schema_version: "0.1",
      document: { file: "min.pdf" }, // text spliced out separately below
      run: {},
      findings: [{ id: "F1", checks: [{ name: "only_check", result: true }] }],
      ledger: [{ check: "only_ledger", result: false }],
      summary: { recommendation: "human_review" },
    });

    // document.text is handled by its own dedicated test; confirm it's absent here too.
    expect("text" in report.document).toBe(false);
  });
});

describe("optional fields present on input round-trip with identical values", () => {
  it("preserves every optional field this fixture doesn't exercise", async () => {
    const input = {
      schema_version: "0.1",
      document: {
        file: "full-meta.pdf",
        text: "Full metadata document text for round-trip verification.",
        sha256: "abc123deadbeef",
        pages: 7,
        page_offsets: [0, 120, 340, 500],
        media_type: "application/pdf",
        title: 'A Title With "Quotes"',
        byline: "By Someone",
        submitter: "Org Name",
      },
      solicitation: "SOL-2099",
      run: { date: "2099-01-01", seconds: 12.5, version: "v9.9.9", cost_usd: 3.42 },
      findings: [
        {
          id: "V1",
          target: "para[3]",
          label: "Verdict test",
          anchor: { quote: "quoted text goes here" },
          checks: [{ name: "check_a", result: 1.5 }],
          verdict: "overstated",
          note: "single line note",
        },
      ],
      ledger: [
        { check: "ledger_a", label: "Ledger A label", result: true, detail: "some detail text" },
      ],
      summary: { recommendation: "human_review" },
    };

    const posted = await post(input);
    const body = await get(posted.run_id);

    const reconstructed = structuredClone(body.report);
    reconstructed.document.text = input.document.text;

    expect(reconstructed).toEqual(input);
  });
});

describe("anchor variants", () => {
  it("round-trips no-anchor, quote-only, quote+page, and quote+page+span(0,0)", async () => {
    const input = {
      document: { file: "anchors.pdf", text: "Anchor variants document body." },
      findings: [
        { id: "no-anchor" },
        { id: "quote-only", anchor: { quote: "just a quote" } },
        { id: "quote-page", anchor: { page: 3, quote: "quote with a page" } },
        {
          id: "quote-page-span-zero",
          anchor: { page: 5, quote: "quote with a zero span", span: { start: 0, end: 0 } },
        },
      ],
    };

    const posted = await post(input);
    const body = await get(posted.run_id);
    const byId = new Map(body.report.findings.map((f: any) => [f.id, f]));

    expect(byId.get("no-anchor")).toEqual({ id: "no-anchor", checks: [] });
    expect(byId.get("quote-only")).toEqual({
      id: "quote-only",
      anchor: { quote: "just a quote" },
      checks: [],
    });
    expect(byId.get("quote-page")).toEqual({
      id: "quote-page",
      anchor: { page: 3, quote: "quote with a page" },
      checks: [],
    });
    // The load-bearing case: start:0/end:0 must survive `?? null` chains that
    // would treat 0 as absent if written as `||` instead.
    expect(byId.get("quote-page-span-zero")).toEqual({
      id: "quote-page-span-zero",
      anchor: {
        page: 5,
        quote: "quote with a zero span",
        span: { start: 0, end: 0 },
      },
      checks: [],
    });
  });
});

describe("evidence round-trips as arbitrary nested JSON", () => {
  it("preserves nested arrays/objects/numbers/booleans/null and an empty {} inside it", async () => {
    const evidence = {
      doi: "10.1234/xyz",
      resolved: true,
      failed_lookup: false,
      score: 0.987,
      count: 0,
      note: "",
      a_null: null,
      scores: [0.1, 0.98, true, false, null, {}],
      nested: { a: { b: {}, c: [1, 2, 3] }, list: [], empty_obj: {} },
    };
    const input = {
      document: { file: "evidence.pdf", text: "Evidence round-trip document body." },
      findings: [{ id: "E1", checks: [{ name: "c", result: true }], evidence }],
    };

    const posted = await post(input);
    const body = await get(posted.run_id);
    const finding = body.report.findings.find((f: any) => f.id === "E1");

    expect(finding.evidence).toEqual(evidence);
  });
});

describe("unicode and special characters", () => {
  const weirdQuote =
    'He said “trust the process” — 100% \\ verified 🔥\nline two with a "straight quote" and back\\slash.';

  it("round-trips unicode/newlines/quotes/backslashes in quote and metadata fields", async () => {
    const input = {
      document: {
        file: "unicode-☂.pdf",
        text: `Intro. ${weirdQuote} Conclusion. 😀`,
        title: "Title with emoji 🚀 and “curly quotes”",
        byline: "Ünïcödé ǎample",
        submitter: 'Org "Name" & Co.',
      },
      findings: [
        {
          id: "U1",
          anchor: { quote: weirdQuote },
          checks: [{ name: "unicode_check", result: true }],
        },
      ],
    };

    const posted = await post(input);
    const body = await get(posted.run_id);

    expect(body.report.document.title).toBe(input.document.title);
    expect(body.report.document.byline).toBe(input.document.byline);
    expect(body.report.document.submitter).toBe(input.document.submitter);
    const finding = body.report.findings.find((f: any) => f.id === "U1");
    expect(finding.anchor.quote).toBe(weirdQuote);

    const expectedSha = await sha256Hex(input.document.text);
    expect(posted.text_sha256).toBe(expectedSha);
    expect(body.text_sha256).toBe(expectedSha);
  });
});

describe("document.text is never stored or returned", () => {
  it("omits document.text from the reconstructed report", async () => {
    const input = {
      document: { file: "no-text-leak.pdf", text: "A distinctive marker string ZQXJ19." },
    };
    const posted = await post(input);
    const body = await get(posted.run_id);

    expect("text" in body.report.document).toBe(false);
    expect(JSON.stringify(body.report)).not.toContain("ZQXJ19");
  });

  it("computes text_length using UTF-16 code units, not bytes or code points", async () => {
    // "abc\u{1F600}def": 3 ascii + 1 astral emoji (surrogate pair, 2 code units) + 3 ascii.
    // JS .length -> 8. UTF-8 byte length -> 10. Code-point count (Array.from) -> 7.
    // All three disagree, so this pins down which counting method is in use.
    const text = "abc😀def";
    expect(text.length).toBe(8);

    const input = { document: { file: "emoji.pdf", text } };
    const posted = await post(input);
    const body = await get(posted.run_id);

    expect(posted.text_length).toBe(8);
    expect(body.text_length).toBe(8);
  });
});

describe("GET /api/runs?text_sha256=", () => {
  it("filters to the matching submission and orders newest run first", async () => {
    // Same document text+metadata (same submission), different report content
    // (different run.seconds) so each POST creates a distinct run rather than
    // being deduped as an identical retry.
    const docA = { file: "a.pdf", text: "TEXT-A shared across two runs." };
    const reportA1 = { document: docA, run: { seconds: 1 } };
    const reportA2 = { document: docA, run: { seconds: 2 } };
    const reportB = { document: { file: "b.pdf", text: "TEXT-B, a different submission." } };

    const postedA1 = await post(reportA1);
    await sleep(5);
    const postedA2 = await post(reportA2);
    await sleep(5);
    await post(reportB);

    expect(postedA1.submission_id).toBe(postedA2.submission_id);
    expect(postedA1.text_sha256).toBe(postedA2.text_sha256);

    const res = await SELF.fetch(
      `${BASE}/api/runs?text_sha256=${postedA1.text_sha256}`,
    );
    expect(res.status).toBe(200);
    const listBody = await res.json<any>();

    expect(listBody.runs.map((r: any) => r.run_id)).toEqual([postedA2.run_id, postedA1.run_id]);
  });
});
