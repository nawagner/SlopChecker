/**
 * D1 schema — the source of truth. `npm run db:generate` turns this into
 * versioned SQL in ./migrations; `wrangler d1 migrations apply` runs it.
 *
 * Mirrors src/slopchecker/models.py (#3). Four rules are baked in here, and
 * every non-obvious column below exists to serve one of them:
 *
 *   1. D1 accepts exactly what models.py accepts. Every CHECK mirrors a
 *      pydantic constraint; none is stricter. A report that validates must be
 *      storable, or D1 becomes a second, competing contract.
 *   2. Derived counts are NEVER columns (#3; models.py `EvidenceReport.counts`).
 *      They're a view — a view can't drift from the ledger, a column can.
 *   3. FlattenedDoc.text is NEVER stored. 30-80 KB/doc is R2's job
 *      (docs/data-storage.md). We keep sha256 + length; that IS the seam.
 *   4. List order is contract data, so every child table carries `ordinal`
 *      and every read must ORDER BY it.
 *
 * `check` is a SQL reserved word — the column is `check_name`.
 */

import { sql } from "drizzle-orm";
import {
  check,
  index,
  integer,
  real,
  sqliteTable,
  text,
  uniqueIndex,
} from "drizzle-orm/sqlite-core";

/** models.py: `CheckStatus = Literal["ok", "skipped", "errored"]` */
export const CHECK_STATUSES = ["ok", "skipped", "errored"] as const;
export type CheckStatus = (typeof CHECK_STATUSES)[number];

/** models.py: `Verdict` — a closed enum, never free text. */
export const VERDICTS = [
  "supported",
  "overstated",
  "unsupported",
  "contradicted",
  "unverifiable",
] as const;
export type VerdictName = (typeof VERDICTS)[number];

/**
 * models.py: `Result = StrictBool | StrictInt | StrictFloat`.
 *
 * SQLite collapses booleans to 1/0, so a bare `result REAL` column would turn
 * a Pangram score of 1.0 into a PASS: `EvidenceReport.counts()` keys off
 * `r is True` / `isinstance(r, bool)`, and the renderer's red/green/purple
 * lanes follow the same distinction. So the kind travels beside the number and
 * is CHECK-enforced at the database level rather than by convention.
 *
 * Two values, not three ('bool' | 'int' | 'float'), because the int/float split
 * is unrepresentable at the JSON boundary in BOTH directions: JSON.parse("1.0")
 * and JSON.parse("1") produce the same JS number, and JSON.stringify(1.0) is
 * "1". A three-valued kind would be a column we could neither fill correctly
 * nor use. Consequence, documented in docs/d1-database.md: a stored 1.0 reads
 * back as 1 — still a SCORE, never a PASS. The lane is what's load-bearing,
 * and the lane is exact.
 */
export const RESULT_KINDS = ["bool", "number"] as const;
export type ResultKind = (typeof RESULT_KINDS)[number];

/** Shared by finding_checks and ledger_rows — identical semantics in models.py. */
const resultColumns = {
  resultKind: text("result_kind").$type<ResultKind>(),
  resultNum: real("result_num"),
  status: text("status").$type<CheckStatus>().notNull().default("ok"),
  reason: text("reason"),
};

type ResultCols = {
  resultKind: unknown;
  resultNum: unknown;
  status: unknown;
  reason: unknown;
};

/**
 * The CHECK constraints shared by finding_checks and ledger_rows.
 *
 * `prefix` keeps constraint names unique across tables — SQLite scopes them
 * per-table, but distinct names make a violation message say which table.
 */
const resultChecks = (prefix: string, t: ResultCols) => [
  check(`${prefix}_status_enum`, sql`${t.status} IN ('ok','skipped','errored')`),
  check(
    `${prefix}_result_kind_enum`,
    sql`${t.resultKind} IS NULL OR ${t.resultKind} IN ('bool','number')`,
  ),
  // A result is present as a (kind, num) pair or not at all — never half.
  check(`${prefix}_result_paired`, sql`(${t.resultKind} IS NULL) = (${t.resultNum} IS NULL)`),
  // Nothing can masquerade as a boolean.
  check(`${prefix}_bool_domain`, sql`${t.resultKind} <> 'bool' OR ${t.resultNum} IN (0, 1)`),
  // Mirrors CheckResult._status_consistent / LedgerRow._status_consistent:
  // ok => a result; not-ok => a reason and NO result. Deliberately does NOT
  // forbid a reason on an ok row, because pydantic permits that.
  check(
    `${prefix}_status_consistent`,
    sql`(${t.status} = 'ok' AND ${t.resultKind} IS NOT NULL) OR (${t.status} <> 'ok' AND ${t.resultKind} IS NULL AND ${t.reason} IS NOT NULL)`,
  ),
];

