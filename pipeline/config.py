"""Paths, endpoints and defaults for the Scorecard ingestion pipeline.

Every setting can be overridden with an environment variable so the same
code runs locally, in Docker and in CI.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("SCORECARD_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
CLEAN_DIR = DATA_DIR / "clean"
DB_PATH = Path(os.getenv("SCORECARD_DB_PATH", DATA_DIR / "scorecard.duckdb"))

# Endpoints and keys used by scorecard.worldbank.org itself. The keys are the
# public, browser-side keys shipped in the site's Angular bundle
# (main.*.js -> environment.apiKey); they are sent as an `apikey` header.
DATA_API = os.getenv("SCORECARD_DATA_API", "https://ext.api.worldbank.org/api/Scorecard/")
DATA_API_KEY = os.getenv("SCORECARD_API_KEY", "251d66a4a60a4f81adcbe6029adb0226")
CMS_API = os.getenv("SCORECARD_CMS_API", "https://scorecardcmsapi.worldbank.org/scorecard/cache/")
CMS_API_KEY = os.getenv("SCORECARD_CMS_KEY", "3e84b52cbc604d20951e4c381c1ccd38")

# Snapshot fiscal years with data (FY2023 and earlier return empty results).
SNAPSHOTS = tuple(int(x) for x in os.getenv("SCORECARD_SNAPSHOTS", "2024,2025,2026").split(","))

HTTP_TIMEOUT = float(os.getenv("SCORECARD_HTTP_TIMEOUT", "120"))
MAX_WORKERS = int(os.getenv("SCORECARD_MAX_WORKERS", "6"))
