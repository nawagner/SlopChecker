"""The thin web layer over the pipeline (#27).

``POST /check``: multipart upload → ``ingest()`` → ``run_checks()`` over every
registered check → the rendered HTML evidence report (or ``?format=json`` for
the raw report.json). The Cloudflare Worker proxies slop-checker.com's
``/api/*`` here with the ``/api`` prefix stripped, so the landing page's
upload flow posts to ``/api/check`` and lands on ``/check``.

Failure discipline matches the rest of the tool: an unreadable upload
(unsupported format, scanned PDF with no text layer) is a 422 whose ``detail``
is the ingest reason, verbatim and actionable — the frontend shows it to the
human. Checks that can't run inside an otherwise-good document are not errors
at all; they come back as coverage-gap rows in the report itself.

``/config`` reports booleans only, never ``config.status()``'s masked values —
this endpoint is unauthenticated by design (it's a health check), so nothing
here should let a caller infer even a fragment of a real key.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from slopchecker import __version__, config
from slopchecker.ingest import LOADERS, ingest
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline import all_checks, build_context, discover, run_checks
from slopchecker.report import render_report

# Loaded once at import time, like any other server startup config — not on
# every request. On Railway there's no .env file so this is a no-op there.
config.load()
discover()  # import check modules so their @register decorators run

app = FastAPI(title="SlopChecker")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/config")
def config_status() -> dict:
    return {
        "llm_model": config.llm_model(),
        "credentials": [
            {"env_var": cred.env_var, "purpose": cred.purpose, "set": value is not None}
            for cred, value in config.status()
        ],
    }


def _safe_name(filename: str | None) -> str:
    """A basename safe to write to disk and to print in the report.

    The suffix routes to a loader and the stem labels the report; everything
    else about a client-supplied filename is untrusted.
    """
    return re.sub(r"[^\w.\-]", "_", Path(filename or "upload").name) or "upload"


def _read_upload(upload: UploadFile, label: str) -> tuple[bytes, str]:
    """Bytes and safe basename for one multipart field, or a 4xx saying which.

    Errors on the secondary field name it, because with two file inputs on the
    page "unsupported format" alone doesn't tell the human which of their two
    files to swap. The proposal's messages are left exactly as they were — it
    is the subject of the request, so naming it adds nothing.
    """
    where = "" if label == "file" else f"{label}: "
    raw = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"{where}file exceeds the {MAX_UPLOAD_BYTES // 2**20} MB upload limit"
        )
    if not raw:
        raise HTTPException(422, f"{where}empty upload")

    name = _safe_name(upload.filename)
    suffix = Path(name).suffix.lower()
    if suffix not in LOADERS:
        supported = ", ".join(sorted(LOADERS))
        raise HTTPException(
            422,
            f"{where}unsupported format '{suffix or '(no extension)'}' — supported: {supported}",
        )
    return raw, name


def _ingest_upload(upload: UploadFile, label: str) -> FlattenedDoc:
    """Ingest one upload through the normal loader path, or 422 with the reason.

    Same contract for the proposal and the rubric: an unreadable file is a 422
    whose detail is the pipeline's own reason, never one invented here.
    """
    raw, name = _read_upload(upload, label)
    with tempfile.TemporaryDirectory(prefix="slopcheck-") as tmpdir:
        path = Path(tmpdir) / name
        path.write_bytes(raw)
        result = ingest(path)
    if result.status != "ok" or result.document is None:
        reason = result.reason or "unknown ingestion error"
        raise HTTPException(422, reason if label == "file" else f"{label}: {reason}")
    return result.document


@app.post("/check")
def check(file: UploadFile, rubric: UploadFile | None = None, format: str = "html") -> Response:
    """Run every registered check against one uploaded document.

    ``rubric`` (optional, #90/#148) is the funder's own reference doc — the
    solicitation or scoring criteria the submission is answering. Supplied, it
    is ingested exactly like the submission and rubric-dependent checks run
    against it; omitted, those checks emit their own skipped coverage-gap rows,
    so compliance reads as *unchecked* rather than passed. The CLI's
    ``--rubric`` does the same thing by the same route (see ``cli.py``).
    """
    document = _ingest_upload(file, "file")
    rubric_doc = _ingest_upload(rubric, "rubric") if rubric is not None else None

    ctx = build_context([document])
    ctx.rubric = rubric_doc

    report = run_checks(document, all_checks(), context=ctx)
    # What the submission was measured against. Parity with the CLI: the
    # rubric's filename, and nothing when no rubric came with the upload.
    if rubric is not None:
        report.solicitation = _safe_name(rubric.filename)

    if format == "json":
        return JSONResponse(report.to_report_dict())
    return HTMLResponse(render_report(report.to_report_dict()))
