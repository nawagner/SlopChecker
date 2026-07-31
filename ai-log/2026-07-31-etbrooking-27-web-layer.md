# 2026-07-31 — etbrooking — #27 web layer: POST /check

Session: Fable via Claude Code (same session as the landing-page and
skipped-chip logs).

- **Landed:** real `web.py` replacing the deploy stub — `POST /check`
  (multipart upload → `ingest()` → `run_checks()` over every registered
  check → rendered HTML evidence report; `?format=json` returns raw
  report.json). `/health` and `/config` unchanged. Frontend upload flow on
  slop-checker.com now completes for real.
- **Audit findings that shaped it:** the frontend contract already existed
  (posts `file` to `/api/check`, renders an HTML response via
  document.write); the Worker proxy strips `/api`, so the route is `/check`;
  Railway only installed `.[web]`, so PDF/DOCX ingestion would have errored
  in production — `railway.toml` buildCommand now installs
  `.[web,pdf,docx]`, and `python-multipart` joined the `web` extra (FastAPI
  needs it for uploads).
- **Failure split, deliberately:** an unreadable *upload* (unsupported
  format, scanned PDF) is a 422 whose detail is the ingest reason verbatim;
  the frontend shows it and stays put. A check that can't run inside a good
  document is not an HTTP error at all — it's a coverage-gap row in the
  report. Frontend redirects to the sample report only when the endpoint is
  actually unreachable.
- **Hygiene:** filename flattened to a safe basename (suffix routes the
  loader, stem labels the report, rest untrusted); 25 MB upload cap; checks
  discovered once at startup, not per request.
- **Verified:** 7 web tests incl. hostile-filename and unsupported-format
  paths; local end-to-end smoke with a generated PDF (200, rendered report,
  both built-in checks ran).
- **Known-thin:** only `has_text` + `word_count` are registered today; live
  reports fatten automatically as engines get registered (`discover()` scans
  `slopchecker.checks` too, which doesn't exist yet).
- **Dead end / note for others:** `tests/test_cli_run.py::
  test_dry_run_lists_checks_and_calls_nothing` fails on Windows terminals
  (Rich table truncates the check id column at narrow widths) on clean main
  too — pre-existing, passes in CI, not touched here.
