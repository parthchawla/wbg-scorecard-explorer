"""Data-access layer for the Scorecard database.

Plain functions over a read-only DuckDB connection that return small,
JSON-serialisable dicts. The MCP server (app/mcp_server.py) exposes them as
tools; tests call them directly. Every function applies the data rules from
pipeline/README.md (headline series, total disaggregations, no summing across
institutions, ACW for global totals) so callers can't get them wrong.
"""

from __future__ import annotations

import difflib
import math
import re
import threading
from functools import lru_cache
from typing import Any

import duckdb

from pipeline import config
from pipeline.transform import HEADLINE_FALLBACK


class ScorecardQueryError(ValueError):
    """User-correctable error; the message tells the caller how to fix the request."""


# ----------------------------------------------------------------------------- connection

_local = threading.local()


@lru_cache(maxsize=1)
def _root_connection() -> duckdb.DuckDBPyConnection:
    if not config.DB_PATH.exists():
        raise RuntimeError(f"database not found at {config.DB_PATH}; run `python -m pipeline --offline`")
    # External access off: SQL can't read local files, fetch URLs or load extensions.
    return duckdb.connect(str(config.DB_PATH), read_only=True, config={"enable_external_access": False})


def cursor() -> duckdb.DuckDBPyConnection:
    """One cursor per thread (DuckDB connections are not safe for concurrent use)."""
    cur = getattr(_local, "cur", None)
    if cur is None:
        cur = _local.cur = _root_connection().cursor()
    return cur


def rows(sql: str, params: list | None = None) -> list[dict[str, Any]]:
    cur = cursor().execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, (_clean(v) for v in r))) for r in cur.fetchall()]


def _clean(v: Any) -> Any:
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        if v.is_integer() and abs(v) < 1e15:
            return int(v)
        return float(f"{v:.6g}") if abs(v) < 1e6 else round(v, 1)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


# ------------------------------------------------------------------------------ reference


@lru_cache(maxsize=1)
def latest_snapshot() -> int:
    return rows("SELECT max(snapshot_fy) AS fy FROM indicator_values")[0]["fy"]


@lru_cache(maxsize=1)
def snapshots() -> list[int]:
    return [r["fy"] for r in rows("SELECT DISTINCT snapshot_fy AS fy FROM indicator_values ORDER BY 1")]


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict[str, Any]]:
    out = {}
    for r in rows("""
        SELECT c.ind_code, c.ind_type AS tier, c.ind_name AS name, c.definition, c.long_definition, c.unit,
               c.outcome_area, c.scale_type, c.reports_achieved, c.reports_expected,
               list(DISTINCT v.snapshot_fy ORDER BY v.snapshot_fy) FILTER (WHERE v.snapshot_fy IS NOT NULL) AS snapshots_with_data
        FROM indicator_catalog c LEFT JOIN indicator_values v USING (ind_code)
        GROUP BY ALL ORDER BY c.ind_type DESC, c.outcome_area, c.ind_code"""):
        scale = r.pop("scale_type") or ""
        r["better_when"] = "lower" if scale.endswith("_rev") else "higher"
        out[r["ind_code"]] = r
    return out


def indicator(ind_code: str) -> dict[str, Any]:
    code = (ind_code or "").strip().upper()
    cat = catalog()
    if code not in cat:
        close = difflib.get_close_matches(code, list(cat), n=3, cutoff=0.6)
        raise ScorecardQueryError(
            f"Unknown indicator code '{ind_code}'. Use search_indicators to find codes"
            + (f"; similar: {', '.join(close)}" if close else "") + "."
        )
    return cat[code]


def _require_results(ind: dict) -> None:
    if ind["tier"] != "WBG Results":
        raise ScorecardQueryError(
            f"{ind['ind_code']} is a {ind['tier']} indicator. Use get_context_trend for Client Context and Vision indicators."
        )
    if not ind["snapshots_with_data"]:
        raise ScorecardQueryError(f"{ind['ind_code']} ({ind['name']}) has no published data in any snapshot yet.")


def _snapshot(snapshot_fy: int | None) -> int:
    if snapshot_fy is None:
        return latest_snapshot()
    if snapshot_fy not in snapshots():
        raise ScorecardQueryError(f"Snapshot FY{snapshot_fy} not available; choose one of {snapshots()}.")
    return snapshot_fy


