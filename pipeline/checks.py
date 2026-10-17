"""Stage 4: data-quality checks on the built DuckDB database.

Each check returns PASS / WARN / FAIL plus a small evidence table. The results
are written to data/clean/data_quality_report.md (human-readable) and
data_quality_report.json. Any FAIL makes `python -m pipeline` exit non-zero.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from . import config

# Units for which summing across areas is meaningful.
ADDITIVE_UNITS = ("Beneficiaries", "Hectare(Ha)", "Gigawatt", "USD", "MtCO2eq/year", "Countries/Economies")
HEADLINE = "is_headline AND is_total_disaggregation AND ind_type = 'WBG Results'"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    evidence: pd.DataFrame = field(default_factory=pd.DataFrame)


def _df(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def check_coverage(con) -> Check:
    missing = _df(con, """
        SELECT i.snapshot_fy, i.ind_code, i.ind_type FROM indicators i
        ANTI JOIN (SELECT DISTINCT snapshot_fy, ind_code FROM indicator_values) v USING (snapshot_fy, ind_code)
        ORDER BY 1, 2""")
    n = _df(con, "SELECT count(*) n FROM indicators").n[0]
    status = "PASS" if missing.empty else "WARN"
    return Check("Indicator coverage", status,
                 f"{n - len(missing)} of {n} (snapshot, indicator) pairs in the metadata have data; "
                 f"{len(missing)} are listed in the metadata but return no rows from the API.", missing)


def check_grain(con) -> Check:
    dups = _df(con, """
        SELECT snapshot_fy, ind_code, series_code, org_code, area_type, area_code, sex, age, disability,
               joint_programming, country_eligibility, period, count(*) n
        FROM indicator_values GROUP BY ALL HAVING count(*) > 1 LIMIT 20""")
    return Check("Indicator grain is unique", "PASS" if dups.empty else "FAIL",
                 "indicator_values is unique on snapshot x indicator x series x org x area x disaggregations x period."
                 if dups.empty else f"{len(dups)}+ duplicated keys.", dups)


def check_results_unique(con) -> Check:
    dups = _df(con, """
        SELECT snapshot_fy, ind_code, org_code, area_type, area_code, count(*) n
        FROM results GROUP BY ALL HAVING count(*) > 1 ORDER BY n DESC LIMIT 20""")
    return Check("`results` view has one row per snapshot x indicator x org x area", "PASS" if dups.empty else "FAIL",
                 "Safe to aggregate or join without double counting." if dups.empty
                 else "Duplicated keys in the headline view; queries could double count.", dups)


def check_headline(con) -> Check:
    gaps = _df(con, """
        SELECT i.snapshot_fy, i.ind_code, i.ind_type FROM indicators i
        JOIN (SELECT DISTINCT snapshot_fy, ind_code FROM indicator_values) v USING (snapshot_fy, ind_code)
        ANTI JOIN (SELECT DISTINCT snapshot_fy, ind_code FROM indicator_values WHERE is_headline) h USING (snapshot_fy, ind_code)
        ORDER BY 3, 2, 1""")
    results_gaps = gaps[gaps.ind_type == "WBG Results"]
    status = "PASS" if results_gaps.empty else "FAIL"
    return Check("Every indicator has a headline series", status if gaps.empty else ("WARN" if results_gaps.empty else "FAIL"),
                 "All WBG Results indicators resolve to exactly one headline series per snapshot."
                 + ("" if gaps.empty else f" {len(gaps)} Client Context/Vision indicators publish only component "
                    "series (e.g. water, sanitation and hygiene separately); use their sub-indicators."), gaps)


def check_display_units(con) -> Check:
    bad = _df(con, """
        WITH t AS (
          SELECT ind_code, achieved_display_unit u, achieved_display a, achieved b,
                 CASE achieved_display_unit WHEN 'K' THEN 1e3 WHEN 'M' THEN 1e6 WHEN 'B' THEN 1e9
                      WHEN 'MW' THEN 1e-3 WHEN 'KtCO2eq/year' THEN 1e-3 ELSE 1 END f
          FROM indicator_values WHERE achieved IS NOT NULL AND achieved_display IS NOT NULL)
        SELECT u AS display_unit, count(*) n,
               sum(CASE WHEN abs(a * f - b) <= 0.051 * f + 1 THEN 1 ELSE 0 END) consistent
        FROM t GROUP BY 1 ORDER BY n DESC""")
    share = bad.consistent.sum() / bad.n.sum()
    return Check("Base values agree with display values", "PASS" if share > 0.99 else "WARN",
                 f"{share:.2%} of rows: base value = display value x unit multiplier (K/M/B; MW display of GW base; GHG rescaled from tCO2eq to MtCO2eq), "
                 "within rounding. The pipeline uses base values throughout.", bad)


def check_org_hierarchy(con) -> Check:
    t = _df(con, f"""
        PIVOT (SELECT snapshot_fy, ind_code, org_code, achieved FROM indicator_values
               WHERE {HEADLINE} AND area_code = 'ACW' AND unit IN {ADDITIVE_UNITS}
                     AND unit <> 'Countries/Economies')
        ON org_code IN ('WBG', 'WB', 'IFC', 'MIGA', 'IBRD', 'IDA') USING sum(achieved)
        ORDER BY ind_code, snapshot_fy""")
    t = t.fillna({c: 0 for c in ["WB", "IFC", "MIGA", "IBRD", "IDA"]})
    t = t[t.WBG.notna() & (t.WBG != 0)]
    t["wbg_vs_parts"] = (t.WB + t.IFC + t.MIGA) / t.WBG
    t["wb_vs_ibrd_ida"] = (t.IBRD + t.IDA) / t.WB.where(t.WB != 0)
    ok = t.wbg_vs_parts.between(0.995, 1.005)
    detail = (f"WBG = WB + IFC + MIGA holds within 0.5% for {ok.sum()} of {len(t)} indicator-snapshots (global, achieved; "
              "economy counts are excluded because one economy can be supported by several institutions). "
              f"IBRD + IDA exceeds WB in {(t.wb_vs_ibrd_ida > 1.005).sum()} cases (projects with both IBRD and IDA "
              "financing are counted once in WB), so IBRD and IDA must never be summed.")
    return Check("Institution hierarchy (never sum across org_code)", "PASS" if ok.mean() > 0.9 else "WARN", detail,
                 t[~ok | (t.wb_vs_ibrd_ida > 1.005)].round(4).head(20))


def check_region_totals(con) -> Check:
    t = _df(con, f"""
        SELECT snapshot_fy, ind_code,
               sum(achieved) FILTER (WHERE area_code = 'ACW') AS global_total,
               sum(achieved) FILTER (WHERE area_type = 'REGION' AND area_code NOT IN ('ACW', 'AFR')) AS sum_regions,
               sum(achieved) FILTER (WHERE area_type = 'COUNTRY') AS sum_countries
        FROM indicator_values
        WHERE {HEADLINE} AND org_code = 'WBG' AND unit IN {ADDITIVE_UNITS}
        GROUP BY ALL HAVING global_total > 0 ORDER BY 2, 1""")
    t["regions_vs_global"] = t.sum_regions / t.global_total
    t["countries_vs_global"] = t.sum_countries / t.global_total
    ok = t.regions_vs_global.between(0.98, 1.02)
    detail = (f"Regions (incl. 'Other') sum to the global total (ACW) within 2% in {ok.sum()} of {len(t)} cases. "
              f"Country rows cover a median {t.countries_vs_global.median():.1%} of the global total; the rest is from "
              "multi-country/regional operations. Use ACW for global totals, never the sum of countries.")
    return Check("Regional rows add up to the global total", "PASS" if ok.mean() > 0.9 else "WARN", detail,
                 t[~ok].round(4).head(20))


def check_country_codes(con) -> Check:
    t = _df(con, """
        SELECT DISTINCT r.snapshot_fy, r.area_code, r.area_name FROM results r
        ANTI JOIN countries k ON k.snapshot_fy = r.snapshot_fy AND k.country_code = r.area_code
        WHERE r.area_type = 'COUNTRY' ORDER BY 1, 2""")
    return Check("Result country codes match the country dimension", "PASS" if t.empty else "WARN",
                 "All country rows join to the country dimension." if t.empty
                 else f"{len(t)} snapshot-specific codes filed under COUNTRY are multi-country groupings "
                      "(e.g. 1W World, 3A Africa) or legacy codes; `country_results.is_economy` flags them so "
                      "country rankings can exclude them.", t.head(30))


def check_negative(con) -> Check:
    t = _df(con, """
        SELECT ind_code, unit, count(*) n_negative FROM indicator_values
        WHERE achieved < 0 OR expected < 0 GROUP BY ALL ORDER BY n_negative DESC""")
    unexpected = t[~t.ind_code.isin(["CSC_RES_GHG_EMS_YEAR", "EN_ATM_GHGT_GT_CE"])]
    return Check("Negative values", "PASS" if unexpected.empty else "WARN",
                 "Negative values for GHG indicators are expected (net reductions / net removals)."
                 + ("" if unexpected.empty else f" {int(unexpected.n_negative.sum())} other negative value(s) look like "
                    "source errors and are left as published: " + ", ".join(unexpected.ind_code)), t)


def check_projects(con) -> Check:
    t = _df(con, """
        WITH p AS (SELECT snapshot_fy, ind_code, sum(expected) proj_expected, count(DISTINCT proj_id) n_projects
                   FROM projects WHERE sex = '_T' AND age = '_T' AND sub_ind_code IS NULL GROUP BY ALL),
             r AS (SELECT snapshot_fy, ind_code, expected wb_expected FROM results WHERE org_code = 'WB' AND area_code = 'ACW')
        SELECT p.*, r.wb_expected, p.proj_expected / nullif(r.wb_expected, 0) AS coverage
        FROM p LEFT JOIN r USING (snapshot_fy, ind_code) ORDER BY ind_code, snapshot_fy""")
    n_proj = _df(con, "SELECT count(DISTINCT proj_id) n FROM projects").n[0]
    full = t.coverage.between(0.98, 1.02)
    partial = t[~full & t.coverage.notna()]
    return Check("Project-level data reconciles to WB totals", "PASS" if partial.empty else "WARN",
                 f"{n_proj} distinct World Bank (IBRD/IDA) projects; IFC and MIGA report only aggregates. "
                 f"Summed project expected values match the WB global total within 2% for {full.sum()} of "
                 f"{t.coverage.notna().sum()} indicator-snapshots. The rest are listed below: project drill-downs "
                 "for these are not exhaustive.", partial.round(3))


CHECKS = [check_coverage, check_grain, check_results_unique, check_headline, check_display_units,
          check_org_hierarchy, check_region_totals, check_country_codes, check_negative, check_projects]


def run_checks(db_path: Path = config.DB_PATH) -> list[Check]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return [fn(con) for fn in CHECKS]
    finally:
        con.close()


def write_report(checks: list[Check], out_dir: Path = config.CLEAN_DIR) -> Path:
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    counts = con.execute("""
        SELECT table_name, estimated_size AS rows FROM duckdb_tables() ORDER BY table_name""").df()
    info = json.loads(con.execute("SELECT info FROM build_info").fetchone()[0])
    con.close()
    lines = ["# Data quality report", "",
             f"Built {info['built_at']} from `{info['source']}`; snapshots {info['snapshots']}.", "",
             "| Check | Status |", "|---|---|"]
    lines += [f"| {c.name} | **{c.status}** |" for c in checks]
    lines += ["", "## Tables", "", counts.to_markdown(index=False), ""]
    for c in checks:
        lines += [f"## {c.name}: {c.status}", "", c.detail, ""]
        if not c.evidence.empty:
            lines += [c.evidence.head(25).to_markdown(index=False), ""]
    path = out_dir / "data_quality_report.md"
    path.write_text("\n".join(lines))
    (out_dir / "data_quality_report.json").write_text(json.dumps(
        [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks], indent=1))
    return path
