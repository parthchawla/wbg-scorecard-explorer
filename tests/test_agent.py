"""Tests for the agent: grounding verifier, guardrails, and the tool loop (with a scripted fake LLM)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS
from typing import Any

import pytest

from app.agent import loop
from app.agent.guardrails import Budget, RateLimiter, Session, SessionStore, cost_usd
from app.agent.verify import extract_claims, verify_answer
from app.scorecard import queries as q
from pipeline import config

needs_db = pytest.mark.skipif(not config.DB_PATH.exists(), reason="run `python -m pipeline --offline` first")


# --------------------------------------------------------------------------- verifier


def test_extract_claims_normalises_and_skips_non_claims():
    text = ("**258.4 million** people (50.5% of 511.7 million) in FY2026; US$1.2bn mobilized; top 3 regions; "
            "ages 15-24; $3.00/day; CSC_RES_ELC_ACCS; P179687; between 2015 and 2024.\n1. First item")
    got = {c.text: (c.value, c.is_pct) for c in extract_claims(text)}
    want = {"258.4 million": (258.4e6, False), "50.5%": (50.5, True), "511.7 million": (511.7e6, False),
            "US$1.2bn": (1.2e9, False)}
    assert got.keys() == want.keys()
    for k, (v, pct) in want.items():
        assert got[k] == (pytest.approx(v), pct)


@needs_db
def test_verifier_accepts_grounded_and_derived_figures():
    ev = [q.get_results("CSC_RES_ELC_ACCS", "region", compare_snapshots=True)]
    rows = {r["area_code"]: r for r in ev[0]["rows"]}
    afe, afw = rows["AFE"], rows["AFW"]
    text = (f"AFE reached {afe['achieved'] / 1e6:.1f} million ({afe['share_of_global_achieved'] * 100:.0f}% of the total), "
            f"up {afe['pct_change_achieved_fy2024_to_fy2026']:.0f}% since FY2024, {afe['achieved'] / afw['achieved']:.1f} "
            f"times AFW's {afw['achieved'] / 1e6:.1f} million; together {(afe['achieved'] + afw['achieved']) / 1e6:.1f} million.")
    assert verify_answer(text, ev).status == "verified"


@needs_db
@pytest.mark.parametrize("fake", ["Western and Central Africa reached 61.3 million people.", "Results rose 37% in AFW.",
                                  "AFE delivered 55% of expected.", "South Asia reached 12.4 million."])
def test_verifier_flags_invented_figures(fake):
    ev = [q.get_results("CSC_RES_ELC_ACCS", "region", compare_snapshots=True)]
    assert verify_answer(fake, ev).status == "unverified"


@needs_db
def test_verifier_handles_units_charts_and_percentage_points():
    ghg = [q.get_results("CSC_RES_GHG_EMS_YEAR", "global")]
    assert verify_answer("a net reduction of 344.8 million tonnes (344.8 MtCO2eq) a year", ghg).status == "verified"
    ctx = [q.get_context_trend("EG_ELC_ACCS_ZS", ["AFE", "global"])]
    assert verify_answer("52.6% in AFE vs 90.7% overall: a gap of 38.1 percentage points.", ctx).status == "verified"
    bro = [q.get_results("CSC_RES_BRO_INTE", "region", compare_snapshots=True)]
    assert verify_answer("", bro, [(73.6, "people (millions)"), (29.6, "people (millions)")]).status == "verified"
    assert verify_answer("", bro, [(81.2, "people (millions)")]).status == "unverified"


def test_verifier_statuses_without_numbers_or_data():
    assert verify_answer("No figures here.", [{"x": 1}]).status == "no_numbers"
    assert verify_answer("We reached 45.2 million people.", []).status == "no_data"
    assert verify_answer("Yes, 45.2 million as you said.", [{"x": 1}], question="Is it 45.2 million?").status == "no_numbers"


# -------------------------------------------------------------------------- guardrails


def test_rate_limiter_blocks_after_limit():
    rl = RateLimiter(per_hour=2)
    assert rl.check("a")[0] and rl.check("a")[0]
    allowed, wait = rl.check("a")
    assert not allowed and wait > 0
    assert rl.check("b")[0]


def test_budget_and_cost():
    usd = cost_usd("claude-opus-5-5", {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 1_000_000})
    assert usd == pytest.approx(4.0 + 2.0 + 0.2)
    b = Budget(daily_usd=1.0)
    assert b.available()
    b.add(1.5)
    assert not b.available()


def test_session_store_reuses_and_expires():
    store = SessionStore(ttl_minutes=60)
    s = store.get(None)
    assert store.get(s.id) is s
    s.last_used -= 3601
    assert store.get(s.id) is not s


# ------------------------------------------------------------------- agent loop (fake LLM)


class FakeStream:
    def __init__(self, message: Any) -> None:
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for b in self.message.content:
                if b.type == "text":
                    yield NS(type="content_block_delta", delta=NS(type="text_delta", text=b.text))
        return gen()

    async def get_final_message(self):
        return self.message


class FakeClient:
    """Replays scripted assistant messages and records each request."""

    def __init__(self, script: list[Any]) -> None:
        self.script, self.requests = list(script), []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **req):
        self.requests.append(req)
        return FakeStream(self.script.pop(0))


def msg(*blocks, stop="end_turn"):
    return NS(content=list(blocks), stop_reason=stop,
              usage=NS(input_tokens=10, output_tokens=20, cache_creation_input_tokens=0, cache_read_input_tokens=100))


def text(t):
    return NS(type="text", text=t)


def tool(id_, name, inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def run(session: Session, question: str, script: list[Any], monkeypatch) -> tuple[list[dict], FakeClient]:
    fake = FakeClient(script)
    monkeypatch.setattr(loop, "client", lambda: fake)

    async def collect():
        return [e async for e in loop.run_turn(session, question, model="claude-opus-5-5")]

    return asyncio.run(collect()), fake


@needs_db
def test_loop_runs_mcp_tools_charts_and_verifies(monkeypatch):
    total = q.get_results("CSC_RES_ELC_ACCS", "global")["rows"][0]["achieved"]
    script = [
        msg(text("Looking that up."), tool("t1", "get_results", {"ind_code": "CSC_RES_ELC_ACCS", "breakdown": "global"}),
            tool("t2", "make_chart", {"chart_type": "bar", "title": "x", "categories": ["All"],
                                      "series": [{"name": "achieved", "values": [round(total / 1e6, 1)]}],
                                      "unit": "people (millions)"}), stop="tool_use"),
        msg(text(f"WBG projects reached **{total / 1e6:.1f} million** people.")),
    ]
    session = Session(id="s1")
    events, fake = run(session, "How many people got electricity?", script, monkeypatch)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "session" and kinds[-1] == "done"
    assert {"tool_call", "tool_result", "chart", "verification"} <= set(kinds)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["ok"] and result["data"]["rows"][0]["achieved"] == total
    assert next(e for e in events if e["type"] == "verification")["status"] == "verified"
    # Both tool results went back in ONE user message, and history is append-only.
    tool_msg = session.messages[2]
    assert tool_msg["role"] == "user" and [r["tool_use_id"] for r in tool_msg["content"]] == ["t1", "t2"]
    assert [m["role"] for m in session.messages] == ["user", "assistant", "user", "assistant"]
    # Request carries cached system prompt, effort and the refusal fallback.
    req = fake.requests[0]
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["output_config"]["effort"] and req["fallbacks"] == "default"
    assert {t["name"] for t in req["tools"]} >= {"get_results", "search_indicators", "make_chart"}


@needs_db
def test_loop_revises_unverified_answer_once(monkeypatch):
    script = [
        msg(tool("t1", "get_results", {"ind_code": "CSC_RES_ELC_ACCS", "breakdown": "global"}), stop="tool_use"),
        msg(text("WBG projects reached 999.9 million people.")),  # invented
        msg(text("WBG projects reached people with electricity (see the data panel).")),
    ]
    session = Session(id="s2")
    events, _ = run(session, "How many people got electricity?", script, monkeypatch)
    checks = [e for e in events if e["type"] == "verification"]
    assert [c["status"] for c in checks] == ["unverified", "no_numbers"]
    assert any(e["type"] == "revision" for e in events)
    assert "999.9 million" in session.messages[-2]["content"]  # feedback names the bad figure


@needs_db
def test_loop_reports_tool_errors_to_model(monkeypatch):
    script = [
        msg(tool("t1", "get_results", {"ind_code": "SE_LPV_PRIM"}), stop="tool_use"),
        msg(text("That is a Client Context indicator.")),
    ]
    session = Session(id="s3")
    events, _ = run(session, "Learning poverty results?", script, monkeypatch)
    res = next(e for e in events if e["type"] == "tool_result")
    assert not res["ok"] and "get_context_trend" in res["summary"]
    assert session.messages[2]["content"][0]["is_error"] is True