# Plain-language synonyms -> indicator codes, used by search_indicators.
TOPIC_SYNONYMS = {
    "digital": ["CSC_RES_BRO_INTE", "CSC_RES_DIG_ENA_SERV", "IT_NET_USER_ZS", "IT_GOV_EGOV_XQ"],
    "internet": ["CSC_RES_BRO_INTE", "IT_NET_USER_ZS"],
    "broadband": ["CSC_RES_BRO_INTE", "IT_NET_USER_ZS"],
    "climate": ["CSC_RES_RESI_CLIM_RISK", "CSC_RES_GHG_EMS_YEAR", "EN_CLM_VULN", "EN_ATM_GHGT_GT_CE"],
    "resilience": ["CSC_RES_RESI_CLIM_RISK", "EN_CLM_VULN"],
    "emissions": ["CSC_RES_GHG_EMS_YEAR", "EN_ATM_GHGT_GT_CE"],
    "energy": ["CSC_RES_ELC_ACCS", "CSC_RES_REN_ENER_ENAB", "EG_ELC_ACCS_ZS"],
    "electricity": ["CSC_RES_ELC_ACCS", "EG_ELC_ACCS_ZS"],
    "power": ["CSC_RES_ELC_ACCS", "CSC_RES_REN_ENER_ENAB"],
    "renewable": ["CSC_RES_REN_ENER_ENAB"],
    "education": ["CSC_RES_EDU_SUPP", "SE_LPV_PRIM"],
    "school": ["CSC_RES_EDU_SUPP", "SE_LPV_PRIM"],
    "learning": ["CSC_RES_EDU_SUPP", "SE_LPV_PRIM"],
    "health": ["CSC_RES_HEA_SERV", "CSC_RES_HEA_EMER_BENE", "SH_UHC_SRVS_CV_XD", "SH_STA_STNT_ME_ZS"],
    "pandemic": ["CSC_RES_HEA_EMER_BENE"],
    "nutrition": ["CSC_RES_FOOD_NUTR_SECU", "SH_STA_STNT_ME_ZS", "SN_ITK_MSFI_ZS_CC"],
    "food": ["CSC_RES_FOOD_NUTR_SECU", "SN_ITK_MSFI_ZS_CC", "SN_ITK_MSFI_ZS"],
    "agriculture": ["CSC_RES_FOOD_NUTR_SECU"],
    "water": ["CSC_RES_WAT_SAN_HYG_TOT", "SH_H2O_STA_HYGN_ZS_TO", "SH_H2O_STA_HYGN_TO"],
    "sanitation": ["CSC_RES_WAT_SAN_HYG_TOT", "SH_H2O_STA_HYGN_ZS_TO"],
    "transport": ["CSC_RES_ACCS_TRANS_INFRA_SERV", "SP_ROD_R2KM"],
    "roads": ["CSC_RES_ACCS_TRANS_INFRA_SERV", "SP_ROD_R2KM"],
    "social protection": ["CSC_RES_SOC_SAF_PROG", "PER_ALLSP_COV_POP_TO"],
    "safety net": ["CSC_RES_SOC_SAF_PROG", "PER_ALLSP_COV_POP_TO"],
    "cash transfer": ["CSC_RES_SOC_SAF_PROG"],
    "poverty": ["SI_POV_DDAY_TO", "CSC_CLI_EXT_POOR_FCS", "SI_POV_PROS", "CSC_RES_SOC_SAF_PROG"],
    "inequality": ["SI_DST_INEQ"],
    "gender": ["CSC_RES_GEN_EQU_BENE", "CSC_RES_FIN_SERV_WOM", "FX_OWN_TO"],
    "women": ["CSC_RES_GEN_EQU_BENE", "CSC_RES_FIN_SERV_WOM", "FX_OWN_TO"],
    "finance": ["CSC_RES_FIN_SERV_WOM", "FX_OWN_TO"],
    "financial inclusion": ["CSC_RES_FIN_SERV_WOM", "FX_OWN_TO"],
    "jobs": ["CSC_RES_NEW_JOBS_WOM_YOU", "SL_EMP_WORK_TO", "SL_UEM_NEET_ME_TO"],
    "employment": ["CSC_RES_NEW_JOBS_WOM_YOU", "SL_EMP_WORK_TO", "SL_UEM_NEET_ME_TO"],
    "youth": ["CSC_RES_NEW_JOBS_WOM_YOU", "SL_UEM_NEET_ME_TO"],
    "private sector": ["CSC_RES_PRIV_CAP_MOBL", "CSC_RES_PRIV_CAP_ENAB", "NE_GDI_FPRV_ZS"],
    "investment": ["CSC_RES_PRIV_CAP_MOBL", "CSC_RES_PRIV_CAP_ENAB", "NE_GDI_FPRV_ZS"],
    "debt": ["CSC_RES_DEBT_SUST_RISK", "FI_DEB_RISK"],
    "tax": ["CSC_RES_TAX_REV_GDP", "FI_TAX_GD_ZS"],
    "fiscal": ["CSC_RES_DEBT_SUST_RISK", "CSC_RES_TAX_REV_GDP", "FI_DEB_RISK", "FI_TAX_GD_ZS"],
    "fragile": ["CSC_RES_DISP_COMM_SERVICES", "CSC_CLI_EXT_POOR_FCS", "SM_POP_FDIP"],
    "conflict": ["CSC_RES_DISP_COMM_SERVICES", "CSC_CLI_EXT_POOR_FCS", "SM_POP_FDIP"],
    "refugees": ["CSC_RES_DISP_COMM_SERVICES", "SM_POP_FDIP"],
    "displaced": ["CSC_RES_DISP_COMM_SERVICES", "SM_POP_FDIP"],
    "biodiversity": ["CSC_RES_TER_AQU_HECT", "ER_PTD_TOTL_ZS", "ER_LND_HEAL", "EN_FSH_SUST_ZS"],
    "nature": ["CSC_RES_TER_AQU_HECT", "ER_PTD_TOTL_ZS", "ER_NCA_RNEW"],
    "forest": ["CSC_RES_TER_AQU_HECT", "ER_LND_HEAL"],
    "air pollution": ["EN_ATM_HAZA"],
}


# ------------------------------------------------------------------------------- areas

AREA_TYPES = {
    "global": "REGION", "region": "REGION", "income": "INCOME", "fcs": "FCS", "ldc": "LDC",
    "sids": "SIDS", "small_state": "SMALLSTATE", "country": "COUNTRY",
}
GLOBAL_WORDS = {"global", "world", "all", "all countries", "total", "acw", "wbg", "everywhere"}


