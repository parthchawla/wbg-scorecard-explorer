"""Stage 2: raw payloads -> typed, analysis-ready tables (pandas DataFrames).

Cleaning decisions (each one verified against the raw data; see
data/clean/data_quality_report.md for the evidence):

* Values: the API returns display-rounded values (`ind_achieved_val` = 729.2 with
  `achieved_uom_display_code` = "K"). We keep the unrounded *base* values
  (`ind_base_achieved_val`, ...) as `achieved` / `expected` in the indicator's
  native unit, and retain the display fields for reference.
* Time: the snapshot fiscal year is the time key. Within one snapshot the
  as-of date (`ind_time_per`) differs by institution (e.g. FY24 IFC rows are
  dated 2023-12-31 while WBG rows are 2024-06-30 and already include IFC), so
  `as_of_date` is informational only.
* Area labels renamed between snapshots are harmonised (FCV -> FCS,
  SSS -> SST); the raw codes are kept in `area_type_raw` / `area_code_raw`.
  MNA (FY24) and MENAAP (FY25+) are *not* merged: MENAAP adds Afghanistan
  and Pakistan, so the two are not comparable.
* Headline series: normally the row with no sub-indicator. Some indicators
  publish their total only as a named sub-indicator (and which one varies by
  snapshot), so HEADLINE_FALLBACK names the total series for those.
* Blank joint-programming flags are normalised to the "_T" total code.
* GHG base values are published in tCO2eq although the unit label (and the
  display value) is MtCO2eq/year; they are rescaled to MtCO2eq/year.
* FY24 has 12 WBG Results keys with two rows dated 2023-12-31 (IFC's
  calendar-year period) and 2024-06-30. Either the rows are identical or one
  holds only part of the total; WBG = WB + IFC + MIGA, so the larger row is
  kept (`dedup_note` records it).
* Client Context periods can be ranges ("2011-2021"): the raw string is kept
  as `period` and `obs_year` is its last year.
* Country names are taken from the country dimension (the raw feed mixes
  "Türkiye" and "Turkiye" within a snapshot).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .client import records
from .fetch import read_raw

log = logging.getLogger(__name__)

# Indicators whose total is only published as a sub-indicator in some
# snapshots: parent ind_code -> sub_ind_code that represents the total.
HEADLINE_FALLBACK = {
    "CSC_RES_FIN_SERV_WOM": "CSC_RES_FIN_SERV",
    "CSC_RES_GEN_EQU_BENE": "CSC_RES_GEN_EQU",
    "CSC_RES_WAT_SAN_HYG_TOT": "CSC_RES_WAT_SAN_HYG",
    "FX_OWN_TO": "FX_OWN_TOTL_ZS",
    "SL_EMP_WORK_TO": "SL_EMP_WORK_ZS",
    "SL_UEM_NEET_ME_TO": "SL_UEM_NEET_ME_ZS",
    "PER_ALLSP_COV_POP_TO": "PER_ALLSP_COV_POP_TOT",
    "SI_POV_DDAY_TO": "SI_POV_DDAY",  # $3.00/day international poverty line
}

GHG_INDICATORS = ("EN_ATM_GHGT_GT_CE", "CSC_RES_GHG_EMS_YEAR")
GHG_SCALE = 1e-6  # tCO2eq -> MtCO2eq

UNIT_ALIASES = {"Megatonnes of CO2-equivalent per year (MtCO2eq/year)": "MtCO2eq/year"}

AREA_TYPE_ALIASES = {"FCV": "FCS"}
AREA_CODE_ALIASES = {("FCS", "FCV"): "FCS", ("FCS", "NON-FCV"): "NON-FCS", ("SMALLSTATE", "SSS"): "SST"}
TOTAL = "_T"


def _load(pattern: str) -> list[dict]:
    rows: list[dict] = []
    for f in sorted(config.RAW_DIR.glob(pattern)):
        rows += records(read_raw(f))
    return rows


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace({"": None}), errors="coerce").astype("float64")


def _int(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace({"": None}), errors="coerce").astype("Int64")


def _date(s: pd.Series, fmt: str | None = None) -> pd.Series:
    return pd.to_datetime(s.replace({"": None}), errors="coerce", format=fmt).dt.date


def _flag(s: pd.Series) -> pd.Series:
    m = {"Y": True, "N": False, "true": True, "false": False, "True": True, "False": False, "1": True, "0": False}
    return s.map(lambda v: m.get(str(v).strip(), pd.NA) if v is not None else pd.NA).astype("boolean")


def _str(s: pd.Series) -> pd.Series:
    return s.where(s.notna(), None).map(lambda v: v.strip() if isinstance(v, str) else v).replace({"": None})


# --------------------------------------------------------------------------- dims


def build_indicators() -> pd.DataFrame:
    m = pd.DataFrame(_load("metadata/*.json.gz"))
    out = pd.DataFrame(
        {
            "snapshot_fy": _int(m["snapshot_fy"]),
            "ind_code": m["ind_code"],
            "ind_type": m["ind_type_name"],
            "ind_name": _str(m["ind_name"]),
            "display_name": _str(m["ind_display_name"]),
            "definition": _str(m["ind_definition"]),
            "long_definition": _str(m["ind_long_definition"]),
            "unit": _str(m["ind_unit_of_measure"]),
            "outcome_area_code": _str(m["ind_outcome_area_code"]),
            "outcome_area": _str(m["ind_outcome_area_name"]),
            "outcome_area_desc": _str(m["ind_outcome_area_desc"]),
            "vertical": _str(m["ind_vertical_name"]),
            "year_concept": _str(m["ind_yr_concpt_name"]),
            "source": _str(m["ind_source"]),
            "note": _str(m["ind_note"]),
            "status": _str(m["ind_status_code"]),
            "scale_type": _str(m["scale_type_code"]),
            "has_sub_indicators": _flag(m["sub_ind_flag"]),
            "sex_disaggregated": _flag(m["ind_sex_disaggregate_flag"]),
            "age_disaggregated": _flag(m["ind_age_disaggregate_flag"]),
            "disability_disaggregated": _flag(m["ind_disability_disaggregate_flag"]),
            "country_disaggregated": _flag(m["ind_cntry_disaggregate_flag"]),
            "reports_achieved": _flag(m["ind_achieved_rpt_flag"]),
            "reports_expected": _flag(m["ind_expected_rpt_flag"]),
            "reports_cumulative": _flag(m["ind_cumulative_rpt_flag"]),
            "fcs_only": _flag(m["ind_fcs_only_flag"]),
            "covers_wb": _flag(m["ind_wb_flag"]),
            "covers_ifc": _flag(m["ind_ifc_flag"]),
            "covers_miga": _flag(m["ind_miga_flag"]),
            "effective_date": _date(m["ind_eff_date"], "%m/%d/%Y"),
            "expiry_date": _date(m["ind_expratn_date"], "%m/%d/%Y"),
        }
    )
    return out.sort_values(["snapshot_fy", "ind_type", "ind_code"]).reset_index(drop=True)


def build_sub_indicators() -> pd.DataFrame:
    s = pd.DataFrame(_load("sub_metadata/*.json.gz"))
    return pd.DataFrame(
        {
            "snapshot_fy": _int(s["snapshot_fy"]),
            "ind_code": s["ind_code"],
            "sub_ind_code": s["sub_ind_code"],
            "sub_ind_name": _str(s["sub_ind_name"]),
            "display_name": _str(s["sub_ind_display_name"]),
            "is_female_series": _flag(s["female_sub_ind"]),
            "unit": _str(s["ind_unit_of_measure"]),
        }
    ).sort_values(["snapshot_fy", "ind_code", "sub_ind_code"]).reset_index(drop=True)


def build_countries() -> pd.DataFrame:
    c = pd.DataFrame(_load("countries/*.json.gz"))
    return pd.DataFrame(
        {
            "snapshot_fy": _int(c["snapshot_fy"]),
            "country_code": c["cntry_code"],
            "iso3": _str(c["cntry_iso3_code"]),
            "country_name": _str(c["cntry_short_name"]),
            "region_code": _str(c["rgn_wb_code"]),
            "region_name": _str(c["rgn_wb_name"]),
            "income_code": _str(c["cntry_inc_class_code"]),
            "income_name": _str(c["cntry_inc_class_name"]),
            "lending_eligibility": _str(c["cntry_elig_class_code"]),
            "is_fcs": _flag(c["cntry_fcv_ind"]),
            "is_ldc": _flag(c["least_dev_cntry_flag"]),
            "is_sids": _flag(c["cntry_sids_class_flag"]),
            "is_small_state": _flag(c["cntry_small_state_class_flag"]),
            "ref_type": _str(c["ref_type_code"]),
        }
    ).sort_values(["snapshot_fy", "country_code"]).reset_index(drop=True)


def build_outcome_areas() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    outcomes, inds, narr = [], [], []
    for f in sorted(config.RAW_DIR.glob("cms/outcomes/*.json.gz")):
        payload = read_raw(f)
        outcomes += payload.get("outcomes") or []
        inds += payload.get("indicators") or []
    for f in sorted(config.RAW_DIR.glob("cms/narratives/*.json.gz")):
        narr += read_raw(f) or []
    o = pd.DataFrame(outcomes)
    outcome_areas = pd.DataFrame(
        {
            "snapshot_fy": _int(o["fy"]),
            "outcome_id": _int(o["outcome_id"]),
            "outcome_area": _str(o["outcome_name"]),
            "description": _str(o["outcome_desc"]),
            "client_context_description": _str(o["client_context_description"]),
            "results_description": _str(o["results_description"]),
        }
    )
    i = pd.DataFrame(inds)
    cms_indicators = pd.DataFrame(
        {
            "snapshot_fy": _int(i["fy"]) if "fy" in i else pd.NA,
            "ind_code": i["ind_code"],
            "sub_ind_code": _str(i["sub_ind_code"]),
            "outcome_area": _str(i["ind_type_name"]),
            "display_name": _str(i["ind_display_name"]),
            "display_desc": _str(i["ind_display_desc"]).str.replace(r"<br\s*/?>", "\n", regex=True),
            "sub_display_name": _str(i["sub_ind_display_name"]),
            "vision_headline": _str(i.get("vision_ind_headline", pd.Series(index=i.index, dtype=object))),
            "display_order": _int(i["ind_display_order"]),
        }
    )
    n = pd.DataFrame(narr)
    narratives = pd.DataFrame(
        {
            "snapshot_fy": _int(n["fy"]),
            "narrative_id": _int(n["narrative_id"]),
            "title": _str(n["narrative_title"]),
            "summary": _str(n["narrative_desc"]),
            "related_outcome_areas": n["related_outcomes"].map(
                lambda xs: "; ".join(x["outcome_name"] for x in xs) if isinstance(xs, list) else None
            ),
            "image_url": _str(n["banner_url"]),
        }
    )
    return outcome_areas, cms_indicators, narratives


# -------------------------------------------------------------------------- facts


def _mark_headline(df: pd.DataFrame) -> pd.Series:
    """True for the series that represents each indicator's total, per snapshot."""
    has_null = df.groupby(["snapshot_fy", "ind_code"])["sub_ind_code"].transform(lambda s: s.isna().any())
    fallback = df["ind_code"].map(HEADLINE_FALLBACK)
    return (df["sub_ind_code"].isna() & has_null) | (~has_null & (df["sub_ind_code"] == fallback))


