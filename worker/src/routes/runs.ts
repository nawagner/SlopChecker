/**
 * `/api/runs` — store an evidence report, read it back.
 *
 * This is the one endpoint that makes the D1 setup provably real rather than
 * inert config: it exercises every table, both `result_kind` values, list
 * ordering, and the R2 seam. A read-only endpoint would need seeded data; a
 * write-only one would prove nothing round-trips.
 *
 *   POST /api/runs        body: report.json  -> 201 {run_id, counts, ...}
 *   GET  /api/runs/:id                       -> 200 {run_id, report, counts, ...}
 *   GET  /api/runs?text_sha256=&limit=       -> 200 {runs: [...]}
 *
 * These paths are served by the Worker and never reach FastAPI — see the
 * WORKER_OWNED note in index.ts.
 */

import { desc, eq, sql } from "drizzle-orm";
import { drizzle, type DrizzleD1Database } from "drizzle-orm/d1";

import {
  BadReport,
  canonicalJson,
  compact,
  decodeResult,
  encodeResult,
  sha256Hex,
  validateReport,
  type DocumentInput,
  type ReportInput,
} from "../db/codec";
import { findingChecks, findings, ledgerRows, runs, submissions } from "../db/schema";

type DB = DrizzleD1Database<Record<string, never>>;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });

/**
 * `EvidenceReport.counts()` as SQL.
 *
 * Computed on read, never stored — #3 decided derived tallies are not columns
 * (docs/DATA_MODEL.md; `models.py` says "derived from the ledger (never
 * stored)"). A query can't drift from the ledger; a column can.
 *
 * No CASE expressions: SQLite comparisons already yield 0/1, so SUM(predicate)
 * counts directly. That also sidesteps wrangler's migration SQL splitter,
 * which mis-parses `SUM(CASE ... END)` — worth keeping as a house habit even
 * though this particular query never goes through a migration file.
 */
async function countsFor(db: DB, runId: string) {
  const [row] = await db
    .select({
      passed: sql<number>`COALESCE(SUM(${ledgerRows.status} = 'ok' AND ${ledgerRows.resultKind} = 'bool' AND ${ledgerRows.resultNum} = 1), 0)`,
      failed: sql<number>`COALESCE(SUM(${ledgerRows.status} = 'ok' AND ${ledgerRows.resultKind} = 'bool' AND ${ledgerRows.resultNum} = 0), 0)`,
      scores: sql<number>`COALESCE(SUM(${ledgerRows.status} = 'ok' AND ${ledgerRows.resultKind} = 'number'), 0)`,
      skipped: sql<number>`COALESCE(SUM(${ledgerRows.status} = 'skipped'), 0)`,
      errored: sql<number>`COALESCE(SUM(${ledgerRows.status} = 'errored'), 0)`,
    })
    .from(ledgerRows)
    .where(eq(ledgerRows.runId, runId));
  return row ?? { passed: 0, failed: 0, scores: 0, skipped: 0, errored: 0 };
}

/**
 * The `FlattenedDoc` fields we mirror, paired incoming-vs-stored for the 409
 * divergence check. Listed explicitly rather than looped over a key list so
 * the column mapping is checked by the compiler.
 */
function docFieldPairs(doc: DocumentInput, stored: typeof submissions.$inferSelect) {
  return [
    { name: "file", incoming: doc.file ?? null, stored: stored.file },
    { name: "sha256", incoming: doc.sha256 ?? null, stored: stored.fileSha256 },
    { name: "pages", incoming: doc.pages ?? null, stored: stored.pages },
    { name: "media_type", incoming: doc.media_type ?? null, stored: stored.mediaType },
    { name: "title", incoming: doc.title ?? null, stored: stored.title },
    { name: "byline", incoming: doc.byline ?? null, stored: stored.byline },
    { name: "submitter", incoming: doc.submitter ?? null, stored: stored.submitter },
  ];
}