@lru_cache(maxsize=1)
def _area_index() -> list[dict[str, Any]]:
    """Every area that appears in the data, with lookup keys (codes, names, ISO3)."""
    areas = rows("""
        SELECT area_type, area_code, arg_max(area_name, snapshot_fy) AS area_name
        FROM indicator_values WHERE area_type <> 'COUNTRY' GROUP BY ALL
        UNION ALL
        SELECT 'COUNTRY', country_code, arg_max(country_name, snapshot_fy) FROM countries GROUP BY ALL""")
    iso3 = {r["country_code"]: r["iso3"] for r in rows("SELECT DISTINCT country_code, iso3 FROM countries")}
    seen, out = set(), []
    for a in areas:
        key = (a["area_type"], a["area_code"])
        if key in seen:
            continue
        seen.add(key)
        keys = {a["area_code"].lower(), (a["area_name"] or "").lower()}
        if a["area_type"] == "COUNTRY" and iso3.get(a["area_code"]):
            keys.add(iso3[a["area_code"]].lower())
        out.append({**a, "keys": keys})
    return out


def resolve_area(text: str) -> dict[str, str]:
    """Map free text ('Kenya', 'KEN', 'South Asia', 'SAR', 'fragile states', 'low income') to an area."""
    t = (text or "").strip().lower()
    if not t:
        raise ScorecardQueryError("Empty area name.")
    if t in GLOBAL_WORDS:
        return {"area_type": "REGION", "area_code": "ACW", "area_name": "All Countries"}
    aliases = {"fragile": "FCS", "fragile states": "FCS", "fcv": "FCS", "fragile and conflict-affected": "FCS",
               "low income": "LIC", "lower middle income": "LMC", "upper middle income": "UMC", "high income": "HIC",
               "mena": "MENAAP", "middle east": "MENAAP", "africa": "AFE", "turkey": "TR"}
    t = aliases.get(t, t).lower()
    idx = _area_index()
    exact = [a for a in idx if t in a["keys"]]
    if not exact:
        exact = [a for a in idx if any(t in k for k in a["keys"] if len(t) >= 4)]
    if not exact:
        raise ScorecardQueryError(
            f"Could not find an area matching '{text}'. Try a country name or ISO code, a region code "
            "(AFE, AFW, EAP, ECA, LCR, MENAAP, SAR), an income group (LIC, LMC, UMC, HIC), FCS, LDC, SIDS, or 'global'."
        )
    # Prefer countries over groupings with the same name, then non-NON- codes.
    exact.sort(key=lambda a: (a["area_code"].startswith("NON"), a["area_type"] != "COUNTRY"))
    a = exact[0]
    return {"area_type": a["area_type"], "area_code": a["area_code"], "area_name": a["area_name"]}


# ------------------------------------------------------------------------------- series

SERIES_FILTERS = {
    None: ("is_headline", "sex = '_T' AND age = '_T' AND disability = '_T'"),
    "women": ("is_headline", "sex = 'F' AND age = '_T' AND disability = '_T'"),
    "youth": ("is_headline", "sex = '_T' AND age = 'Y14T24' AND disability = '_T'"),
    "disability_inclusive": ("is_headline", "sex = '_T' AND age = '_T' AND disability = 'Yes'"),
}


def _series_clause(ind_code: str, series: str | None) -> tuple[str, list, str]:
    """SQL filter for the requested series; returns (clause, params, label)."""
    s = (series or "").strip()
    key = s.lower() or None
    if key in SERIES_FILTERS:
        head, disagg = SERIES_FILTERS[key]
        label = {None: "total", "women": "women and girls (subset of total)", "youth": "youth aged 15-24 (subset of total)",
                 "disability_inclusive": "results from disability-inclusive projects (subset of total)"}[key]
        return f"{head} AND {disagg} AND joint_programming = '_T'", [], label
    subs = rows("SELECT DISTINCT sub_ind_code FROM indicator_values WHERE ind_code = ? AND sub_ind_code IS NOT NULL", [ind_code])
    codes = [r["sub_ind_code"] for r in subs]
    if s.upper() in codes:
        return ("sub_ind_code = ? AND sex = '_T' AND age = '_T' AND disability = '_T' AND joint_programming = '_T'",
                [s.upper()], f"sub-indicator {s.upper()}")
    raise ScorecardQueryError(
        f"Unknown series '{series}'. Use one of: women, youth, disability_inclusive"
        + (f", or a sub-indicator code: {', '.join(codes)}" if codes else "") + "."
    )


# ---------------------------------------------------------------------------- tools


def search_indicators(query: str = "", tier: str = "any", outcome_area: str | None = None) -> dict[str, Any]:
    cat = list(catalog().values())
    if tier and tier.lower() != "any":
        cat = [c for c in cat if c["tier"].lower() == tier.lower()]
    if outcome_area:
        oa = outcome_area.lower()
        cat = [c for c in cat if c["outcome_area"] and oa in c["outcome_area"].lower()]
    q = (query or "").lower().strip()
    if q:
        boosted = {code for word, codes in TOPIC_SYNONYMS.items() if word in q for code in codes}
        words = [w for w in re.findall(r"[a-z0-9]+", q) if len(w) > 2 and w not in {"the", "and", "for", "with", "people", "number"}]

        def score(c: dict) -> int:
            text = " ".join(str(c.get(k) or "") for k in ("ind_code", "name", "definition", "outcome_area")).lower()
            return 10 * (c["ind_code"] in boosted) + sum(w in text for w in words) + 20 * (q.upper() == c["ind_code"])

        scored = sorted(((score(c), c) for c in cat), key=lambda x: -x[0])
        cat = [c for s, c in scored if s > 0]
    results = [
        {k: c[k] for k in ("ind_code", "name", "tier", "outcome_area", "unit", "reports_achieved",
                           "reports_expected", "better_when", "snapshots_with_data")}
        for c in cat[:15]
    ]
    return {
        "matches": results,
        "count": len(results),
        "note": None if results else "No indicator matched. Try a broader word (e.g. 'energy', 'health', 'jobs') or tier='any'.",
    }


