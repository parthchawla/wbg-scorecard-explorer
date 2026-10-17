# Data quality report

Built 2026-10-17T15:22:16+00:00 from `https://ext.api.worldbank.org/api/Scorecard/`; snapshots [2024, 2025, 2026].

| Check | Status |
|---|---|
| Indicator coverage | **WARN** |
| Indicator grain is unique | **PASS** |
| `results` view has one row per snapshot x indicator x org x area | **PASS** |
| Every indicator has a headline series | **WARN** |
| Base values agree with display values | **PASS** |
| Institution hierarchy (never sum across org_code) | **PASS** |
| Regional rows add up to the global total | **PASS** |
| Result country codes match the country dimension | **WARN** |
| Negative values | **WARN** |
| Project-level data reconciles to WB totals | **WARN** |

## Tables

| table_name       |   rows |
|:-----------------|-------:|
| build_info       |      1 |
| cms_indicators   |    225 |
| countries        |    747 |
| indicator_values | 368344 |
| indicators       |    156 |
| narratives       |     42 |
| outcome_areas    |     45 |
| projects         |  43405 |
| sub_indicators   |     64 |

## Indicator coverage: WARN

152 of 156 (snapshot, indicator) pairs in the metadata have data; 4 are listed in the metadata but return no rows from the API.

|   snapshot_fy | ind_code                 | ind_type    |
|--------------:|:-------------------------|:------------|
|          2024 | CSC_RES_NEW_JOBS_WOM_YOU | WBG Results |
|          2024 | CSC_RES_PRIV_CAP_ENAB    | WBG Results |
|          2025 | CSC_RES_NEW_JOBS_WOM_YOU | WBG Results |
|          2026 | CSC_RES_NEW_JOBS_WOM_YOU | WBG Results |

## Indicator grain is unique: PASS

indicator_values is unique on snapshot x indicator x series x org x area x disaggregations x period.

## `results` view has one row per snapshot x indicator x org x area: PASS

Safe to aggregate or join without double counting.

## Every indicator has a headline series: WARN

All WBG Results indicators resolve to exactly one headline series per snapshot. 6 Client Context/Vision indicators publish only component series (e.g. water, sanitation and hygiene separately); use their sub-indicators.

|   snapshot_fy | ind_code              | ind_type       |
|--------------:|:----------------------|:---------------|
|          2024 | SH_H2O_STA_HYGN_ZS_TO | Client Context |
|          2025 | SH_H2O_STA_HYGN_ZS_TO | Client Context |
|          2026 | SH_H2O_STA_HYGN_ZS_TO | Client Context |
|          2024 | SH_H2O_STA_HYGN_TO    | Vision         |
|          2025 | SH_H2O_STA_HYGN_TO    | Vision         |
|          2026 | SH_H2O_STA_HYGN_TO    | Vision         |

## Base values agree with display values: PASS

100.00% of rows: base value = display value x unit multiplier (K/M/B; MW display of GW base; GHG rescaled from tCO2eq to MtCO2eq), within rounding. The pipeline uses base values throughout.

| display_unit   |      n |   consistent |
|:---------------|-------:|-------------:|
| %              | 221921 |       221921 |
| nan            |  63393 |        63393 |
| K              |  35544 |        35544 |
| M              |  18993 |        18993 |
| MtCO2eq/year   |  15026 |        15026 |
| GW             |   1182 |         1182 |
| KtCO2eq/year   |    862 |          862 |
| MW             |    109 |          109 |
| B              |      6 |            6 |

## Institution hierarchy (never sum across org_code): PASS

WBG = WB + IFC + MIGA holds within 0.5% for 45 of 45 indicator-snapshots (global, achieved; economy counts are excluded because one economy can be supported by several institutions). IBRD + IDA exceeds WB in 12 cases (projects with both IBRD and IDA financing are counted once in WB), so IBRD and IDA must never be summed.

|   snapshot_fy | ind_code                      |          WBG |           WB |          IFC |             MIGA |         IBRD |         IDA |   wbg_vs_parts |   wb_vs_ibrd_ida |
|--------------:|:------------------------------|-------------:|-------------:|-------------:|-----------------:|-------------:|------------:|---------------:|-----------------:|
|          2026 | CSC_RES_ACCS_TRANS_INFRA_SERV |  2.22422e+08 |  1.5092e+08  |  6.81798e+07 |      3.32284e+06 |  3.99264e+07 | 1.17613e+08 |              1 |           1.0439 |
|          2026 | CSC_RES_BRO_INTE              |  2.43936e+08 |  4.5054e+07  |  1.93484e+08 |      5.39796e+06 |  3.47233e+06 | 5.22165e+07 |              1 |           1.236  |
|          2026 | CSC_RES_DIG_ENA_SERV          |  3.71381e+08 |  1.88977e+08 |  1.52069e+08 |      3.03343e+07 |  5.57674e+07 | 1.59757e+08 |              1 |           1.1405 |
|          2026 | CSC_RES_ELC_ACCS              |  2.58394e+08 |  1.47884e+08 |  8.60534e+07 |      2.4456e+07  |  6.66466e+07 | 1.01735e+08 |              1 |           1.1386 |
|          2024 | CSC_RES_FIN_SERV_WOM          |  7.34428e+07 |  6.80772e+06 |  6.65663e+07 |  68800           |  2.27271e+06 | 4.56908e+06 |              1 |           1.005  |
|          2026 | CSC_RES_FIN_SERV_WOM          |  1.90143e+08 |  3.40307e+07 |  1.25537e+08 |      3.05758e+07 |  1.13543e+07 | 5.14416e+07 |              1 |           1.8453 |
|          2026 | CSC_RES_FOOD_NUTR_SECU        |  2.30859e+08 |  1.75908e+08 |  4.41184e+07 |      1.0832e+07  |  2.66305e+07 | 1.60582e+08 |              1 |           1.0643 |
|          2026 | CSC_RES_GEN_EQU_BENE          |  3.24325e+08 |  3.09689e+08 |  1.38205e+07 | 815931           |  1.50595e+08 | 1.67923e+08 |              1 |           1.0285 |
|          2026 | CSC_RES_REN_ENER_ENAB         | 47.3328      | 24.4316      | 19.55        |      3.3512      | 20.7968      | 5.6965      |              1 |           1.0844 |
|          2026 | CSC_RES_RESI_CLIM_RISK        |  1.61721e+08 |  1.14862e+08 |  4.68594e+07 |      0           |  2.80253e+07 | 9.4733e+07  |              1 |           1.0687 |
|          2026 | CSC_RES_SOC_SAF_PROG          |  2.82099e+08 |  2.82099e+08 |  0           |      0           |  1.28588e+08 | 1.67062e+08 |              1 |           1.048  |
|          2026 | CSC_RES_WAT_SAN_HYG_TOT       |  7.52419e+07 |  6.86175e+07 |  6.18432e+06 | 440000           |  2.30173e+07 | 4.63051e+07 |              1 |           1.0103 |

