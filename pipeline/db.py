"""Stage 3: load the cleaned Parquet tables into DuckDB and define analysis views.

The views encode the aggregation rules that are easy to get wrong when
querying the raw grain directly (see transform.py), so downstream consumers
(the MCP tools, the dashboard, the LLM's SQL) can start from them.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from . import config

log = logging.getLogger(__name__)

VIEWS = {
    # Latest metadata row per indicator (names/units/outcome area as of the newest snapshot).
    "indicator_catalog": """
        SELECT * EXCLUDE (rn) FROM (
            SELECT i.*, row_number() OVER (PARTITION BY ind_code ORDER BY snapshot_fy DESC) AS rn
            FROM indicators i)
        WHERE rn = 1
    """,
    # WBG Results headline series, all disaggregations at their total. One row per
    # snapshot x institution x area. Never sum across org_code: WBG = WB + IFC + MIGA,
    # WB <= IBRD + IDA (co-financed projects are de-duplicated), IDA-21 is a subset of IDA.
    "results": """
        SELECT v.snapshot_fy, v.as_of_date, v.ind_code, c.ind_name, c.outcome_area, v.unit,
               v.org_code, v.area_type, v.area_code, v.area_name, v.country_eligibility,
               v.achieved, v.expected, v.cumulative_achieved,
               CASE WHEN v.expected > 0 THEN v.achieved / v.expected END AS achieved_to_expected,
               v.footnote
        FROM indicator_values v
        JOIN indicator_catalog c USING (ind_code)
        WHERE v.ind_type = 'WBG Results' AND v.is_headline AND v.is_total_disaggregation
    """,
    # Same, but every series (headline + sub-indicators) and the sex split.
    "results_detail": """
        SELECT v.snapshot_fy, v.ind_code, c.ind_name, v.series_code, s.sub_ind_name, v.is_headline,
               v.org_code, v.area_type, v.area_code, v.area_name, v.sex, v.age, v.disability,
               v.unit, v.achieved, v.expected
        FROM indicator_values v
        JOIN indicator_catalog c USING (ind_code)
        LEFT JOIN sub_indicators s ON s.snapshot_fy = v.snapshot_fy AND s.sub_ind_code = v.sub_ind_code
        WHERE v.ind_type = 'WBG Results' AND v.joint_programming = '_T'
    """,
    # Country-level results with country attributes from the same snapshot. Rows with
    # is_economy = false are multi-country groupings (e.g. 1W "World", 3A "Africa")
    # that the feed files under COUNTRY; exclude them from country rankings.
    "country_results": """
        SELECT r.*, k.country_code IS NOT NULL AS is_economy, k.iso3, k.region_code, k.region_name,
               k.income_name, k.lending_eligibility, k.is_fcs, k.is_ldc, k.is_sids, k.is_small_state
        FROM results r
        LEFT JOIN countries k ON k.snapshot_fy = r.snapshot_fy AND k.country_code = r.area_code
        WHERE r.area_type = 'COUNTRY'
    """,
    # Client Context and Vision indicators: observed values by calendar year.
    "context": """
        SELECT v.snapshot_fy, v.ind_type, v.ind_code, c.ind_name, c.outcome_area, v.series_code,
               s.sub_ind_name, v.is_headline, v.org_code AS country_group, v.area_type, v.area_code,
               v.area_name, v.obs_year, v.unit, v.achieved AS value, c.scale_type
        FROM indicator_values v
        JOIN indicator_catalog c USING (ind_code)
        LEFT JOIN sub_indicators s ON s.snapshot_fy = v.snapshot_fy AND s.sub_ind_code = v.sub_ind_code
        WHERE v.ind_type IN ('Client Context', 'Vision') AND v.is_total_disaggregation
    """,
    # Project-level contributions (World Bank IBRD/IDA operations only; IFC and
    # MIGA investments are reported only in the aggregate results).
    "project_results": """
        SELECT p.*, c.ind_name, c.unit, k.country_name, k.iso3
        FROM projects p
        JOIN indicator_catalog c USING (ind_code)
        LEFT JOIN countries k ON k.snapshot_fy = p.snapshot_fy AND k.country_code = p.country_code
        WHERE p.sex = '_T' AND p.age = '_T'
    """,
}


def build_database(clean_dir: Path = config.CLEAN_DIR, db_path: Path = config.DB_PATH) -> Path:
    tmp = db_path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    for f in sorted(clean_dir.glob("*.parquet")):
        con.execute(f"CREATE TABLE {f.stem} AS SELECT * FROM read_parquet(?)", [str(f)])
    for name, sql in VIEWS.items():
        con.execute(f"CREATE VIEW {name} AS {sql}")
    latest = con.execute("SELECT max(snapshot_fy) FROM indicator_values").fetchone()[0]
    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latest_snapshot_fy": latest,
        "snapshots": [r[0] for r in con.execute("SELECT DISTINCT snapshot_fy FROM indicator_values ORDER BY 1").fetchall()],
        "source": config.DATA_API,
    }
    con.execute("CREATE TABLE build_info AS SELECT * FROM (VALUES (?)) t(info)", [json.dumps(meta)])
    con.close()
    tmp.replace(db_path)
    log.info("built %s (latest snapshot FY%s)", db_path, latest)
    return db_path


def connect(db_path: Path = config.DB_PATH, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    # Read-only connections also disable external access (no file reads, URLs or extensions). This
    # matches the app's connection; DuckDB rejects mixed configurations for one file in one process.
    cfg = {"enable_external_access": False} if read_only else {}
    return duckdb.connect(str(db_path), read_only=read_only, config=cfg)