def get_indicator_profile(ind_code: str) -> dict[str, Any]:
    ind = indicator(ind_code)
    code = ind["ind_code"]
    out: dict[str, Any] = {k: ind[k] for k in ("ind_code", "name", "tier", "outcome_area", "unit", "definition",
                                               "better_when", "reports_achieved", "reports_expected", "snapshots_with_data")}
    if ind["long_definition"] and ind["long_definition"] != ind["definition"]:
        out["long_definition"] = ind["long_definition"]
    out["sub_indicators"] = rows("""
        SELECT DISTINCT s.sub_ind_code, s.sub_ind_name FROM sub_indicators s
        WHERE s.ind_code = ? AND s.snapshot_fy = (SELECT max(snapshot_fy) FROM sub_indicators WHERE ind_code = ?)
        ORDER BY 1""", [code, code])
    if ind["tier"] == "WBG Results":
        out["global_totals"] = rows("""
            SELECT snapshot_fy, org_code AS institution, achieved, expected,
                   round(achieved_to_expected, 3) AS achieved_to_expected
            FROM results WHERE ind_code = ? AND area_code = 'ACW'
            ORDER BY snapshot_fy, CASE org_code WHEN 'WBG' THEN 0 WHEN 'WB' THEN 1 WHEN 'IBRD' THEN 2
                     WHEN 'IDA' THEN 3 WHEN 'IDA-21' THEN 4 WHEN 'IFC' THEN 5 ELSE 6 END""", [code])
        out["breakdowns_available"] = [r["area_type"] for r in rows(
            "SELECT DISTINCT area_type FROM results WHERE ind_code = ? ORDER BY 1", [code])]
        out["related_client_context"] = [
            {"ind_code": c["ind_code"], "name": c["name"]} for c in catalog().values()
            if c["tier"] == "Client Context" and c["outcome_area"] == ind["outcome_area"]]
    else:
        out["latest_global"] = rows("""
            SELECT country_group, series_code, obs_year, value FROM context
            WHERE ind_code = ? AND area_code = 'ACW' AND snapshot_fy = (SELECT max(snapshot_fy) FROM context WHERE ind_code = ?)
            QUALIFY obs_year = max(obs_year) OVER (PARTITION BY country_group, series_code)
            ORDER BY series_code, country_group""", [code, code])
        out["related_wbg_results"] = [
            {"ind_code": c["ind_code"], "name": c["name"]} for c in catalog().values()
            if c["tier"] == "WBG Results" and ind["outcome_area"] and c["outcome_area"] == ind["outcome_area"]]
    out["caveats"] = _caveats(ind)
    return out


def _caveats(ind: dict) -> list[str]:
    notes = []
    code = ind["ind_code"]
    if not ind["snapshots_with_data"]:
        notes.append("No published data yet for this indicator.")
    if ind["tier"] == "WBG Results":
        if not ind["reports_achieved"] or code in ("CSC_RES_GHG_EMS_YEAR", "CSC_RES_PRIV_CAP_MOBL"):
            notes.append("Reports expected results only (achieved-results methodology still being developed).")
        if ind["unit"] in ("Percentage", "Countries/Economies"):
            notes.append(f"Unit is {ind['unit']}: not additive across places or institutions.")
        if code == "CSC_RES_GHG_EMS_YEAR":
            notes.append("Negative values mean a net reduction in emissions (MtCO2eq per year).")
        if code == "CSC_RES_ELC_ACCS":
            notes.append("Project-level data explains only ~55-63% of the FY2025-26 World Bank totals.")
        notes.append("Never add institutions: WBG = WB + IFC + MIGA, and IBRD + IDA can exceed WB.")
    else:
        notes.append("Client Context/Vision values describe conditions in countries; they are not WBG results.")
    return notes