async function postRun(request: Request, db: DB): Promise<Response> {
  let report: ReportInput;
  try {
    report = validateReport(JSON.parse(await request.text()));
  } catch (err) {
    if (err instanceof BadReport) return json({ error: err.message, path: err.path }, 400);
    return json({ error: "body must be valid JSON" }, 400);
  }

  const doc = report.document;
  // Computed here, never trusted from the payload.
  const textSha256 = await sha256Hex(doc.text);
  const textLength = doc.text.length;
  // Canonical form rather than the raw body, so a retry that differs only in
  // formatting — whitespace OR key order — is recognised as the same report.
  // Plain JSON.stringify would handle whitespace but not key order.
  const reportSha256 = await sha256Hex(canonicalJson(report));

  // Idempotent ingest: a pipeline that POSTs on completion will retry.
  const [existing] = await db.select({ id: runs.id, submissionId: runs.submissionId })
    .from(runs)
    .where(eq(runs.reportSha256, reportSha256))
    .limit(1);
  if (existing) {
    return json(
      {
        run_id: existing.id,
        submission_id: existing.submissionId,
        created: false,
        text_sha256: textSha256,
        text_length: textLength,
        counts: await countsFor(db, existing.id),
      },
      200,
    );
  }

  const now = Date.now();
  const [priorSubmission] = await db.select().from(submissions)
    .where(eq(submissions.textSha256, textSha256))
    .limit(1);

  let submissionId: string;
  const statements: unknown[] = [];

  if (priorSubmission) {
    // Same text, different metadata means a stored row would contradict the
    // report you read back. Fail loudly rather than silently reuse — same
    // instinct as pydantic's extra="forbid". If this ever becomes annoying,
    // key submissions on (text_sha256, meta_sha256) so divergence forks a row.
    const divergent = docFieldPairs(doc, priorSubmission)
      .filter(({ incoming, stored }) => incoming !== stored)
      .map(({ name }) => name);
    if (divergent.length > 0) {
      return json(
        {
          error: "document metadata diverges from the stored submission with this text",
          text_sha256: textSha256,
          submission_id: priorSubmission.id,
          fields: divergent,
        },
        409,
      );
    }
    submissionId = priorSubmission.id;
  } else {
    submissionId = crypto.randomUUID();
    statements.push(
      db.insert(submissions).values({
        id: submissionId,
        textSha256,
        textLength,
        file: doc.file,
        fileSha256: doc.sha256 ?? null,
        pages: doc.pages ?? null,
        pageOffsets: doc.page_offsets ?? null,
        mediaType: doc.media_type ?? null,
        title: doc.title ?? null,
        byline: doc.byline ?? null,
        submitter: doc.submitter ?? null,
        createdAt: now,
      }),
    );
  }

  const runId = crypto.randomUUID();
  statements.push(
    db.insert(runs).values({
      id: runId,
      submissionId,
      reportSha256,
      schemaVersion: report.schema_version ?? "0.1",
      solicitation: report.solicitation ?? null,
      runDate: report.run?.date ?? null,
      runSeconds: report.run?.seconds ?? null,
      runVersion: report.run?.version ?? null,
      costUsd: report.run?.cost_usd ?? null,
      recommendation: report.summary?.recommendation ?? "human_review",
      createdAt: now,
    }),
  );

  // UUIDs are minted up front so finding_checks.finding_id is known without a
  // round trip — the whole write is one batch.
  (report.findings ?? []).forEach((f, i) => {
    const findingId = crypto.randomUUID();
    statements.push(
      db.insert(findings).values({
        id: findingId,
        runId,
        ordinal: i,
        findingKey: f.id,
        target: f.target ?? null,
        label: f.label ?? null,
        anchorQuote: f.anchor?.quote ?? null,
        anchorPage: f.anchor?.page ?? null,
        spanStart: f.anchor?.span?.start ?? null,
        spanEnd: f.anchor?.span?.end ?? null,
        verdict: f.verdict ?? null,
        evidence: f.evidence ?? {},
        note: f.note ?? null,
      }),
    );
    (f.checks ?? []).forEach((c, j) => {
      const { kind, num } = encodeResult(c.result, `findings[${i}].checks[${j}].result`);
      statements.push(
        db.insert(findingChecks).values({
          id: crypto.randomUUID(),
          findingId,
          ordinal: j,
          checkName: c.name,
          resultKind: kind,
          resultNum: num,
          status: c.status ?? "ok",
          reason: c.reason ?? null,
        }),
      );
    });
  });

  (report.ledger ?? []).forEach((row, i) => {
    const { kind, num } = encodeResult(row.result, `ledger[${i}].result`);
    statements.push(
      db.insert(ledgerRows).values({
        id: crypto.randomUUID(),
        runId,
        ordinal: i,
        checkName: row.check,
        label: row.label ?? null,
        detail: row.detail ?? null,
        resultKind: kind,
        resultNum: num,
        status: row.status ?? "ok",
        reason: row.reason ?? null,
      }),
    );
  });

  // Single-row inserts in one batch, deliberately: D1 caps bound parameters at
  // 100 per query, so a multi-row INSERT would blow up at ~8 findings. batch()
  // is also atomic — a half-written report would still satisfy extra="forbid"
  // on read and be silently wrong.
  try {
    await db.batch(statements as unknown as [never, ...never[]]);
  } catch (err) {
    // The idempotency SELECT and this INSERT aren't one transaction, so a
    // concurrent duplicate POST lands here. UNIQUE(report_sha256) caught it;
    // re-read rather than 500.
    const message = err instanceof Error ? err.message : String(err);
    if (/UNIQUE/i.test(message)) {
      const [raced] = await db.select({ id: runs.id, submissionId: runs.submissionId })
        .from(runs)
        .where(eq(runs.reportSha256, reportSha256))
        .limit(1);
      if (raced) {
        return json(
          {
            run_id: raced.id,
            submission_id: raced.submissionId,
            created: false,
            text_sha256: textSha256,
            text_length: textLength,
            counts: await countsFor(db, raced.id),
          },
          200,
        );
      }
    }
    throw err;
  }

  return json(
    {
      run_id: runId,
      submission_id: submissionId,
      created: true,
      text_sha256: textSha256,
      text_length: textLength,
      counts: await countsFor(db, runId),
    },
    201,
  );
}

