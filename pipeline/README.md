# Scorecard data pipeline

Pulls the WBG Corporate Scorecard data straight from the API behind
scorecard.worldbank.org, cleans it and loads it into DuckDB
(`data/scorecard.duckdb`). The app's MCP tools and dashboard both read from
that database.

```bash
python -m pipeline              # fetch (uses cached raw files) -> clean -> DuckDB -> quality checks
python -m pipeline --refresh    # re-download everything (~1 min)
python -m pipeline --offline    # rebuild from the committed raw extracts, no network needed
pytest -q tests                 # 15 tests: parser, cleaning rules, invariants of the built DB
```

## Stages

| Stage | Module | Output |
|---|---|---|
| 1. Fetch | `fetch.py`, `client.py` | `data/raw/**.json.gz`: unmodified API payloads, plus `fetch_manifest.json` (URL, rows, time per call) |
| 2. Clean | `transform.py` | `data/clean/*.parquet`: typed tables |
| 3. Load | `db.py` | `data/scorecard.duckdb`: tables plus analysis views |
| 4. Validate | `checks.py` | `data/clean/data_quality_report.md` / `.json`. The command exits non-zero on any FAIL. |

## Source endpoints

All calls send an `apikey` header. The keys are the public, browser-side keys
the Scorecard site ships in its JavaScript bundle (`main.*.js` →
`environment.apiKey`). They can be overridden with environment variables (see
`config.py`).

| Data | Endpoint (base `https://ext.api.worldbank.org/api/Scorecard/`) |
|---|---|
| Indicator metadata (52 indicators: 22 WBG Results, 22 Client Context, 8 Vision) | `v1/metadata?snapshotfy=FY` |
| Sub-indicator metadata | `getSCSubIndicatorMetaData?snapshotfy=FY` |
| Indicator values by institution × area × disaggregation | `v1/data/{ind_code}?snapshotfy=FY` |
| Project-level results (World Bank operations) | `v1/resultsdata/{ind_code}?snapshotfy=FY` |
| Country attributes (region, income, FCS, LDC, SIDS, lending eligibility) | `getSCCountryDATA?snapshotfy=FY` |
| Outcome-area text and narratives (CMS, base `https://scorecardcmsapi.worldbank.org/scorecard/cache/`) | `get_outcomes_indicators?fy=FY`, `get_home_narratives?fy=FY` |

Snapshots FY2024–FY2026 have data; FY2023 returns nothing. Responses are
Databricks SQL-statement JSON with every value as a string.
`client.records()` parses them and refuses incomplete payloads. Large results
come in chunks that the gateway merges, which is verified against
`total_row_count`. The project geo-location endpoint (`getSCGEOLOC`) returns
only 19,800 of 84,659 rows, so it is skipped unless `--geo` is passed (and
fails the guard even then). `downloaddata` and `getSCSUMMARYDATAXLSX` return
HTTP 500.

## Tables and views

| Name | Grain / purpose |
|---|---|
| `indicator_values` | All values: snapshot × indicator × series × institution × area × sex/age/disability × period |
| `indicators`, `sub_indicators`, `indicator_catalog` (view, latest snapshot) | Metadata: names, definitions, units, outcome area, flags |
| `countries` | Country attributes per snapshot |
| `projects` | Project contributions per snapshot × indicator (IBRD/IDA operations) |
| `outcome_areas`, `cms_indicators`, `narratives` | Scorecard text content |
| **`results`** (view) | WBG Results headline series at total disaggregation: one row per snapshot × indicator × institution × area, with `achieved`, `expected`, `achieved_to_expected` |
| `results_detail` (view) | Every series plus sex/age/disability splits |
| `country_results` (view) | `results` for countries, joined to country attributes; `is_economy` flags real economies |
| `context` (view) | Client Context and Vision values by calendar year |
| `project_results` (view) | Projects at total sex/age, with country and indicator names |

## Data rules found while building (the agent must respect these)

Evidence for each rule is in `data_quality_report.md`.

1. **Use base values.** `achieved` and `expected` are unrounded, in the indicator's own unit. The API's display values are rounded and scaled (K/M/B).
2. **Never sum across `org_code`.**
   - WBG = WB + IFC + MIGA (verified to within 0.5%).
   - WB ≤ IBRD + IDA, because projects with both kinds of financing are counted once.
   - IDA-21 is a subset of IDA.
   - Use `org_code = 'WBG'` for whole-group figures.
3. **Global totals come from `area_code = 'ACW'`** ("All Countries"), never from summing countries. Regions sum to ACW; countries do not, because multi-country operations exist.
4. **The snapshot fiscal year is the time key** for results. The as-of dates within a snapshot differ by institution.
5. **Achieved vs expected.** Achieved = results delivered to date. Expected = what the active portfolio expects to deliver. GHG and private-capital-mobilized indicators report expected only.
6. **Area labels are harmonised across snapshots** (FCV→FCS, SSS→SST). MNA (FY24) and MENAAP (FY25+) differ in coverage, so they are not merged.
7. **Units differ across indicators.**
   - Most count beneficiaries. Others are USD, GW, hectares, MtCO2eq/year, number of economies, or percentages.
   - Never rank indicators with different units against each other.
   - Percentages and economy counts are not additive across areas.
8. **GHG values** are rescaled from tCO2eq (as published) to MtCO2eq/year (the label).
9. **Project drill-downs** cover only World Bank (IBRD/IDA) operations. They reconcile with WB totals for 45 of 50 indicator-snapshots; the exceptions are listed in the report.