def get_results(
    ind_code: str,
    breakdown: str = "region",
    institution: str = "WBG",
    snapshot_fy: int | None = None,
    compare_snapshots: bool = False,
    series: str | None = None,
    sort_by: str = "achieved",
    top_n: int = 15,
) -> dict[str, Any]:
    ind = indicator(ind_code)
    _require_results(ind)
    code = ind["ind_code"]
    fy = _snapshot(snapshot_fy)
    bd = (breakdown or "region").lower()
    org = (institution or "WBG").upper()
    top_n = max(1, min(int(top_n or 15), 250))
    clause, params, series_label = _series_clause(code, series)
    base = f"FROM indicator_values WHERE ind_type = 'WBG Results' AND ind_code = ? AND {clause}"
    p0 = [code, *params]

    if bd == "institution":
        group_sql = "org_code AS area_code, org_code AS area_name"
        where = "area_code = 'ACW'"
        org_filter, org_params = "", []
    elif bd in AREA_TYPES:
        group_sql = "area_code, any_value(area_name) AS area_name"
        if bd == "global":
            where = "area_code = 'ACW'"
        elif bd == "region":
            where = "area_type = 'REGION' AND area_code NOT IN ('ACW', 'AFR')"
        else:
            where = f"area_type = '{AREA_TYPES[bd]}'"
        org_filter, org_params = "AND org_code = ?", [org]
    else:
        raise ScorecardQueryError(
            f"Unknown breakdown '{breakdown}'. Use one of: global, region, income, fcs, ldc, sids, small_state, country, institution."
        )

    fys = snapshots() if compare_snapshots else [fy]
    data = rows(f"""
        SELECT snapshot_fy, {group_sql}, sum(achieved) AS achieved, sum(expected) AS expected
        {base} AND {where} {org_filter} AND snapshot_fy IN ({','.join('?' * len(fys))})
        GROUP BY ALL""", p0 + org_params + fys)
    if bd == "country":
        econ = {r["country_code"] for r in rows("SELECT DISTINCT country_code FROM countries")}
        data = [d for d in data if d["area_code"] in econ]
        attrs = {r["country_code"]: r for r in rows(
            "SELECT country_code, region_code, income_name, is_fcs FROM countries WHERE snapshot_fy = ?", [fy])}

    by_area: dict[str, dict[str, Any]] = {}
    for d in data:
        a = by_area.setdefault(d["area_code"], {"area_code": d["area_code"], "area_name": d["area_name"]})
        if d["snapshot_fy"] == fy:
            a["achieved"], a["expected"] = d["achieved"], d["expected"]
            a["achieved_to_expected"] = round(d["achieved"] / d["expected"], 3) if d["achieved"] is not None and d["expected"] else None
        if compare_snapshots:
            a[f"achieved_fy{d['snapshot_fy']}"] = d["achieved"]
            a[f"expected_fy{d['snapshot_fy']}"] = d["expected"]
    if compare_snapshots:
        first, last = fys[0], fys[-1]
        for a in by_area.values():
            v0, v1 = a.get(f"achieved_fy{first}"), a.get(f"achieved_fy{last}")
            a[f"change_achieved_fy{first}_to_fy{last}"] = None if v0 is None or v1 is None else round(v1 - v0, 1)
            a[f"pct_change_achieved_fy{first}_to_fy{last}"] = round(100 * (v1 - v0) / abs(v0), 1) if v0 and v1 is not None else None
    if series and series.strip().lower() in ("women", "youth", "disability_inclusive"):
        # Subgroup share of the total for the same place/institution/snapshot, so answers can quote
        # "48.2% of students supported were women and girls" without doing their own arithmetic.
        tclause, tparams, _ = _series_clause(code, None)
        totals = rows(f"""
            SELECT snapshot_fy, {group_sql}, sum(achieved) AS achieved, sum(expected) AS expected
            FROM indicator_values WHERE ind_type = 'WBG Results' AND ind_code = ? AND {tclause} AND {where} {org_filter}
              AND snapshot_fy IN ({','.join('?' * len(fys))}) GROUP BY ALL""", [code, *tparams] + org_params + fys)
        tmap = {(t["snapshot_fy"], t["area_code"]): t for t in totals}
        for a in by_area.values():
            for f in fys:
                t = tmap.get((f, a["area_code"]))
                if not t:
                    continue
                sub_a = a.get("achieved") if f == fy else a.get(f"achieved_fy{f}")
                sub_e = a.get("expected") if f == fy else a.get(f"expected_fy{f}")
                sfx = "" if f == fy else f"_fy{f}"
                if f == fy:
                    a["total_achieved"], a["total_expected"] = t["achieved"], t["expected"]
                if sub_a is not None and t["achieved"]:
                    a[f"share_of_total_achieved{sfx}"] = round(sub_a / t["achieved"], 3)
                if sub_e is not None and t["expected"]:
                    a[f"share_of_total_expected{sfx}"] = round(sub_e / t["expected"], 3)
    global_row = rows(f"SELECT sum(achieved) AS achieved, sum(expected) AS expected {base} AND area_code = 'ACW' AND org_code = ? AND snapshot_fy = ?",
                      p0 + [org, fy])[0] if bd != "institution" else None
    additive = ind["unit"] not in ("Percentage", "Countries/Economies")
    for a in by_area.values():
        if bd == "country" and a["area_code"] in attrs:
            at = attrs[a["area_code"]]
            a.update(region=at["region_code"], income=at["income_name"], fcs=at["is_fcs"])
        if additive and global_row and global_row["achieved"] and a.get("achieved") is not None and bd not in ("global", "institution"):
            a["share_of_global_achieved"] = round(a["achieved"] / global_row["achieved"], 3)

    key = {"achieved": "achieved", "expected": "expected", "achieved_to_expected": "achieved_to_expected",
           "change": f"change_achieved_fy{fys[0]}_to_fy{fys[-1]}" if compare_snapshots else "achieved"}.get(sort_by, "achieved")
    ordered = sorted(by_area.values(), key=lambda a: (a.get(key) is None, -(a.get(key) or 0)))
    notes = list(_caveats(ind))
    if bd == "country":
        notes.append("Countries do not sum to the global total (multi-country projects); only economies with reported results are listed.")
    if bd == "region":
        notes.append("'OTH' (Other) covers global or multi-region operations. MENAAP (FY2025+) and MNA (FY2024) differ in coverage.")
    if compare_snapshots:
        notes.append("Snapshot-to-snapshot changes are indicative: definitions and coverage were refined between editions.")
    if bd == "institution":
        notes.append("Institution rows overlap (WBG includes WB, IFC, MIGA; WB includes IBRD and IDA). Do not add them.")
    return {
        "indicator": {"ind_code": code, "name": ind["name"], "unit": ind["unit"]},
        "snapshot_fy": fy,
        "institution": None if bd == "institution" else org,
        "breakdown": bd,
        "series": series_label,
        "global_total": global_row,
        "rows": ordered[:top_n],
        "rows_total": len(ordered),
        "truncated": len(ordered) > top_n,
        "notes": notes,
    }