/**
 * One document under review — `FlattenedDoc` minus `text`.
 *
 * Deduped on `text_sha256`, which the Worker computes from `document.text` via
 * WebCrypto and never trusts from the payload. Insert-if-absent, never update:
 * the writer 409s on metadata divergence rather than silently reusing a row
 * whose title/byline differ, so a stored row can never contradict the report
 * you read back. Same "fail loudly at the boundary" instinct as extra="forbid".
 *
 * `file_sha256` is `FlattenedDoc.sha256` — the SOURCE FILE hash, round-tripped
 * verbatim. Distinct from `text_sha256`, which is ours and hashes the
 * normalized text. Don't conflate them.
 */
export const submissions = sqliteTable(
  "submissions",
  {
    id: text("id").primaryKey(),
    textSha256: text("text_sha256").notNull(),
    textLength: integer("text_length").notNull(),
    file: text("file").notNull(),
    fileSha256: text("file_sha256"),
    pages: integer("pages"),
    pageOffsets: text("page_offsets", { mode: "json" }).$type<number[]>(),
    mediaType: text("media_type"),
    title: text("title"),
    byline: text("byline"),
    submitter: text("submitter"),
    createdAt: integer("created_at").notNull(),
  },
  (t) => [
    uniqueIndex("submissions_text_sha256_key").on(t.textSha256),
    // FlattenedDoc.pages: int | None = Field(ge=0)
    check("submissions_pages_ge0", sql`${t.pages} IS NULL OR ${t.pages} >= 0`),
    check("submissions_text_length_ge0", sql`${t.textLength} >= 0`),
  ],
);

/**
 * One pipeline execution over a submission — everything in the report that
 * isn't the document.
 *
 * The contract has no run identifier at all (`RunInfo` is date/seconds/version/
 * cost_usd), so we mint one: `crypto.randomUUID()`, opaque and URL-safe.
 * Ordering comes from the indexed `created_at` rather than a sortable id — the
 * only thing a ULID would buy here is ordering, and an integer index buys it
 * without the base32.
 *
 * `run_date` holds `RunInfo.date` verbatim. It is a *string* in the contract
 * ("2026-07-31"), not a date; parsing it to a timestamp would be a lossy
 * round-trip. `created_at` (ours, machine time) and `run_date` (theirs,
 * verbatim) are different columns on purpose.
 *
 * `report_sha256` UNIQUE gives idempotent ingest: a retried POST returns the
 * existing run_id instead of duplicating a run. A pipeline that POSTs on
 * completion *will* retry.
 */
export const runs = sqliteTable(
  "runs",
  {
    id: text("id").primaryKey(),
    submissionId: text("submission_id")
      .notNull()
      .references(() => submissions.id, { onDelete: "cascade", onUpdate: "cascade" }),
    reportSha256: text("report_sha256").notNull(),
    schemaVersion: text("schema_version").notNull(),
    solicitation: text("solicitation"),
    runDate: text("run_date"),
    runSeconds: real("run_seconds"),
    runVersion: text("run_version"),
    costUsd: real("cost_usd"),
    recommendation: text("recommendation").notNull(),
    createdAt: integer("created_at").notNull(),
  },
  (t) => [
    uniqueIndex("runs_report_sha256_key").on(t.reportSha256),
    index("runs_submission_created_idx").on(t.submissionId, t.createdAt),
    // RunInfo.cost_usd: float | None = Field(ge=0.0). `seconds` carries no
    // such bound in models.py, so we don't invent one.
    check("runs_cost_ge0", sql`${t.costUsd} IS NULL OR ${t.costUsd} >= 0`),
  ],
);