def _dedupe_results(out: pd.DataFrame) -> pd.DataFrame:
    """Collapse WBG Results rows that differ only by as-of date (see module docstring)."""
    key = ["snapshot_fy", "ind_code", "series_code", "org_code", "area_type", "area_code", "sex", "age",
           "disability", "joint_programming", "country_eligibility"]
    res = out["ind_type"] == "WBG Results"
    r = out[res].copy()
    r["_size"] = r["achieved"].abs().fillna(0) + r["expected"].abs().fillna(0)
    r = r.sort_values(key + ["_size", "as_of_date"], na_position="first")
    dup = r.duplicated(key, keep=False)
    r.loc[dup, "dedup_note"] = "FY24 duplicate as-of dates collapsed; kept the larger (complete) row"
    kept = r.drop_duplicates(key, keep="last").drop(columns="_size")
    if len(kept) < len(r):
        log.info("collapsed %d WBG Results rows that duplicated a key across as-of dates", len(r) - len(kept))
    return pd.concat([kept, out[~res]], ignore_index=True)


def build_indicator_values(countries: pd.DataFrame | None = None) -> pd.DataFrame:
    d = pd.DataFrame(_load("indicator_data/*/*.json.gz"))
    area_type_raw = d["ref_area_type_code"]
    area_type = area_type_raw.replace(AREA_TYPE_ALIASES)
    area_code_raw = d["ref_area_code"]
    area_code = pd.Series(
        [AREA_CODE_ALIASES.get((t, c), c) for t, c in zip(area_type, area_code_raw)], index=d.index
    )
    joint = _str(d["wbg_joint_progming_flag"]).fillna(TOTAL)
    out = pd.DataFrame(
        {
            "snapshot_fy": _int(d["snapshot_fy"]),
            "snapshot_date": _date(d["snapshot_date"]),
            "period": _str(d["ind_time_per"]),
            "as_of_date": _date(d["ind_time_per"], "%Y-%m-%d"),
            "ind_code": d["ind_code"],
            "ind_type": d["ind_type_name"],
            "sub_ind_code": _str(d["sub_ind_code"]),
            "org_code": d["org_code"],
            "area_type": area_type,
            "area_code": area_code,
            "area_name": _str(d["ref_area_name"]),
            "area_type_raw": area_type_raw,
            "area_code_raw": area_code_raw,
            "sex": _str(d["sex_disaggregate_code"]).fillna(TOTAL),
            "age": _str(d["age_disaggregate_code"]).fillna(TOTAL),
            "disability": _str(d["disability_disaggregate_code"]).fillna(TOTAL),
            "joint_programming": joint,
            "country_eligibility": _str(d["cntry_eligibility_code"]),
            "unit": _str(d["unit_of_measure_code"]).replace(UNIT_ALIASES),
            "achieved": _num(d["ind_base_achieved_val"]),
            "expected": _num(d["ind_base_expected_val"]),
            "cumulative_achieved": _num(d["cumulative_ind_base_achieved_val"]),
            "achieved_display": _num(d["ind_achieved_val"]),
            "achieved_display_unit": _str(d["achieved_uom_display_code"]),
            "expected_display": _num(d["ind_expected_val"]),
            "expected_display_unit": _str(d["expected_uom_display_code"]),
            "decimal_places": _int(d["decimal_rounding_nbr"]),
            "status_note": _str(d["ind_val_status_note"]),
            "footnote": _str(d["ind_val_foot_note"]),
            "low_threshold": _str(d["low_threshold_flag"]),
        }
    )
    ghg = out["ind_code"].isin(GHG_INDICATORS)
    for col in ("achieved", "expected", "cumulative_achieved"):
        out.loc[ghg, col] = out.loc[ghg, col] * GHG_SCALE
    out["series_code"] = out["sub_ind_code"].fillna(out["ind_code"])
    out["is_headline"] = _mark_headline(out)
    out["is_total_disaggregation"] = (
        (out["sex"] == TOTAL) & (out["age"] == TOTAL) & (out["disability"] == TOTAL) & (out["joint_programming"] == TOTAL)
    )
    # The calendar year a Client Context / Vision observation refers to (end year for ranges).
    out["obs_year"] = out["period"].str.extract(r"(\d{4})(?!.*\d{4})")[0].astype("Int64")
    if countries is not None:
        names = countries.drop_duplicates(["snapshot_fy", "country_code"]).set_index(["snapshot_fy", "country_code"])["country_name"]
        is_c = out["area_type"] == "COUNTRY"
        idx = pd.MultiIndex.from_arrays([out.loc[is_c, "snapshot_fy"], out.loc[is_c, "area_code"]])
        out.loc[is_c, "area_name"] = pd.Series(names.reindex(idx).to_numpy(), index=out.index[is_c]).fillna(out.loc[is_c, "area_name"])
    out["dedup_note"] = None
    before = len(out)
    out = out.drop_duplicates()
    if len(out) != before:
        log.warning("dropped %d exact duplicate indicator rows", before - len(out))
    return _dedupe_results(out).reset_index(drop=True)


