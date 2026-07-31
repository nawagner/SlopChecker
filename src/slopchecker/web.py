"""Deploy-target stub for #27 — not the real API.

Exists so Railway has something to run, and so you can confirm a secret set
on the host is actually visible to the deployed process, the same way
`slopcheck config` confirms it locally. Delete or replace once the real
"thin web layer over the pipeline" (#27) lands.

`/config` reports booleans only, never `config.status()`'s masked values —
this endpoint is unauthenticated by design (it's a health check), so nothing
here should let a caller infer even a fragment of a real key.
"""

from __future__ import annotations

from fastapi import FastAPI

from slopchecker import __version__, config

# Loaded once at import time, like any other server startup config — not on
# every request. On Railway there's no .env file so this is a no-op there;
# locally it means a real .env can shadow a test's monkeypatched env vars,
# but only for the process's lifetime, same as any other Python config load.
config.load()

app = FastAPI(title="SlopChecker (deploy-target stub)")


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
