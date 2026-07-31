/**
 * report.json <-> D1 rows.
 *
 * The whole bool-vs-number problem lives in `encodeResult`/`decodeResult` —
 * eight lines each way, and everything else in the codebase can stay ignorant
 * of it. See schema.ts for why `result_kind` exists at all.
 *
 * Shape validation here is deliberately hand-rolled rather than zod: the
 * authoritative validator is pydantic (`models.py`, extra="forbid"). All this
 * needs to do is turn a malformed payload into a 400 naming the offending JSON
 * path, instead of letting a CHECK constraint surface as an opaque 500.
 */

import type { CheckStatus, ResultKind, VerdictName } from "./schema";

/** A shape violation in the posted report. Carries the JSON path that failed. */
export class BadReport extends Error {
  constructor(
    message: string,
    readonly path: string,
  ) {
    super(message);
    this.name = "BadReport";
  }
}

/** models.py `Result = StrictBool | StrictInt | StrictFloat` */
export type ReportResult = boolean | number;

export interface CheckResultInput {
  name: string;
  result?: ReportResult | null;
  status?: CheckStatus;
  reason?: string | null;
}

export interface FindingInput {
  id: string;
  target?: string | null;
  label?: string | null;
  anchor?: { page?: number | null; quote: string; span?: { start: number; end: number } | null };
  checks?: CheckResultInput[];
  verdict?: VerdictName | null;
  evidence?: Record<string, unknown>;
  note?: string | null;
}

export interface LedgerRowInput {
  check: string;
  label?: string | null;
  result?: ReportResult | null;
  detail?: string | null;
  status?: CheckStatus;
  reason?: string | null;
}

export interface DocumentInput {
  file: string;
  text: string;
  sha256?: string | null;
  pages?: number | null;
  page_offsets?: number[] | null;
  media_type?: string | null;
  title?: string | null;
  byline?: string | null;
  submitter?: string | null;
}

export interface ReportInput {
  schema_version?: string;
  document: DocumentInput;
  solicitation?: string | null;
  run?: {
    date?: string | null;
    seconds?: number | null;
    version?: string | null;
    cost_usd?: number | null;
  };
  findings?: FindingInput[];
  ledger?: LedgerRowInput[];
  summary?: { recommendation?: string };
}

/**
 * Split a report result into its (kind, number) pair.
 *
 * `true` -> ('bool', 1) and `1` -> ('number', 1). Same stored number, different
 * kind — which is the entire point: `EvidenceReport.counts()` and the
 * renderer's lanes treat a boolean as pass/fail and a number as a score.
 */
export function encodeResult(
  value: unknown,
  path: string,
): { kind: ResultKind | null; num: number | null } {
  if (value === undefined || value === null) return { kind: null, num: null };
  if (typeof value === "boolean") return { kind: "bool", num: value ? 1 : 0 };
  // Mirrors StrictInt|StrictFloat: NaN/Infinity aren't valid JSON numbers and
  // would silently become NULL in SQLite.
  if (typeof value === "number" && Number.isFinite(value)) return { kind: "number", num: value };
  throw new BadReport(`result must be a boolean or a finite number, got ${typeof value}`, path);
}

/**
 * Rebuild a report result from its stored pair.
 *
 * Returns `undefined` (not `null`) when absent, so `JSON.stringify` omits the
 * key — matching pydantic's `exclude_none=True` on the way out.
 *
 * The ternary is the one line that keeps a score of 1.0 from reading back as a
 * passing `true`.
 */
export function decodeResult(
  kind: string | null,
  num: number | null,
): ReportResult | undefined {
  if (kind === null || num === null) return undefined;
  return kind === "bool" ? num === 1 : num;
}

/** Hex SHA-256 via WebCrypto — available in workerd with no dependency. */
export async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Serialize with object keys sorted recursively, so two payloads that differ
 * only in formatting hash identically.
 *
 * `JSON.stringify` alone is not enough for that: it collapses whitespace but
 * preserves each object's own key *insertion* order. So a producer that emits
 * `{"document":…,"schema_version":…}` and one that emits the same report with
 * those two keys swapped would hash differently and create a duplicate run.
 * Pydantic serializes in field-definition order, so a single producer is
 * self-consistent — but "the same report from a different code path" is
 * exactly the retry case idempotency exists to absorb.
 *
 * Arrays are NOT reordered. List order is contract data (`findings`, `ledger`,
 * and each finding's `checks` are ordered), so two reports differing in array
 * order are genuinely different reports and must hash differently.
 */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined) // matches JSON.stringify's own omission
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonicalJson(v)}`).join(",")}}`;
}

/**
 * Minimum shape needed to store a report without tripping a CHECK constraint.
 *
 * Intentionally not a full re-implementation of models.py — it validates what
 * the database is about to enforce anyway, so the caller gets a useful 400.
 */
export function validateReport(value: unknown): ReportInput {
  const isObj = (v: unknown): v is Record<string, unknown> =>
    typeof v === "object" && v !== null && !Array.isArray(v);

  if (!isObj(value)) throw new BadReport("report must be a JSON object", "$");
  const doc = value.document;
  if (!isObj(doc)) throw new BadReport("document is required", "document");
  if (typeof doc.file !== "string") throw new BadReport("document.file must be a string", "document.file");
  if (typeof doc.text !== "string") throw new BadReport("document.text must be a string", "document.text");

  const findings = value.findings ?? [];
  if (!Array.isArray(findings)) throw new BadReport("findings must be an array", "findings");
  findings.forEach((f, i) => {
    if (!isObj(f)) throw new BadReport("finding must be an object", `findings[${i}]`);
    if (typeof f.id !== "string") throw new BadReport("finding.id must be a string", `findings[${i}].id`);
    const checks = f.checks ?? [];
    if (!Array.isArray(checks)) throw new BadReport("checks must be an array", `findings[${i}].checks`);
    checks.forEach((c, j) => {
      const p = `findings[${i}].checks[${j}]`;
      if (!isObj(c)) throw new BadReport("check must be an object", p);
      if (typeof c.name !== "string") throw new BadReport("check.name must be a string", `${p}.name`);
      encodeResult(c.result, `${p}.result`); // throws BadReport on a bad type
    });
  });

  const ledger = value.ledger ?? [];
  if (!Array.isArray(ledger)) throw new BadReport("ledger must be an array", "ledger");
  ledger.forEach((row, i) => {
    const p = `ledger[${i}]`;
    if (!isObj(row)) throw new BadReport("ledger row must be an object", p);
    if (typeof row.check !== "string") throw new BadReport("ledger.check must be a string", `${p}.check`);
    encodeResult(row.result, `${p}.result`);
  });

  return value as unknown as ReportInput;
}

/** Drop `undefined` values so JSON.stringify reproduces `exclude_none=True`. */
export function compact<T extends Record<string, unknown>>(obj: T): T {
  for (const key of Object.keys(obj)) {
    if (obj[key] === undefined) delete obj[key];
  }
  return obj;
}