def build_projects() -> pd.DataFrame:
    p = pd.DataFrame(_load("projects/*/*.json.gz"))
    out = pd.DataFrame(
        {
            "snapshot_fy": _int(p["snapshot_fy"]),
            "ind_code": p["ind_code"],
            "sub_ind_code": _str(p["sub_ind_code"]),
            "proj_id": p["proj_id"],
            "parent_proj_id": _str(p["parent_project_id"]),
            "org_code": p["org_code"],
            "country_code": _str(p["cntry_code"]),
            "region_code": _str(p["region_code"]),
            "project_name": _str(p["project_name"]),
            "project_description": _str(p["project_description"]),
            "approval_fy": _int(p["approval_fy"]),
            "closing_fy": _int(p["closing_fy"]),
            "approval_date": _date(p["approval_date"]),
            "closing_date": _date(p["closing_date"]),
            "status": _str(p["project_status_code"]),
            "global_practice": _str(p["global_practice_code"]),
            "product_line": _str(p["product_line_code"]),
            "financier": _str(p["project_financier_code"]),
            "lending_instrument": _str(p["lending_instrument_type_code"]),
            "sex": _str(p["sex_disaggregate_code"]).fillna(TOTAL),
            "age": _str(p["age_disaggregate_code"]).fillna(TOTAL),
            # In project rows "Yes" marks a disability-inclusive operation (an
            # attribute), not a population split as it is in the aggregates.
            "disability_inclusive": _str(p["disability_disaggregate_code"]) == "Yes",
            "as_of_date": _date(p["ind_time_per"]),
            "commitment_usd": _num(p["sum_tot_net_cmt_amt"]),
            "ibrd_commitment_usd": _num(p["sum_ibrd_net_cmt_amt"]),
            "ida_commitment_usd": _num(p["sum_ida_net_cmt_amt"]),
            "other_commitment_usd": _num(p["sum_other_net_cmt_amt"]),
            "baseline": _num(p["sum_final_ind_baseline_val"]),
            "progress": _num(p["sum_final_ind_progress_val"]),
            "target": _num(p["sum_final_ind_target_val"]),
            "baseline_date": _date(p["max_ind_baseline_date"]),
            "progress_date": _date(p["max_ind_progress_date"]),
            "target_date": _date(p["max_ind_target_date"]),
            "achieved": _num(p["sum_ind_base_achieved_val"]),
            "expected": _num(p["sum_ind_base_expected_val"]),
            "cumulative_achieved": _num(p["sum_cumulative_ind_base_achieved_val"]),
            "ida_share": _num(p["max_ida_contribution_percent"]),
            "ibrd_share": _num(p["max_ibrd_contribution_percent"]),
            "double_counting_flag": _flag(p["max_double_counting_flag"]),
            "isr_date": _date(p["max_isr_archive_date"]),
            "project_url": _str(p["project_external_url"]),
            "footnote": _str(p["max_ind_val_foot_note"]),
        }
    )
    ghg = out["ind_code"].isin(GHG_INDICATORS)
    for col in ("achieved", "expected", "cumulative_achieved"):
        out.loc[ghg, col] = out.loc[ghg, col] * GHG_SCALE
    out["progress_ratio"] = np.where(
        (out["target"] - out["baseline"]).abs() > 0,
        (out["progress"] - out["baseline"]) / (out["target"] - out["baseline"]),
        np.nan,
    )
    return out.drop_duplicates().reset_index(drop=True)


def build_all() -> dict[str, pd.DataFrame]:
    outcome_areas, cms_indicators, narratives = build_outcome_areas()
    countries = build_countries()
    return {
        "indicators": build_indicators(),
        "sub_indicators": build_sub_indicators(),
        "countries": countries,
        "outcome_areas": outcome_areas,
        "cms_indicators": cms_indicators,
        "narratives": narratives,
        "indicator_values": build_indicator_values(countries),
        "projects": build_projects(),
    }


def write_parquet(tables: dict[str, pd.DataFrame], out_dir: Path = config.CLEAN_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(out_dir / f"{name}.parquet", index=False)
        log.info("wrote %-18s %8d rows", name, len(df))