/**
 * A quote-anchored piece of evidence.
 *
 * `finding_key` holds `Finding.id` ("C1", "Q1", "D1") — unique only *within* a
 * report, and models.py doesn't even enforce that. So it's indexed, not
 * unique: a report pydantic accepts must be storable. The surrogate `id` is
 * the real key.
 *
 * `Anchor` is flattened. `anchor_quote IS NULL` means "no anchor at all",
 * distinguishable from an empty-string quote, which models.py permits.
 */
export const findings = sqliteTable(
  "findings",
  {
    id: text("id").primaryKey(),
    runId: text("run_id")
      .notNull()
      .references(() => runs.id, { onDelete: "cascade", onUpdate: "cascade" }),
    ordinal: integer("ordinal").notNull(),
    findingKey: text("finding_key").notNull(),
    target: text("target"),
    label: text("label"),
    anchorQuote: text("anchor_quote"),
    anchorPage: integer("anchor_page"),
    spanStart: integer("span_start"),
    spanEnd: integer("span_end"),
    verdict: text("verdict").$type<VerdictName>(),
    // Finding.evidence: dict[str, Any] — opaque to us, stored as JSON text.
    evidence: text("evidence", { mode: "json" }).$type<Record<string, unknown>>().notNull(),
    note: text("note"),
  },
  (t) => [
    uniqueIndex("findings_run_ordinal_key").on(t.runId, t.ordinal),
    // Deliberately NOT unique — see the finding_key note above.
    index("findings_run_key_idx").on(t.runId, t.findingKey),
    // Anchor.page: int | None = Field(ge=1)
    check("findings_page_ge1", sql`${t.anchorPage} IS NULL OR ${t.anchorPage} >= 1`),
    // Span: start >= 0, end >= start, and both-or-neither.
    check(
      "findings_span_valid",
      sql`(${t.spanStart} IS NULL AND ${t.spanEnd} IS NULL) OR (${t.spanStart} >= 0 AND ${t.spanEnd} >= ${t.spanStart})`,
    ),
    // No orphan page/span without an anchor to hang them on.
    check(
      "findings_anchor_shape",
      sql`${t.anchorQuote} IS NOT NULL OR (${t.anchorPage} IS NULL AND ${t.spanStart} IS NULL AND ${t.spanEnd} IS NULL)`,
    ),
    check(
      "findings_verdict_enum",
      sql`${t.verdict} IS NULL OR ${t.verdict} IN ('supported','overstated','unsupported','contradicted','unverifiable')`,
    ),
  ],
);

/** `CheckResult` rows inside a Finding. Column is `check_name` — `check` is reserved. */
export const findingChecks = sqliteTable(
  "finding_checks",
  {
    id: text("id").primaryKey(),
    findingId: text("finding_id")
      .notNull()
      .references(() => findings.id, { onDelete: "cascade", onUpdate: "cascade" }),
    ordinal: integer("ordinal").notNull(),
    checkName: text("check_name").notNull(),
    ...resultColumns,
  },
  (t) => [
    uniqueIndex("finding_checks_finding_ordinal_key").on(t.findingId, t.ordinal),
    index("finding_checks_name_idx").on(t.checkName),
    ...resultChecks("finding_checks", t),
  ],
);

/** `LedgerRow` — the document-level all-checks table. `LedgerRow.check` -> check_name. */
export const ledgerRows = sqliteTable(
  "ledger_rows",
  {
    id: text("id").primaryKey(),
    runId: text("run_id")
      .notNull()
      .references(() => runs.id, { onDelete: "cascade", onUpdate: "cascade" }),
    ordinal: integer("ordinal").notNull(),
    checkName: text("check_name").notNull(),
    label: text("label"),
    detail: text("detail"),
    ...resultColumns,
  },
  (t) => [
    uniqueIndex("ledger_rows_run_ordinal_key").on(t.runId, t.ordinal),
    // Powers "how has all_dois_resolve trended across submissions?" without a
    // full scan — the query #20 (batch view) and #14 (similarity) both want.
    index("ledger_rows_check_kind_idx").on(t.checkName, t.resultKind, t.resultNum),
    ...resultChecks("ledger_rows", t),
  ],
);
