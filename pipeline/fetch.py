"""Stage 1: download raw Scorecard payloads to data/raw/ (gzipped JSON, unmodified).

Raw files are cached: re-running skips anything already on disk unless
`refresh=True`, so a partial run can be resumed and the cleaned layer can be
rebuilt offline from the committed raw extracts.
"""

from __future__ import annotations

import gzip
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .client import ScorecardAPIError, ScorecardClient, records

log = logging.getLogger(__name__)


@dataclass
class Job:
    name: str
    api: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def file(self) -> Path:
        return config.RAW_DIR / f"{self.name}.json.gz"


def write_raw(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    tmp.replace(path)


def read_raw(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _run(client: ScorecardClient, job: Job, refresh: bool) -> dict[str, Any]:
    entry = {"name": job.name, "url": f"{client.bases[job.api][0]}{job.path}", "params": job.params}
    if job.file.exists() and not refresh:
        return {**entry, "status": "cached", "rows": len(records(read_raw(job.file)))}
    t0 = time.monotonic()
    try:
        payload = client.get(job.api, job.path, job.params)
        rows = len(records(payload))
    except (ScorecardAPIError, ValueError) as e:
        log.warning("FAILED %s: %s", job.name, e)
        return {**entry, "status": "error", "error": str(e)}
    write_raw(job.file, payload)
    return {
        **entry,
        "status": "fetched",
        "rows": rows,
        "seconds": round(time.monotonic() - t0, 2),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _run_all(client: ScorecardClient, jobs: list[Job], refresh: bool) -> list[dict[str, Any]]:
    out = []
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        futures = {pool.submit(_run, client, j, refresh): j for j in jobs}
        for fut in as_completed(futures):
            res = fut.result()
            log.info("%-8s %-55s rows=%s", res["status"], res["name"], res.get("rows", "-"))
            out.append(res)
    return out


def fetch_all(snapshots: tuple[int, ...] = config.SNAPSHOTS, refresh: bool = False, geo: bool = True) -> list[dict[str, Any]]:
    client = ScorecardClient()

    # Pass 1: dimension and catalogue endpoints (one call per snapshot).
    jobs: list[Job] = []
    for fy in snapshots:
        p = {"snapshotfy": str(fy)}
        jobs += [
            Job(f"metadata/{fy}", "data", "v1/metadata", p),
            Job(f"sub_metadata/{fy}", "data", "getSCSubIndicatorMetaData", p),
            Job(f"countries/{fy}", "data", "getSCCountryDATA", p),
            Job(f"cms/outcomes/{fy}", "cms", "get_outcomes_indicators", {"fy": str(fy)}),
            Job(f"cms/narratives/{fy}", "cms", "get_home_narratives", {"fy": str(fy)}),
        ]
    if geo:
        jobs.append(Job("geo/project_locations", "data", "getSCGEOLOC"))
    manifest = _run_all(client, jobs, refresh)

    # Pass 2: one data call per indicator listed in that snapshot's metadata,
    # plus project-level results for every WBG Results indicator.
    jobs = []
    for fy in snapshots:
        meta_file = Job(f"metadata/{fy}", "data", "").file
        if not meta_file.exists():
            log.error("no metadata for FY%s; skipping its indicators", fy)
            continue
        for ind in records(read_raw(meta_file)):
            code = ind["ind_code"]
            p = {"snapshotfy": str(fy)}
            jobs.append(Job(f"indicator_data/{fy}/{code}", "data", f"v1/data/{code}", p))
            if ind.get("ind_type_name") == "WBG Results":
                jobs.append(Job(f"projects/{fy}/{code}", "data", f"v1/resultsdata/{code}", p))
    manifest += _run_all(client, jobs, refresh)

    manifest.sort(key=lambda r: r["name"])
    (config.RAW_DIR / "fetch_manifest.json").write_text(json.dumps(manifest, indent=1))
    errors = [m for m in manifest if m["status"] == "error"]
    log.info("fetch complete: %d jobs, %d errors", len(manifest), len(errors))
    return manifest


def manifest_summary(manifest: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in manifest:
        out[m["status"]] = out.get(m["status"], 0) + 1
    return out


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(manifest_summary(fetch_all()))
