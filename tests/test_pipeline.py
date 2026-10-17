"""Tests for the ingestion pipeline.

Unit tests use synthetic payloads; the integration tests run against the
built DuckDB file and are skipped if it has not been built yet
(`python -m pipeline --offline`).
"""

from __future__ import annotations

import pandas as pd
import pytest

from pipeline import config, transform
from pipeline.client import ScorecardAPIError, records


def statement(cols, rows, **manifest):
    return {
        "status": {"state": "SUCCEEDED"},
        "manifest": {"schema": {"columns": [{"name": c} for c in cols]}, "total_row_count": len(rows), **manifest},
        "result": {"data_array": rows},
    }


# ---------------------------------------------------------------- client.records


def test_records_parses_statement_payload():
    out = records(statement(["a", "b"], [["1", "x"], ["2", None]]))
    assert out == [{"a": "1", "b": "x"}, {"a": "2", "b": None}]


def test_records_accepts_gateway_merged_chunks():
    p = statement(["a"], [["1"], ["2"], ["3"]], total_chunk_count=2)
    p["result"]["next_chunk_internal_link"] = "/api/2.0/sql/statements/x/result/chunks/1"
    assert len(records(p)) == 3


def test_records_rejects_incomplete_payload():
    p = statement(["a"], [["1"]])
    p["manifest"]["total_row_count"] = 5
    with pytest.raises(ScorecardAPIError, match="incomplete"):
        records(p)


def test_records_rejects_failed_statement():
    p = statement(["a"], [])
    p["status"]["state"] = "FAILED"
    with pytest.raises(ScorecardAPIError):
        records(p)


def test_records_passes_plain_lists_through():
    assert records([{"a": 1}]) == [{"a": 1}]


# ------------------------------------------------------------- transform rules


def _vals(rows):
    df = pd.DataFrame(rows, columns=["snapshot_fy", "ind_code", "sub_ind_code"])
    return transform._mark_headline(df).tolist()


def test_headline_prefers_null_sub_indicator():
    assert _vals([(2025, "X", None), (2025, "X", "X_SUB")]) == [True, False]


def test_headline_falls_back_to_named_total_series():
    rows = [(2024, "CSC_RES_FIN_SERV_WOM", "CSC_RES_FIN_SERV"), (2024, "CSC_RES_FIN_SERV_WOM", "CSC_RES_FIN_SERV_WOM_CUS")]
    assert _vals(rows) == [True, False]


def test_headline_fallback_is_per_snapshot():
    rows = [(2024, "CSC_RES_FIN_SERV_WOM", "CSC_RES_FIN_SERV"), (2026, "CSC_RES_FIN_SERV_WOM", None),
            (2026, "CSC_RES_FIN_SERV_WOM", "CSC_RES_FIN_SERV")]
    assert _vals(rows) == [True, True, False]


def test_dedupe_keeps_complete_row():
    base = dict(snapshot_fy=2024, ind_code="I", series_code="I", org_code="WBG", area_type="COUNTRY", area_code="TR",
                sex="_T", age="_T", disability="_T", joint_programming="_T", country_eligibility="IBRD",
                ind_type="WBG Results", dedup_note=None)
    df = pd.DataFrame([
        {**base, "as_of_date": "2024-06-30", "achieved": 0.0, "expected": 0.0},
        {**base, "as_of_date": "2023-12-31", "achieved": 591579.0, "expected": 854700.0},
        {**base, "ind_type": "Client Context", "as_of_date": "2020-12-31", "achieved": 1.0, "expected": None},
        {**base, "ind_type": "Client Context", "as_of_date": "2021-12-31", "achieved": 2.0, "expected": None},
    ])
    out = transform._dedupe_results(df)
    res = out[out.ind_type == "WBG Results"]
    assert len(res) == 1 and res.achieved.iloc[0] == 591579.0
    assert len(out[out.ind_type == "Client Context"]) == 2  # context time series untouched


# ------------------------------------------------------------ built database

needs_db = pytest.mark.skipif(not config.DB_PATH.exists(), reason="run `python -m pipeline --offline` first")


@pytest.fixture(scope="module")
def con():
    from pipeline.db import connect
    c = connect()
    yield c
    c.close()


@needs_db
def test_views_exist(con):
    names = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()}
    assert {"results", "results_detail", "country_results", "context", "project_results", "indicator_catalog"} <= names


@needs_db
def test_results_view_is_unique(con):
    dup = con.execute("""SELECT count(*) FROM (SELECT snapshot_fy, ind_code, org_code, area_type, area_code
                         FROM results GROUP BY ALL HAVING count(*) > 1)""").fetchone()[0]
    assert dup == 0


@needs_db
def test_every_results_indicator_with_data_has_a_global_headline(con):
    missing = con.execute("""
        SELECT DISTINCT v.snapshot_fy, v.ind_code FROM indicator_values v
        WHERE v.ind_type = 'WBG Results'
        AND NOT EXISTS (SELECT 1 FROM results r WHERE r.snapshot_fy = v.snapshot_fy AND r.ind_code = v.ind_code
                        AND r.org_code = 'WBG' AND r.area_code = 'ACW')""").fetchall()
    assert missing == []


@needs_db
def test_wbg_equals_sum_of_institutions(con):
    rows = con.execute("""
        SELECT ind_code, snapshot_fy,
               sum(achieved) FILTER (WHERE org_code = 'WBG') wbg,
               coalesce(sum(achieved) FILTER (WHERE org_code IN ('WB', 'IFC', 'MIGA')), 0) parts
        FROM results WHERE area_code = 'ACW' AND unit = 'Beneficiaries' GROUP BY ALL HAVING wbg > 0""").fetchall()
    assert rows and all(abs(parts / wbg - 1) < 0.005 for _, _, wbg, parts in rows)


@needs_db
def test_ghg_values_are_in_megatonnes(con):
    v = con.execute("""SELECT expected FROM results WHERE ind_code = 'CSC_RES_GHG_EMS_YEAR'
                       AND org_code = 'WBG' AND area_code = 'ACW' AND snapshot_fy = 2025""").fetchone()[0]
    assert -1_000 < v < 0  # net reduction of a few hundred Mt, not ~1e8 tonnes


@needs_db
def test_base_values_not_display_values(con):
    # Display values are rounded and scaled (e.g. 214.5 "M"); base values are raw people counts.
    v = con.execute("""SELECT achieved FROM results WHERE ind_code = 'CSC_RES_ELC_ACCS'
                       AND org_code = 'WBG' AND area_code = 'ACW' AND snapshot_fy = 2025""").fetchone()[0]
    assert v > 1e8