def get_country_profile(country: str, snapshot_fy: int | None = None) -> dict[str, Any]:
    area = resolve_area(country)
    if area["area_type"] != "COUNTRY":
        raise ScorecardQueryError(f"'{country}' matched the group '{area['area_name']}', not a country. Use get_results with a breakdown instead.")
    cc = area["area_code"]
    fy = _snapshot(snapshot_fy)
    attrs = rows("""SELECT country_name, iso3, region_name, income_name, lending_eligibility, is_fcs, is_ldc, is_sids, is_small_state
                    FROM countries WHERE country_code = ? ORDER BY snapshot_fy DESC LIMIT 1""", [cc])
    results = rows("""
        SELECT r.ind_code, r.ind_name AS name, r.unit, r.outcome_area,
               r.achieved, r.expected, round(r.achieved_to_expected, 3) AS achieved_to_expected,
               p.achieved AS achieved_prev_snapshot
        FROM results r
        LEFT JOIN results p ON p.ind_code = r.ind_code AND p.org_code = 'WBG' AND p.area_code = r.area_code AND p.snapshot_fy = r.snapshot_fy - 1
        WHERE r.area_type = 'COUNTRY' AND r.area_code = ? AND r.org_code = 'WBG' AND r.snapshot_fy = ?
          AND (coalesce(r.achieved, 0) <> 0 OR coalesce(r.expected, 0) <> 0)
        ORDER BY r.outcome_area, r.ind_code""", [cc, fy])
    context = rows("""
        WITH c AS (SELECT * FROM context WHERE ind_type = 'Client Context' AND is_headline AND snapshot_fy = ?
                   AND country_group = 'WBG' AND value IS NOT NULL),
             latest AS (SELECT * FROM c WHERE area_type = 'COUNTRY' AND area_code = ?
                        QUALIFY obs_year = max(obs_year) OVER (PARTITION BY ind_code))
        SELECT l.ind_code, l.ind_name AS name, l.unit, l.obs_year, l.value AS country_value,
               -- Only rates (percentages, indexes) are comparable with the all-client-countries figure;
               -- for counts (people, economies) the group value is a total, not an average.
               CASE WHEN l.unit ILIKE '%percent%' OR l.unit ILIKE '%index%' THEN g.value END AS all_client_countries_value,
               CASE WHEN l.scale_type LIKE '%_rev' THEN 'lower' ELSE 'higher' END AS better_when
        FROM latest l LEFT JOIN c g ON g.ind_code = l.ind_code AND g.area_code = 'ACW' AND g.obs_year = l.obs_year
        ORDER BY l.ind_code""", [fy, cc])
    proj = rows("""SELECT count(*) AS n_projects, sum(c) AS commitment_usd FROM (
                       SELECT proj_id, max(commitment_usd) AS c FROM project_results
                       WHERE country_code = ? AND snapshot_fy = ? GROUP BY proj_id)""", [cc, fy])[0]
    return {
        "country": {"code": cc, **(attrs[0] if attrs else {"country_name": area["area_name"]})},
        "snapshot_fy": fy,
        "institution": "WBG",
        "wbg_results": results,
        "client_context": context,
        "world_bank_projects_reporting": proj["n_projects"],
        "world_bank_projects_commitment_usd": proj["commitment_usd"],
        "notes": [
            "WBG results shown are achieved/expected for the whole Group; indicators with no reported result are omitted.",
            "achieved_prev_snapshot is from the previous snapshot; changes are indicative.",
            "Client Context values describe the country's situation (all sources, not only WBG); compare with all_client_countries_value.",
            "World Bank project counts cover IBRD/IDA operations that report on Scorecard indicators.",
        ],
    }


def _project_rows(where: str, params: list, sort_by: str, limit: int) -> list[dict[str, Any]]:
    sort_col = {"expected": "expected", "achieved": "achieved", "commitment": "commitment_usd",
                "approval_date": "approval_date"}.get(sort_by, "expected")
    fallback_list = ",".join(f"'{v}'" for v in HEADLINE_FALLBACK.values())
    return rows(f"""
        WITH base AS (SELECT * FROM project_results WHERE {where}),
        -- per project x indicator: headline (null sub) rows if present, else the named total
        -- sub-indicator, else the sum of component sub-indicators.
        ranked AS (
          SELECT *, CASE WHEN sub_ind_code IS NULL THEN 0 WHEN sub_ind_code IN ({fallback_list}) THEN 1 ELSE 2 END AS pri
          FROM base),
        chosen AS (SELECT * FROM ranked QUALIFY pri = min(pri) OVER (PARTITION BY proj_id, ind_code))
        SELECT proj_id, any_value(project_name) AS project_name, any_value(country_name) AS country,
               any_value(region_code) AS region, ind_code, any_value(ind_name) AS indicator, any_value(unit) AS unit,
               sum(achieved) AS achieved, sum(expected) AS expected,
               max(commitment_usd) AS commitment_usd, any_value(approval_fy) AS approval_fy, any_value(closing_fy) AS closing_fy,
               any_value(status) AS status, any_value(project_url) AS url, max(approval_date) AS approval_date
        FROM chosen GROUP BY proj_id, ind_code
        ORDER BY {sort_col} DESC NULLS LAST LIMIT ?""", params + [limit])


