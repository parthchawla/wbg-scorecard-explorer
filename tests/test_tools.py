"""Tests for the Scorecard query layer and MCP server.

Tool outputs are checked against independent SQL on the raw `indicator_values`
grain, so a bug in a tool's filters (wrong series, disaggregation, institution)
shows up as a mismatch.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from app.scorecard import queries as q
from pipeline import config

pytestmark = pytest.mark.skipif(not config.DB_PATH.exists(), reason="run `python -m pipeline --offline` first")

RAW_TOTAL = """
    SELECT sum(achieved) a, sum(expected) e FROM indicator_values
    WHERE ind_code = ? AND snapshot_fy = ? AND org_code = ? AND area_code = ? AND is_headline
      AND sex = '_T' AND age = '_T' AND disability = '_T' AND joint_programming = '_T'"""


def raw(ind, fy, org, area):
    return q.rows(RAW_TOTAL, [ind, fy, org, area])[0]


@pytest.mark.parametrize("ind", ["CSC_RES_ELC_ACCS", "CSC_RES_HEA_SERV", "CSC_RES_BRO_INTE", "CSC_RES_FIN_SERV_WOM"])
def test_global_results_match_raw_sql(ind):
    out = q.get_results(ind, "global")
    truth = raw(ind, q.latest_snapshot(), "WBG", "ACW")
    assert out["rows"][0]["achieved"] == pytest.approx(truth["a"], rel=1e-6)
    assert out["rows"][0]["expected"] == pytest.approx(truth["e"], rel=1e-6)


def test_regions_add_up_to_global():
    out = q.get_results("CSC_RES_ELC_ACCS", "region", top_n=60)
    total = sum(r["achieved"] for r in out["rows"])
    assert total == pytest.approx(out["global_total"]["achieved"], rel=0.02)


def test_country_breakdown_excludes_multicountry_groupings():
    out = q.get_results("CSC_RES_HEA_SERV", "country", top_n=60)
    names = {r["area_name"] for r in out["rows"]}
    assert "World" not in names and "Africa" not in names
    assert all("region" in r for r in out["rows"])


def test_compare_snapshots_change_is_consistent():
    out = q.get_results("CSC_RES_BRO_INTE", "region", compare_snapshots=True, sort_by="change", top_n=60)
    for r in out["rows"]:
        if r.get("achieved_fy2024") is not None and r.get("achieved_fy2026") is not None:
            assert r["change_achieved_fy2024_to_fy2026"] == pytest.approx(r["achieved_fy2026"] - r["achieved_fy2024"], abs=1)
    changes = [r["change_achieved_fy2024_to_fy2026"] for r in out["rows"] if r["change_achieved_fy2024_to_fy2026"] is not None]
    assert changes == sorted(changes, reverse=True)


def test_women_series_is_a_subset():
    total = q.get_results("CSC_RES_EDU_SUPP", "global")["rows"][0]["achieved"]
    women = q.get_results("CSC_RES_EDU_SUPP", "global", series="women")["rows"][0]["achieved"]
    assert 0 < women < total


def test_institution_breakdown_does_not_sum():
    rows = {r["area_code"]: r for r in q.get_results("CSC_RES_ELC_ACCS", "institution")["rows"]}
    assert {"WBG", "WB", "IFC"} <= set(rows)
    assert rows["WBG"]["achieved"] == pytest.approx(
        rows["WB"]["achieved"] + rows["IFC"]["achieved"] + rows.get("MIGA", {"achieved": 0})["achieved"], rel=0.005)


def test_fcs_breakdown_resolves_harmonised_code():
    out = q.get_results("CSC_RES_RESI_CLIM_RISK", "fcs")
    assert any(r["area_code"] == "FCS" for r in out["rows"])


def test_country_profile_matches_results_view():
    prof = q.get_country_profile("KEN")
    assert prof["country"]["code"] == "KE"
    elc = next(r for r in prof["wbg_results"] if r["ind_code"] == "CSC_RES_ELC_ACCS")
    truth = raw("CSC_RES_ELC_ACCS", q.latest_snapshot(), "WBG", "KE")
    assert elc["achieved"] == pytest.approx(truth["a"], rel=1e-6)
    assert prof["client_context"], "Kenya should have Client Context values"


@pytest.mark.parametrize("ind,fy", [("CSC_RES_HEA_SERV", 2025), ("CSC_RES_SOC_SAF_PROG", 2026), ("CSC_RES_ELC_ACCS", 2024)])
def test_project_rows_reconcile_with_wb_total(ind, fy):
    projects = q._project_rows("snapshot_fy = ? AND ind_code = ?", [fy, ind], "expected", 100_000)
    wb = raw(ind, fy, "WB", "ACW")
    assert sum(p["expected"] or 0 for p in projects) == pytest.approx(wb["e"], rel=0.02)


def test_search_indicators_maps_plain_language():
    codes = [m["ind_code"] for m in q.search_indicators("digital access")["matches"]]
    assert {"CSC_RES_BRO_INTE", "CSC_RES_DIG_ENA_SERV"} <= set(codes[:4])
    codes = [m["ind_code"] for m in q.search_indicators("climate resilience", tier="WBG Results")["matches"]]
    assert codes[0] == "CSC_RES_RESI_CLIM_RISK"


@pytest.mark.parametrize("text,expected", [("Kenya", ("COUNTRY", "KE")), ("ind", ("COUNTRY", "IN")), ("South Asia", ("REGION", "SAR")),
                                           ("fragile states", ("FCS", "FCS")), ("world", ("REGION", "ACW")), ("Turkey", ("COUNTRY", "TR"))])
def test_resolve_area(text, expected):
    a = q.resolve_area(text)
    assert (a["area_type"], a["area_code"]) == expected


def test_context_trend_returns_series():
    out = q.get_context_trend("EG_ELC_ACCS_ZS", ["AFE", "global"], start_year=2020)
    assert len(out["series"]) == 2 and all(s["points"] for s in out["series"])
    assert out["indicator"]["better_when"] == "higher"


@pytest.mark.parametrize("sql", ["DROP TABLE results", "select 1; select 2", "select * from read_csv('/etc/passwd')",
                                 "SELECT * FROM results WHERE 1=1 UNION ALL SELECT * FROM results; ATTACH 'x.db'",
                                 "with x as (select 1) insert into results select * from x"])
def test_run_sql_blocks_unsafe_queries(sql):
    with pytest.raises(q.ScorecardQueryError):
        q.run_sql(sql)


def test_run_sql_caps_rows():
    out = q.run_sql("select * from indicator_values")
    assert out["row_count"] == q.SQL_MAX_ROWS and out["truncated"]


def test_errors_are_actionable():
    with pytest.raises(q.ScorecardQueryError, match="get_context_trend"):
        q.get_results("SE_LPV_PRIM")
    with pytest.raises(q.ScorecardQueryError, match="CSC_RES_ELC_ACCS"):
        q.indicator("CSC_RES_ELEC_ACCS")
    with pytest.raises(q.ScorecardQueryError, match="no published data"):
        q.get_results("CSC_RES_NEW_JOBS_WOM_YOU")


def test_guide_indicator_codes_match_database():
    from app.mcp_server import KNOWLEDGE
    text = (KNOWLEDGE / "scorecard_guide.md").read_text()
    cited = set(re.findall(r"\[([A-Z][A-Z0-9_]{5,})\]", text)) | set(re.findall(r"`([A-Z][A-Z0-9_]{5,})`", text))
    catalog = set(q.catalog())
    assert cited - catalog == set(), f"guide cites unknown codes: {cited - catalog}"
    results = {c for c, v in q.catalog().items() if v["tier"] == "WBG Results"}
    assert results - cited == set(), f"guide is missing results indicators: {results - cited}"


def test_mcp_server_lists_read_only_tools_and_reports_errors():
    from mcp import Client

    from app.mcp_server import mcp

    async def go():
        async with Client(mcp) as c:
            tools = (await c.list_tools()).tools
            bad = await c.call_tool("get_results", {"ind_code": "SE_LPV_PRIM"})
            good = await c.call_tool("search_indicators", {"query": "electricity"})
            guide = await c.read_resource("scorecard://guide")
            return tools, bad, good, guide

    tools, bad, good, guide = asyncio.run(go())
    assert len(tools) == 7 and all(t.annotations.read_only_hint for t in tools)
    assert bad.is_error and "get_context_trend" in bad.content[0].text
    assert not good.is_error and good.structured_content["matches"]
    assert guide.contents[0].text.startswith("# Part A")


def test_subgroup_series_reports_share_of_total():
    row = q.get_results("CSC_RES_EDU_SUPP", "global", series="women", compare_snapshots=True)["rows"][0]
    total = q.get_results("CSC_RES_EDU_SUPP", "global")["rows"][0]["achieved"]
    assert row["total_achieved"] == pytest.approx(total)
    assert row["share_of_total_achieved"] == pytest.approx(row["achieved"] / total, abs=1e-3)
    assert "share_of_total_achieved_fy2024" in row
