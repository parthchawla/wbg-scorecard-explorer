"""System prompt: the assistant SOP + data guide (from app/knowledge) + app-specific notes.

The prompt is static per day so it is cached across requests (tools render
before the system prompt, so the cache covers the tool definitions too).
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from app.mcp_server import guide_parts
from app.scorecard import queries as q
from app.scorecard.queries import SCHEMA_DOC

APP_NOTES = """\
# Part C: Notes for this web app

- Today is {today}. The latest Scorecard snapshot is FY{latest}; snapshots available: {snapshots}.
- You are embedded in the "Scorecard Explorer" web app. The app shows the user every tool call you make and its data
  ("How this was answered"), so do not paste raw JSON or tool output; summarise it.
- An automated checker compares every number in your final answer (and in charts) with the numbers your tools returned.
  Quote figures as returned, or rounded (e.g. 258,393,655 -> "258.4 million"). Prefer figures the tools computed
  (achieved_to_expected, share_of_global_achieved, change_*, pct_change_*) over doing your own arithmetic.
- Use the `make_chart` tool when a comparison of 3+ places, groups or years would be clearer as a picture. Use values
  exactly as returned by the data tools (you may convert units, e.g. people -> millions, and say so in `unit`).
  Do not describe the chart in detail afterwards; one sentence on the takeaway is enough.
- Format answers in Markdown: short paragraphs, bullet lists, and small tables. Bold the single most important number.
- Before your first tool call, write at most one short sentence on what you are looking up (or nothing).

## Database schema for `run_sql` (use it to explore questions the other tools don't cover)

{schema}
"""

CHART_TOOL = {
    "name": "make_chart",
    "description": (
        "Show the user a chart (rendered in the web app). Use for comparisons across 3+ places, groups or years. "
        "Values must come from data-tool results. Returns a confirmation only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "chart_type": {"type": "string", "enum": ["bar", "horizontal_bar", "grouped_bar", "stacked_bar", "line"],
                           "description": "bar/horizontal_bar for one series across categories; grouped_bar to compare "
                                          "series (e.g. achieved vs expected, or FY2024 vs FY2026); line for years."},
            "title": {"type": "string", "description": "Short, plain-language title."},
            "subtitle": {"type": "string", "description": "Indicator, institution, snapshot, e.g. 'WBG, achieved, FY2026 snapshot'."},
            "categories": {"type": "array", "items": {"type": "string"}, "description": "X-axis labels (places, groups or years)."},
            "series": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "values": {"type": "array", "items": {"type": ["number", "null"]},
                                   "description": "One value per category, in the same order."},
                    },
                    "required": ["name", "values"],
                },
            },
            "unit": {"type": "string", "description": "Unit of the values, e.g. 'people (millions)', '%', 'GW'."},
            "source_note": {"type": "string", "description": "Short source note, e.g. 'WBG Scorecard, FY2026 snapshot'."},
        },
        "required": ["chart_type", "title", "categories", "series", "unit"],
    },
}


@lru_cache(maxsize=4)
def _system_prompt(day: str) -> str:
    part_a, part_b = guide_parts()
    notes = APP_NOTES.format(today=day, latest=q.latest_snapshot(), snapshots=", ".join(f"FY{s}" for s in q.snapshots()),
                             schema=SCHEMA_DOC.replace("# Database schema (DuckDB, read-only)\n\n", ""))
    return f"{part_b}\n\n{notes}\n\n---\n\n{part_a}"


def system_prompt() -> str:
    return _system_prompt(date.today().isoformat())