def search_projects(
    ind_code: str | None = None,
    country: str | None = None,
    region: str | None = None,
    keyword: str | None = None,
    snapshot_fy: int | None = None,
    sort_by: str = "expected",
    limit: int = 10,
) -> dict[str, Any]:
    fy = _snapshot(snapshot_fy)
    where, params = ["snapshot_fy = ?"], [fy]
    label: dict[str, Any] = {}
    if ind_code:
        ind = indicator(ind_code)
        where.append("ind_code = ?"), params.append(ind["ind_code"])
        label["indicator"] = ind["name"]
    if country:
        area = resolve_area(country)
        if area["area_type"] != "COUNTRY":
            raise ScorecardQueryError(f"'{country}' is not a country; use region= for regions.")
        where.append("country_code = ?"), params.append(area["area_code"])
        label["country"] = area["area_name"]
    if region:
        area = resolve_area(region)
        if area["area_type"] != "REGION" or area["area_code"] == "ACW":
            raise ScorecardQueryError("region must be a World Bank region code or name (AFE, AFW, EAP, ECA, LCR, MENAAP, SAR).")
        where.append("region_code = ?"), params.append(area["area_code"])
        label["region"] = area["area_name"]
    if keyword:
        where.append("(project_name ILIKE ? OR project_description ILIKE ?)"), params.extend([f"%{keyword}%"] * 2)
        label["keyword"] = keyword
    limit = max(1, min(int(limit or 10), 50))
    found = _project_rows(" AND ".join(where), params, sort_by, limit)
    return {
        "snapshot_fy": fy,
        "filters": label,
        "projects": found,
        "notes": [
            "World Bank (IBRD/IDA) projects only; IFC and MIGA do not publish project-level Scorecard results.",
            "achieved/expected are each project's contribution to the indicator; commitment_usd is the project's total net commitment.",
        ],
    }


def get_context_trend(
    ind_code: str,
    areas: list[str] | None = None,
    country_group: str = "WBG",
    start_year: int | None = None,
    series: str | None = None,
) -> dict[str, Any]:
    ind = indicator(ind_code)
    if ind["tier"] == "WBG Results":
        raise ScorecardQueryError(f"{ind['ind_code']} is a WBG Results indicator; use get_results instead.")
    code = ind["ind_code"]
    fy = rows("SELECT max(snapshot_fy) AS fy FROM context WHERE ind_code = ?", [code])[0]["fy"]
    if fy is None:
        raise ScorecardQueryError(f"{code} has no data.")
    resolved = [resolve_area(a) for a in (areas or [])] or [{"area_type": "REGION", "area_code": "ACW", "area_name": "All Countries"}]
    series_rows = rows("SELECT DISTINCT series_code, sub_ind_name, is_headline FROM context WHERE ind_code = ? AND snapshot_fy = ?", [code, fy])
    if series:
        chosen = [s["series_code"] for s in series_rows if s["series_code"].upper() == series.upper()]
        if not chosen:
            raise ScorecardQueryError(f"Unknown series '{series}' for {code}; available: {', '.join(s['series_code'] for s in series_rows)}.")
    else:
        chosen = [s["series_code"] for s in series_rows if s["is_headline"]] or [s["series_code"] for s in series_rows]
    group = (country_group or "WBG").upper()
    groups = rows("SELECT DISTINCT country_group FROM context WHERE ind_code = ? AND snapshot_fy = ?", [code, fy])
    gset = {g["country_group"] for g in groups}
    if group not in gset:
        group = "ALL" if "ALL" in gset else sorted(gset)[0]
    out_series = []
    for a in resolved:
        for s in chosen:
            pts = rows("""
                SELECT obs_year AS year, value FROM context
                WHERE ind_code = ? AND snapshot_fy = ? AND series_code = ? AND area_code = ? AND country_group = ?
                  AND value IS NOT NULL AND (? IS NULL OR obs_year >= ?)
                ORDER BY obs_year""", [code, fy, s, a["area_code"], group, start_year, start_year])
            if not pts and a["area_type"] == "COUNTRY":
                pts = rows("""SELECT obs_year AS year, value FROM context WHERE ind_code = ? AND snapshot_fy = ? AND series_code = ?
                              AND area_code = ? AND value IS NOT NULL AND (? IS NULL OR obs_year >= ?) ORDER BY obs_year""",
                           [code, fy, s, a["area_code"], start_year, start_year])
            out_series.append({"area_code": a["area_code"], "area_name": a["area_name"], "series_code": s,
                               "points": pts, "latest": pts[-1] if pts else None})
    return {
        "indicator": {"ind_code": code, "name": ind["name"], "tier": ind["tier"], "unit": ind["unit"], "better_when": ind["better_when"]},
        "snapshot_fy": fy,
        "country_group": group,
        "series_available": [{"series_code": s["series_code"], "name": s["sub_ind_name"]} for s in series_rows],
        "series": out_series,
        "notes": [
            "These values describe conditions in countries (all sources); they are not results of WBG projects.",
            "country_group: WBG = all WBG client countries, IBRD/IDA = IBRD- or IDA-eligible countries (applies to group areas).",
            f"Lower values are better for this indicator." if ind["better_when"] == "lower" else "Higher values are better for this indicator.",
        ],
    }


# ------------------------------------------------------------------------- dashboard


def overview() -> list[dict[str, Any]]:
    """Headline WBG global figures for every WBG Results indicator, all snapshots."""
    data = rows("""
        SELECT c.ind_code, c.name, c.outcome_area, c.unit, c.reports_achieved, c.reports_expected,
               r.snapshot_fy, r.achieved, r.expected
        FROM (SELECT ind_code, ind_name AS name, outcome_area, unit, reports_achieved, reports_expected, outcome_area_code
              FROM indicator_catalog WHERE ind_type = 'WBG Results') c
        LEFT JOIN results r ON r.ind_code = c.ind_code AND r.org_code = 'WBG' AND r.area_code = 'ACW'
        ORDER BY try_cast(regexp_extract(c.outcome_area_code, '(\\d+)', 1) AS INT), c.ind_code, r.snapshot_fy""")
    out: dict[str, dict[str, Any]] = {}
    for d in data:
        o = out.setdefault(d["ind_code"], {k: d[k] for k in ("ind_code", "name", "outcome_area", "unit",
                                                             "reports_achieved", "reports_expected")} | {"by_snapshot": {}})
        if d["snapshot_fy"]:
            o["by_snapshot"][d["snapshot_fy"]] = {"achieved": d["achieved"], "expected": d["expected"]}
    fy = latest_snapshot()
    for o in out.values():
        latest = o["by_snapshot"].get(fy, {})
        o["achieved"], o["expected"] = latest.get("achieved"), latest.get("expected")
        first = o["by_snapshot"].get(min(o["by_snapshot"]), {}) if o["by_snapshot"] else {}
        o["achieved_first"] = first.get("achieved")
        o["has_data"] = bool(o["by_snapshot"])
    return list(out.values())


