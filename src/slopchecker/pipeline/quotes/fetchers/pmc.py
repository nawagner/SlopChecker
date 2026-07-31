"""PubMed Central OA fetcher: DOI -> PMCID -> full-text JATS XML.

PMC hosts full-text JATS XML only for its Open Access subset. Flow:
1. NCBI's ID Converter maps DOI -> PMCID.
2. NCBI's EFetch retrieves the JATS XML by PMCID.
3. We pull the ``<body>`` text out and return it.

Closed-access PMC articles either lack a PMCID in the converter response or
return an error at EFetch — both paths return ``None`` so the check layer
records ``source_unavailable`` rather than ``not_found``. No paywall
circumvention: if PMC won't give us OA text, we don't try elsewhere.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

import httpx

from slopchecker.pipeline.citations.models import ReferenceEntry
from slopchecker.pipeline.quotes.fetchers._http import build_client, safe_get

_ID_CONVERT_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_TOOL_NAME = "slopchecker"


class PmcOAFetcher:
    """Fetch OA full text from PubMed Central for a DOI-bearing reference."""

    def __init__(self, client: httpx.Client | None = None, email: str | None = None):
        self._client = build_client(client)
        self._email = email  # NCBI asks for a contact; opt-in, no default.

    @staticmethod
    def applies_to(ref: ReferenceEntry) -> bool:
        return bool(ref.doi)

    def fetch(self, ref: ReferenceEntry) -> str | None:
        if not ref.doi:
            return None
        pmcid = self._doi_to_pmcid(ref.doi)
        if pmcid is None:
            return None
        return self._fetch_pmc_body(pmcid)

    def _doi_to_pmcid(self, doi: str) -> str | None:
        params = {"ids": doi, "format": "json", "tool": _TOOL_NAME}
        if self._email:
            params["email"] = self._email
        response = safe_get(self._client, _ID_CONVERT_URL, params=params)
        if response is None:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        records = payload.get("records") or []
        if not records:
            return None
        record = records[0]
        pmcid = record.get("pmcid")
        if not pmcid or record.get("errmsg"):
            return None
        return pmcid  # e.g. "PMC1234567"

    def _fetch_pmc_body(self, pmcid: str) -> str | None:
        numeric = re.sub(r"^PMC", "", pmcid, flags=re.IGNORECASE)
        params = {"db": "pmc", "id": numeric, "rettype": "xml", "tool": _TOOL_NAME}
        if self._email:
            params["email"] = self._email
        response = safe_get(self._client, _EFETCH_URL, params=params)
        if response is None:
            return None
        return _jats_body_text(response.text)


def _jats_body_text(xml_text: str) -> str | None:
    """Pull the JATS ``<body>`` text out; return ``None`` on parse failure or
    if the response has no body (closed-access articles produce this)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    body = root.find(".//body")
    if body is None:
        return None
    parts = [text for text in body.itertext() if text]
    joined = " ".join("".join(parts).split())
    return joined or None
