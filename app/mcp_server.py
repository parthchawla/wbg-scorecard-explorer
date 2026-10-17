"""MCP server for the WBG Corporate Scorecard.

Exposes the Scorecard database to any MCP client (the web app's agent,
Claude Desktop, Claude Code, ...) through three MCP primitives:

* Tools (model-controlled): seven read-only, workflow-shaped tools.
* Resources (application-controlled): the data guide, the assistant SOP,
  the database schema and the indicator catalogue.
* Prompts (user-controlled): ready-made analyses (country briefing,
  outcome-area stocktake, group comparison).

Run standalone:
    python -m app.mcp_server                       # stdio (Claude Desktop / Claude Code)
    python -m app.mcp_server --http --port 8001    # Streamable HTTP at /mcp
"""

from __future__ import annotations

import argparse
import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from app.scorecard import queries as q

KNOWLEDGE = Path(__file__).parent / "knowledge"


@lru_cache(maxsize=1)
def guide_parts() -> tuple[str, str]:
    """Split the guide into Part A (data guide) and Part B (assistant SOP)."""
    text = (KNOWLEDGE / "scorecard_guide.md").read_text()
    head, sep, part_b = text.partition("\n# Part B")
    part_a = head.split("\n# Part A", 1)[-1]
    return "# Part A" + part_a.rstrip("-\n "), "# Part B" + part_b


INSTRUCTIONS = """\
World Bank Group (WBG) Corporate Scorecard data: what WBG-financed projects achieved and expect to achieve (WBG Results),
alongside conditions in client countries (Client Context) and global goals (Vision). Snapshots FY2024-FY2026.

Read the `scorecard://guide` resource before your first answer. Key rules:
- Only state numbers returned by these tools; say what each number is (indicator, unit, achieved vs expected,
  institution, snapshot).
- Achieved = delivered so far; expected = what current projects expect to deliver over their life (usually larger).
- Never add across institutions (WBG = WB + IFC + MIGA; IBRD + IDA can exceed WB) or across indicators.
- Global totals are the 'All Countries' rows, not sums of countries. Client Context values are not WBG results.
Typical flow: search_indicators -> get_indicator_profile -> get_results / get_context_trend / get_country_profile /
search_projects. Use run_sql only when no other tool fits."""

mcp = MCPServer(
    name="wbg-scorecard",
    title="WBG Corporate Scorecard",
    description="Query World Bank Group Corporate Scorecard results, client-country context and project contributions.",
    instructions=INSTRUCTIONS,
    website_url="https://scorecard.worldbank.org",
)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

Breakdown = Literal["global", "region", "income", "fcs", "ldc", "sids", "small_state", "country", "institution"]
Institution = Literal["WBG", "WB", "IBRD", "IDA", "IDA-21", "IFC", "MIGA"]
Snapshot = Annotated[int | None, Field(description="Snapshot fiscal year (2024, 2025 or 2026). Omit for the latest (FY2026).")]


def _call(fn, *args, **kwargs) -> dict[str, Any]:
    """Run a query function, turning data/user errors into actionable MCP tool errors."""
    try:
        return fn(*args, **kwargs)
    except q.ScorecardQueryError as e:
        raise ToolError(str(e)) from None


# ----------------------------------------------------------------------------- tools


@mcp.tool(title="Search indicators", annotations=READ_ONLY)
def search_indicators(
    query: Annotated[str, Field(description="Plain-language topic or keywords, e.g. 'digital access', 'climate resilience', "
                                            "'girls education', or an indicator code. Empty string lists everything.")] = "",
    tier: Annotated[Literal["any", "WBG Results", "Client Context", "Vision"],
                    Field(description="Restrict to one Scorecard tier.")] = "any",
    outcome_area: Annotated[str | None, Field(description="Optional outcome-area name fragment, e.g. 'energy', 'health'.")] = None,
) -> dict[str, Any]:
    """Find Scorecard indicators that match a topic, and get their codes.

    Start here whenever the user describes a topic in their own words. Returns up to 15 indicators with code,
    full name, tier, outcome area, unit, whether achieved/expected values are reported, whether higher or lower values
    are better, and which snapshots have data. Tiers: 'WBG Results' = what WBG projects delivered (attributable to
    the WBG); 'Client Context' = conditions in client countries; 'Vision' = global goals.
    """
    return _call(q.search_indicators, query, tier, outcome_area)


@mcp.tool(title="Indicator profile", annotations=READ_ONLY)
def get_indicator_profile(
    ind_code: Annotated[str, Field(description="Indicator code from search_indicators, e.g. 'CSC_RES_ELC_ACCS'.")],
) -> dict[str, Any]:
    """Everything about one indicator: definition, unit, sub-indicators, headline numbers and caveats.

    For WBG Results indicators: global totals for every snapshot and institution (WBG, WB, IBRD, IDA, IDA-21, IFC, MIGA),
    the breakdowns available, and the related Client Context indicators. For Client Context/Vision indicators: the
    latest global values and the related WBG Results indicators. Use this to give a quick overview or to check the
    definition and caveats before answering.
    """
    return _call(q.get_indicator_profile, ind_code)