def country_list() -> list[dict[str, Any]]:
    return rows("""
        SELECT country_code, iso3, country_name, region_code, region_name, income_name, is_fcs, lending_eligibility
        FROM countries WHERE snapshot_fy = (SELECT max(snapshot_fy) FROM countries) AND iso3 IS NOT NULL
        ORDER BY country_name""")


# ------------------------------------------------------------------------------ SQL

SQL_MAX_ROWS = 200
SQL_TIMEOUT_S = 10.0
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|export|import|install|load|pragma|set|reset|call|checkpoint|vacuum|use)\b",
    re.I,
)


def run_sql(sql: str) -> dict[str, Any]:
    q = (sql or "").strip().rstrip(";").strip()
    if not q:
        raise ScorecardQueryError("Empty query.")
    if ";" in q:
        raise ScorecardQueryError("Only a single SELECT statement is allowed (no ';').")
    if not re.match(r"^(select|with|from)\b", q, re.I):
        raise ScorecardQueryError("Only read-only SELECT/WITH queries are allowed.")
    if _FORBIDDEN.search(re.sub(r"'[^']*'", "''", q)):
        raise ScorecardQueryError("Query contains a forbidden keyword; only read-only SELECT queries are allowed.")
    cur = _root_connection().cursor()
    timer = threading.Timer(SQL_TIMEOUT_S, cur.interrupt)
    timer.start()
    try:
        res = cur.execute(f"SELECT * FROM ({q}) LIMIT {SQL_MAX_ROWS + 1}")
        cols = [d[0] for d in res.description]
        data = [dict(zip(cols, (_clean(v) for v in r))) for r in res.fetchall()]
    except duckdb.InterruptException:
        raise ScorecardQueryError(f"Query exceeded {SQL_TIMEOUT_S:.0f}s; add filters or aggregate.") from None
    except duckdb.Error as e:
        raise ScorecardQueryError(f"SQL error: {str(e).splitlines()[0]}. Check table and column names in the schema (scorecard://schema); explore with e.g. SELECT DISTINCT.") from None
    finally:
        timer.cancel()
        cur.close()
    return {"columns": cols, "rows": data[:SQL_MAX_ROWS], "row_count": min(len(data), SQL_MAX_ROWS),
            "truncated": len(data) > SQL_MAX_ROWS}


# ------------------------------------------------------------------------------ schema

SCHEMA_DOC = """# Database schema (DuckDB, read-only)

Start from the VIEWS: they already apply the data rules. All values are base (unrounded) values in the indicator's unit.

## View `results`: WBG Results, headline series, total disaggregation
One row per snapshot_fy x ind_code x org_code x area. Columns: snapshot_fy, as_of_date, ind_code, ind_name, outcome_area, unit,
org_code (WBG, WB, IBRD, IDA, IDA-21, IFC, MIGA), area_type (REGION, INCOME, FCS, LDC, SIDS, SMALLSTATE, COUNTRY),
area_code, area_name, country_eligibility, achieved, expected, cumulative_achieved, achieved_to_expected, footnote.
Global totals: area_code = 'ACW'. Regions: area_type='REGION' AND area_code NOT IN ('ACW','AFR'). Never SUM across org_code.

## View `results_detail`: all series and sex/age/disability splits
snapshot_fy, ind_code, ind_name, series_code, sub_ind_name, is_headline, org_code, area_type, area_code, area_name,
sex ('_T' total, 'F' female), age ('_T', 'Y14T24' youth), disability ('_T', 'Yes' = disability-inclusive subset), unit, achieved, expected.

## View `country_results`: `results` for COUNTRY rows plus attributes
Adds is_economy (false = multi-country grouping such as 'World'), iso3, region_code, region_name, income_name,
lending_eligibility, is_fcs, is_ldc, is_sids, is_small_state.

## View `context`: Client Context and Vision indicators
snapshot_fy, ind_type, ind_code, ind_name, outcome_area, series_code, sub_ind_name, is_headline,
country_group (WBG = all client countries, IBRD, IDA, ALL), area_type, area_code, area_name, obs_year (calendar year), unit, value, scale_type
(scale_type ending in '_rev' = lower is better). Use the latest snapshot_fy for each indicator.

## View `project_results`: World Bank (IBRD/IDA) project contributions (sex and age totals)
snapshot_fy, ind_code, ind_name, unit, sub_ind_code, proj_id, project_name, project_description, country_code, country_name,
region_code, approval_fy, closing_fy, status, global_practice, financier, commitment_usd, baseline, progress, target,
achieved, expected, disability_inclusive, project_url. A project can have several rows per indicator (sub-indicators).

## Tables
indicator_catalog (ind_code, ind_type, ind_name, definition, unit, outcome_area, ...), countries (snapshot_fy, country_code,
iso3, country_name, region_code, income_code, is_fcs, ...), outcome_areas, narratives, indicator_values (raw grain).
"""
