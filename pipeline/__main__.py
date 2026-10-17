"""Scorecard ingestion pipeline CLI.

    python -m pipeline                 # fetch (cached) -> clean -> DuckDB -> checks
    python -m pipeline --refresh       # re-download everything from the API
    python -m pipeline --offline       # rebuild from committed raw extracts only
    python -m pipeline --geo           # also try the project geo-location endpoint
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import checks, config, db, fetch, transform


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__.splitlines()[0])
    ap.add_argument("--refresh", action="store_true", help="re-download raw payloads even if cached")
    ap.add_argument("--offline", action="store_true", help="skip the API; build from data/raw only")
    ap.add_argument("--geo", action="store_true",
                    help="also fetch project geo-locations (the API currently truncates this endpoint)")
    ap.add_argument("--snapshots", default=",".join(map(str, config.SNAPSHOTS)), help="comma-separated snapshot FYs")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("pipeline")

    if not args.offline:
        snapshots = tuple(int(x) for x in args.snapshots.split(","))
        manifest = fetch.fetch_all(snapshots, refresh=args.refresh, geo=args.geo)
        log.info("fetch: %s", fetch.manifest_summary(manifest))

    tables = transform.build_all()
    transform.write_parquet(tables)
    db.build_database()

    results = checks.run_checks()
    report = checks.write_report(results)
    for c in results:
        log.info("%-5s %s", c.status, c.name)
    log.info("report: %s", report)
    return 1 if any(c.status == "FAIL" for c in results) else 0


if __name__ == "__main__":
    sys.exit(main())