@mcp.tool(title="Results by place, group or institution", annotations=READ_ONLY)
def get_results(
    ind_code: Annotated[str, Field(description="A WBG Results indicator code (starts with 'CSC_RES_').")],
    breakdown: Annotated[Breakdown, Field(description=(
        "How to split the results: 'global' (All Countries total), 'region' (World Bank regions), 'income' (income groups), "
        "'fcs' (fragile and conflict-affected situations), 'ldc', 'sids', 'small_state', 'country' (economies only), "
        "or 'institution' (WBG vs WB, IBRD, IDA, IFC, MIGA at global level)."))] = "region",
    institution: Annotated[Institution, Field(description="Which institution's results (ignored when breakdown='institution'). "
                                                          "'WBG' = whole Group.")] = "WBG",
    snapshot_fy: Snapshot = None,
    compare_snapshots: Annotated[bool, Field(description="True adds achieved/expected for every snapshot (FY2024-FY2026) and the "
                                                         "change from first to last. Use for 'progress over time' questions.")] = False,
    series: Annotated[str | None, Field(description="Optional subset: 'women', 'youth', 'disability_inclusive' (rows then also "
                                                    "include the total and share_of_total_*), or a sub-indicator code from "
                                                    "get_indicator_profile. Omit for the total.")] = None,
    sort_by: Annotated[Literal["achieved", "expected", "achieved_to_expected", "change"],
                       Field(description="Sort rows (descending). 'change' needs compare_snapshots=true.")] = "achieved",
    top_n: Annotated[int, Field(ge=1, le=60, description="Maximum rows to return.")] = 15,
) -> dict[str, Any]:
    """Achieved and expected results of one WBG Results indicator, split by region, income group, FCS, country or institution.

    Each row has achieved (delivered so far), expected (what current projects expect to deliver over their life),
    achieved_to_expected (share delivered so far; not a performance grade) and share_of_global_achieved. Also returns the
    global total for the same institution/snapshot and data notes. Examples: 'Which regions reached the most people with
    broadband?' -> breakdown='region'; 'progress since FY2024' -> compare_snapshots=true, sort_by='change';
    'results in fragile states' -> breakdown='fcs'; 'top countries' -> breakdown='country'.
    """
    return _call(q.get_results, ind_code, breakdown, institution, snapshot_fy, compare_snapshots, series, sort_by, top_n)


@mcp.tool(title="Country profile", annotations=READ_ONLY)
def get_country_profile(
    country: Annotated[str, Field(description="Country name or ISO2/ISO3 code, e.g. 'Kenya', 'KE', 'KEN'.")],
    snapshot_fy: Snapshot = None,
) -> dict[str, Any]:
    """One-stop summary for a country: attributes, all WBG results there, and the country's Client Context.

    Returns region, income group, FCS/LDC/SIDS status and lending eligibility; every WBG Results indicator with a reported
    result in the country (achieved, expected, and achieved in the previous snapshot); the latest Client Context values
    for the country next to the average for all WBG client countries; and how many World Bank projects report results.
    Use for 'What has the World Bank Group done in X?' or for comparing need vs delivery in a country.
    """
    return _call(q.get_country_profile, country, snapshot_fy)


@mcp.tool(title="Search projects", annotations=READ_ONLY)
def search_projects(
    ind_code: Annotated[str | None, Field(description="Optional WBG Results indicator code to filter by.")] = None,
    country: Annotated[str | None, Field(description="Optional country name or ISO code.")] = None,
    region: Annotated[str | None, Field(description="Optional World Bank region code or name (AFE, AFW, EAP, ECA, LCR, MENAAP, SAR).")] = None,
    keyword: Annotated[str | None, Field(description="Optional word to match in project names/descriptions, e.g. 'solar'.")] = None,
    snapshot_fy: Snapshot = None,
    sort_by: Annotated[Literal["expected", "achieved", "commitment", "approval_date"],
                       Field(description="Sort projects (descending).")] = "expected",
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum projects to return.")] = 10,
) -> dict[str, Any]:
    """World Bank (IBRD/IDA) projects that contribute to Scorecard results, with links to their project pages.

    Each project shows its name, country, region, the indicator, its achieved and expected contribution, total net
    commitment (USD), approval/closing fiscal year, status (A = active, C = closed) and URL. Use to give concrete
    examples behind a number ('Which projects bring electricity to Nigeria?'). IFC and MIGA projects are not included.
    """
    return _call(q.search_projects, ind_code, country, region, keyword, snapshot_fy, sort_by, limit)