## Regional rows add up to the global total: PASS

Regions (incl. 'Other') sum to the global total (ACW) within 2% in 50 of 51 cases. Country rows cover a median 99.7% of the global total; the rest is from multi-country/regional operations. Use ACW for global totals, never the sum of countries.

|   snapshot_fy | ind_code             |   global_total |   sum_regions |   sum_countries |   regions_vs_global |   countries_vs_global |
|--------------:|:---------------------|---------------:|--------------:|----------------:|--------------------:|----------------------:|
|          2024 | CSC_RES_DIG_ENA_SERV |    1.74302e+08 |   1.68039e+08 |     1.62088e+08 |              0.9641 |                0.9299 |

## Result country codes match the country dimension: WARN

59 snapshot-specific codes filed under COUNTRY are multi-country groupings (e.g. 1W World, 3A Africa) or legacy codes; `country_results.is_economy` flags them so country rankings can exclude them.

|   snapshot_fy | area_code   | area_name                   |
|--------------:|:------------|:----------------------------|
|          2024 | 1E          | Europe                      |
|          2024 | 1W          | World                       |
|          2024 | 3A          | Africa                      |
|          2024 | 3F          | Eastern Africa Region       |
|          2024 | 3S          | Southern Africa             |
|          2024 | 3T          | Central Africa              |
|          2024 | 3W          | Western and Central Africa  |
|          2024 | 4E          | East Asia and Pacific       |
|          2024 | 6C          | Central America             |
|          2024 | 6L          | Latin America and Caribbean |
|          2024 | 7C          | Central Asia                |
|          2024 | 8S          | South Asia                  |
|          2024 | EM          | Middle East Region          |
|          2024 | EU          | Europe Region               |
|          2024 | RN          | Northern Africa Region      |
|          2024 | YF          | Serbia                      |
|          2025 | 1E          | Europe                      |
|          2025 | 1W          | World                       |
|          2025 | 3A          | Africa                      |
|          2025 | 3E          | Eastern and Southern Africa |
|          2025 | 3F          | Eastern Africa Region       |
|          2025 | 3S          | Southern Africa             |
|          2025 | 3T          | Central Africa              |
|          2025 | 3W          | Western and Central Africa  |
|          2025 | 4A          | Asia                        |

## Negative values: WARN

Negative values for GHG indicators are expected (net reductions / net removals). 2 other negative value(s) look like source errors and are left as published: CSC_RES_GEN_EQU_BENE

| ind_code             | unit          |   n_negative |
|:---------------------|:--------------|-------------:|
| EN_ATM_GHGT_GT_CE    | MtCO2eq/year  |         2264 |
| CSC_RES_GHG_EMS_YEAR | MtCO2eq/year  |         1739 |
| CSC_RES_GEN_EQU_BENE | Beneficiaries |            2 |

## Project-level data reconciles to WB totals: WARN

3158 distinct World Bank (IBRD/IDA) projects; IFC and MIGA report only aggregates. Summed project expected values match the WB global total within 2% for 45 of 50 indicator-snapshots. The rest are listed below: project drill-downs for these are not exhaustive.

|   snapshot_fy | ind_code               |   proj_expected |   n_projects |   wb_expected |   coverage |
|--------------:|:-----------------------|----------------:|-------------:|--------------:|-----------:|
|          2024 | CSC_RES_DEBT_SUST_RISK |    35           |          112 |  59.322       |      0.59  |
|          2025 | CSC_RES_ELC_ACCS       |     1.54488e+08 |           90 |   2.80172e+08 |      0.551 |
|          2026 | CSC_RES_ELC_ACCS       |     2.04062e+08 |          100 |   3.21263e+08 |      0.635 |
|          2025 | CSC_RES_HEA_EMER_BENE  |     0           |           25 |  57           |      0     |
|          2026 | CSC_RES_HEA_EMER_BENE  |     0           |           62 |  71           |      0     |
