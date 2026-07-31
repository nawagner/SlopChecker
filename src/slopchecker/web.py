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
from slopchecker.pipeline import all_checks, discover, run_checks
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


@app.post("/check")
def check(file: UploadFile, format: str = "html") -> Response:
    """Run every registered check against one uploaded document."""
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file exceeds the {MAX_UPLOAD_BYTES // 2**20} MB upload limit")
    if not raw:
        raise HTTPException(422, "empty upload")

    # The filename's suffix routes to a loader and its stem labels the report;
    # everything else about it is untrusted. Flatten to a safe basename.
    name = re.sub(r"[^\w.\-]", "_", Path(file.filename or "upload").name) or "upload"
    suffix = Path(name).suffix.lower()
    if suffix not in LOADERS:
        supported = ", ".join(sorted(LOADERS))
        raise HTTPException(
            422, f"unsupported format '{suffix or '(no extension)'}' — supported: {supported}"
        )

    with tempfile.TemporaryDirectory(prefix="slopcheck-") as tmpdir:
        path = Path(tmpdir) / name
        path.write_bytes(raw)
        result = ingest(path)
    if result.status != "ok":
        raise HTTPException(422, result.reason)

    report = run_checks(result.document, all_checks())
    if format == "json":
        return JSONResponse(report.to_report_dict())
    return HTMLResponse(render_report(report.to_report_dict()))