async function getRun(runId: string, db: DB): Promise<Response> {
  const [run] = await db
    .select()
    .from(runs)
    .innerJoin(submissions, eq(runs.submissionId, submissions.id))
    .where(eq(runs.id, runId))
    .limit(1);
  if (!run) return json({ error: "run not found", run_id: runId }, 404);

  // ORDER BY ordinal everywhere: list order is contract data, and getting it
  // wrong fails silently on small fixtures.
  const findingRows = await db.select().from(findings)
    .where(eq(findings.runId, runId))
    .orderBy(findings.ordinal);
  const ledger = await db.select().from(ledgerRows)
    .where(eq(ledgerRows.runId, runId))
    .orderBy(ledgerRows.ordinal);

  const checksByFinding = new Map<string, typeof findingChecks.$inferSelect[]>();
  if (findingRows.length > 0) {
    const allChecks = await db
      .select()
      .from(findingChecks)
      .innerJoin(findings, eq(findingChecks.findingId, findings.id))
      .where(eq(findings.runId, runId))
      .orderBy(findings.ordinal, findingChecks.ordinal);
    for (const row of allChecks) {
      const list = checksByFinding.get(row.finding_checks.findingId) ?? [];
      list.push(row.finding_checks);
      checksByFinding.set(row.finding_checks.findingId, list);
    }
  }

  const { runs: r, submissions: s } = run;

  // `document.text` is deliberately absent — it never entered D1 (schema.ts
  // rule 3). The envelope carries text_sha256/text_length so a consumer can
  // splice the text back in from wherever it lives.
  const report = compact({
    schema_version: r.schemaVersion,
    document: compact({
      file: s.file,
      sha256: s.fileSha256 ?? undefined,
      pages: s.pages ?? undefined,
      page_offsets: s.pageOffsets ?? undefined,
      media_type: s.mediaType ?? undefined,
      title: s.title ?? undefined,
      byline: s.byline ?? undefined,
      submitter: s.submitter ?? undefined,
    }),
    solicitation: r.solicitation ?? undefined,
    run: compact({
      date: r.runDate ?? undefined,
      seconds: r.runSeconds ?? undefined,
      version: r.runVersion ?? undefined,
      cost_usd: r.costUsd ?? undefined,
    }),
    findings: findingRows.map((f) => {
      const anchor =
        f.anchorQuote === null
          ? undefined
          : compact({
              page: f.anchorPage ?? undefined,
              quote: f.anchorQuote,
              span:
                f.spanStart === null || f.spanEnd === null
                  ? undefined
                  : { start: f.spanStart, end: f.spanEnd },
            });
      return compact({
        id: f.findingKey,
        target: f.target ?? undefined,
        label: f.label ?? undefined,
        anchor,
        checks: (checksByFinding.get(f.id) ?? []).map((c) =>
          compact({
            name: c.checkName,
            result: decodeResult(c.resultKind, c.resultNum),
            // "ok" is the model default; omit it so the payload matches what
            // exclude_none + defaults produce on the Python side.
            status: c.status === "ok" ? undefined : c.status,
            reason: c.reason ?? undefined,
          }),
        ),
        verdict: f.verdict ?? undefined,
        evidence: Object.keys(f.evidence ?? {}).length > 0 ? f.evidence : undefined,
        note: f.note ?? undefined,
      });
    }),
    ledger: ledger.map((row) =>
      compact({
        check: row.checkName,
        label: row.label ?? undefined,
        result: decodeResult(row.resultKind, row.resultNum),
        detail: row.detail ?? undefined,
        status: row.status === "ok" ? undefined : row.status,
        reason: row.reason ?? undefined,
      }),
    ),
    summary: { recommendation: r.recommendation },
  });

  return json({
    run_id: r.id,
    submission_id: s.id,
    created_at: r.createdAt,
    text_sha256: s.textSha256,
    text_length: s.textLength,
    // The R2 seam: null until #65's slopchecker-docs bucket is bound here.
    // `text_sha256` is already the object key, so wiring it is additive — no
    // migration needed.
    text_location: null,
    counts: await countsFor(db, r.id),
    report,
  });
}