@mcp.tool(title="Client Context / Vision trend", annotations=READ_ONLY)
def get_context_trend(
    ind_code: Annotated[str, Field(description="A Client Context or Vision indicator code, e.g. 'EG_ELC_ACCS_ZS'.")],
    areas: Annotated[list[str] | None, Field(description="Places or groups to compare: country names/ISO codes, region codes "
                                                         "(AFE, SAR, ...), 'FCS', 'LIC', or 'global'. Omit for the global value.")] = None,
    country_group: Annotated[Literal["WBG", "IBRD", "IDA"], Field(description="For group-level values: all WBG client countries "
                                                                              "('WBG'), or only IBRD-/IDA-eligible countries.")] = "WBG",
    start_year: Annotated[int | None, Field(description="Optional first calendar year, e.g. 2015.")] = None,
    series: Annotated[str | None, Field(description="Optional series code when an indicator has several (see series_available).")] = None,
) -> dict[str, Any]:
    """Yearly values of a Client Context or Vision indicator for one or more places (the size of the challenge).

    Returns a time series per place, the latest value, and whether higher or lower is better. Combine with get_results to
    contrast need (e.g. % of people without electricity) with WBG delivery (people given electricity access).
    """
    return _call(q.get_context_trend, ind_code, areas, country_group, start_year, series)


@mcp.tool(title="Read-only SQL", annotations=READ_ONLY)
def run_sql(
    sql: Annotated[str, Field(description="One read-only DuckDB SELECT/WITH query over the views described in the "
                                          "scorecard://schema resource. Max 200 rows returned.")],
) -> dict[str, Any]:
    """Escape hatch for questions the other tools cannot answer (custom filters, joins, rankings).

    Prefer the views `results`, `results_detail`, `country_results`, `context`, `project_results`: they already apply the
    data rules. Remember: filter org_code (never sum across institutions); global totals use area_code = 'ACW'; values are
    in each indicator's own unit. File access, writes and multi-statement queries are blocked; 10-second timeout.
    """
    return _call(q.run_sql, sql)


# -------------------------------------------------------------------------- resources


@mcp.resource("scorecard://guide", title="Scorecard data guide", mime_type="text/markdown",
              description="Plain-language guide: the World Bank Group, the Scorecard, key concepts, data rules, limitations, indicators.")
def guide() -> str:
    return guide_parts()[0]


@mcp.resource("scorecard://how-to-use", title="How to use the assistant", mime_type="text/markdown",
              description="One-page user guide: what you can ask, what data is searched, how to read the answers.")
def how_to_use() -> str:
    return (KNOWLEDGE / "how_to_use.md").read_text()


@mcp.resource("scorecard://assistant-sop", title="Assistant SOP", mime_type="text/markdown",
              description="Operating procedure for AI assistants answering questions with this data.")
def assistant_sop() -> str:
    return guide_parts()[1]


@mcp.resource("scorecard://schema", title="Database schema", mime_type="text/markdown",
              description="Views, tables and columns available to run_sql.")
def schema() -> str:
    return q.SCHEMA_DOC


@mcp.resource("scorecard://indicators", title="Indicator catalogue", mime_type="application/json",
              description="All 52 indicators with tier, outcome area, unit and data availability.")
def indicators() -> str:
    cols = ("ind_code", "name", "tier", "outcome_area", "unit", "better_when", "reports_achieved", "reports_expected", "snapshots_with_data")
    return json.dumps([{k: c[k] for k in cols} for c in q.catalog().values()], indent=1)


@mcp.resource("scorecard://indicators/{ind_code}", title="Indicator profile", mime_type="application/json",
              description="Profile of one indicator (same content as the get_indicator_profile tool).")
def indicator_resource(ind_code: str) -> str:
    return json.dumps(_call(q.get_indicator_profile, ind_code), indent=1, default=str)


# ---------------------------------------------------------------------------- prompts


@mcp.prompt(title="Country briefing", description="Two-minute briefing on WBG results and context in one country.")
def country_briefing(country: str) -> str:
    return (f"Prepare a short briefing for a policymaker on the World Bank Group's results in {country}. "
            "Use get_country_profile, then highlight the 3 largest results, how they changed since the previous snapshot, "
            "and where the country's Client Context shows the biggest needs compared with all client countries. "
            "Add 2 example World Bank projects with search_projects. Follow the assistant SOP answer format.")


@mcp.prompt(title="Outcome area stocktake", description="Where the WBG stands on one outcome area, globally and by region.")
def outcome_area_stocktake(outcome_area: str) -> str:
    return (f"Give a stocktake of the '{outcome_area}' outcome area. Find its indicators with search_indicators. For each "
            "WBG Results indicator, report the latest global achieved and expected results and the change across snapshots; "
            "then show which regions deliver the most and which lag (get_results with compare_snapshots). Contrast with the "
            "related Client Context trend. End with the two biggest gaps or opportunities the data suggests.")


@mcp.prompt(title="Compare groups", description="Compare results for a topic across regions, income groups or fragile states.")
def compare_groups(topic: str, breakdown: str = "region") -> str:
    return (f"Compare World Bank Group results on '{topic}' across {breakdown} groups. Identify the right indicator(s) with "
            f"search_indicators, call get_results with breakdown='{breakdown}' and compare_snapshots=true, and present a small "
            "table plus a chart. Explain differences in plain language and note relevant caveats.")


def main() -> None:
    ap = argparse.ArgumentParser(description="WBG Scorecard MCP server")
    ap.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()
    if args.http:
        import uvicorn
        uvicorn.run(mcp.streamable_http_app(host=args.host), host=args.host, port=args.port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
