"""HTTP client for the WBG Scorecard data and CMS APIs.

The data API returns Databricks SQL-statement payloads:

    {"status": {"state": "SUCCEEDED"},
     "manifest": {"schema": {"columns": [{"name": ...}, ...]}, "total_chunk_count": 1, ...},
     "result": {"data_array": [["2025", "CSC_RES_ELC_ACCS", ...], ...]}}

with every value serialised as a string. Some endpoints return a plain JSON
array instead, and failures come back as {"statusCode": 500, "message": ...}
with an HTTP 200 or 500. `records()` normalises all three shapes.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

log = logging.getLogger(__name__)


class ScorecardAPIError(RuntimeError):
    pass


def _session() -> requests.Session:
    retry = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=config.MAX_WORKERS * 2))
    s.headers["User-Agent"] = "wbg-scorecard-explorer/0.1 (assessment prototype)"
    return s


class ScorecardClient:
    def __init__(self) -> None:
        self.session = _session()
        self.bases = {
            "data": (config.DATA_API, config.DATA_API_KEY),
            "cms": (config.CMS_API, config.CMS_API_KEY),
        }

    def get(self, api: str, path: str, params: dict[str, Any] | None = None) -> Any:
        base, key = self.bases[api]
        url = base + path.lstrip("/")
        r = self.session.get(url, params=params, headers={"apikey": key}, timeout=config.HTTP_TIMEOUT)
        if r.status_code != 200:
            raise ScorecardAPIError(f"{r.status_code} for {r.url}: {r.text[:200]}")
        payload = r.json()
        if isinstance(payload, dict) and "statusCode" in payload and "manifest" not in payload:
            raise ScorecardAPIError(f"{payload.get('statusCode')} for {r.url}: {payload.get('message')}")
        return payload


def records(payload: Any) -> list[dict[str, Any]]:
    """Convert any Scorecard payload shape into a list of row dicts."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and "manifest" in payload:
        state = (payload.get("status") or {}).get("state")
        if state != "SUCCEEDED":
            raise ScorecardAPIError(f"statement state {state!r}")
        manifest = payload["manifest"]
        result = payload.get("result") or {}
        data = result.get("data_array") or []
        # Large results are split into Databricks chunks. The API gateway
        # already concatenates them into data_array (len == total_row_count),
        # but the chunk links can't be followed without Databricks credentials,
        # so fail loudly if a payload ever arrives incomplete.
        expected = manifest.get("total_row_count")
        if manifest.get("truncated") or (expected is not None and len(data) != expected):
            raise ScorecardAPIError(
                f"incomplete result: {len(data)} rows of {expected} "
                f"(chunks={manifest.get('total_chunk_count')}, truncated={manifest.get('truncated')})"
            )
        cols = [c["name"] for c in manifest["schema"]["columns"]]
        return [dict(zip(cols, row)) for row in data]
    if isinstance(payload, dict):
        return [payload]
    raise ScorecardAPIError(f"unrecognised payload type {type(payload).__name__}")