/** Run history for one document — the query #20 (batch view) and #14 (similarity) both want. */
async function listRuns(url: URL, db: DB): Promise<Response> {
  const textSha256 = url.searchParams.get("text_sha256");
  const limit = Math.min(Number(url.searchParams.get("limit") ?? 20) || 20, 100);

  const rows = await db
    .select({
      run_id: runs.id,
      submission_id: runs.submissionId,
      file: submissions.file,
      text_sha256: submissions.textSha256,
      run_date: runs.runDate,
      recommendation: runs.recommendation,
      created_at: runs.createdAt,
    })
    .from(runs)
    .innerJoin(submissions, eq(runs.submissionId, submissions.id))
    .where(textSha256 ? eq(submissions.textSha256, textSha256) : undefined)
    .orderBy(desc(runs.createdAt))
    .limit(limit);

  return json({ runs: rows });
}

export async function handleRuns(request: Request, db: D1Database, url: URL): Promise<Response> {
  const orm = drizzle(db);
  const rest = url.pathname.replace(/^\/api\/runs\/?/, "");

  if (request.method === "POST" && rest === "") return postRun(request, orm);
  if (request.method === "GET" && rest === "") return listRuns(url, orm);
  if (request.method === "GET" && rest !== "") return getRun(decodeURIComponent(rest), orm);

  return json({ error: `method ${request.method} not allowed on ${url.pathname}` }, 405);
}
