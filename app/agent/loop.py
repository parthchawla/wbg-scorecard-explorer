"""The agent: a streaming Claude tool-use loop over the Scorecard MCP server.

One call to `run_turn` answers one user message and yields UI events:

    session      {session_id}
    text         {delta, round}                 streamed answer text
    tool_call    {id, name, title, input}
    tool_result  {id, name, ok, summary, data}  data = the tool's structured result (for the evidence panel)
    chart        {id, spec}
    verification {status, checked, verified, unverified, attempt}
    revision     {reason}                       the answer is being revised after a failed check
    done         {model, usage, cost_usd, seconds, rounds, tool_calls}
    error        {message}

The data tools come from the MCP server through an in-process MCP client, so the
agent uses exactly the interface any other MCP client (e.g. Claude Desktop) sees.
`make_chart` is an app-side tool: rendering is specific to this UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator

import anthropic
from mcp import Client

from app.agent.guardrails import Session, budget, cost_usd
from app.agent.prompt import CHART_TOOL, system_prompt
from app.agent.verify import verify_answer
from app.config import settings
from app.mcp_server import mcp

log = logging.getLogger("agent")

FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5")
NO_EFFORT_PREFIXES = ("claude-3", "claude-haiku-4", "claude-sonnet-4-5", "claude-opus-4-1", "claude-opus-4-0")

TOOL_TITLES = {
    "search_indicators": "Searching indicators",
    "get_indicator_profile": "Reading indicator profile",
    "get_results": "Querying WBG results",
    "get_country_profile": "Building country profile",
    "search_projects": "Finding projects",
    "get_context_trend": "Reading client-country context",
    "run_sql": "Running a custom query",
    "make_chart": "Drawing a chart",
}

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        kwargs: dict[str, Any] = {"api_key": settings.api_key, "max_retries": 3, "timeout": 120.0}
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        _client = anthropic.AsyncAnthropic(**kwargs)
    return _client


def _request_params(model: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": settings.max_output_tokens,
        # Tools render before the system prompt, so this breakpoint caches both; the
        # top-level cache_control then caches the growing conversation automatically.
        "system": [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
        "cache_control": {"type": "ephemeral"},
    }
    if not model.startswith(NO_EFFORT_PREFIXES):
        params["output_config"] = {"effort": settings.effort}
    # Server-side refusal fallback (Claude API only): if a safety classifier declines, the API
    # re-runs the request on a suitable model instead of returning an empty answer.
    if model in FALLBACK_MODELS and not settings.base_url:
        params["betas"] = ["server-side-fallback-2026-07-01"]
        params["fallbacks"] = "default"
    return params


def _tool_defs(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    defs = [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in mcp_tools]
    return defs + [CHART_TOOL]


def _summarise(name: str, data: dict[str, Any] | None, text: str) -> str:
    if not data:
        return text[:160]
    for key, label in (("rows", "rows"), ("matches", "indicators"), ("projects", "projects"), ("series", "series"),
                       ("wbg_results", "results")):
        if isinstance(data.get(key), list):
            return f"{len(data[key])} {label}"
    return "ok"


def _validate_chart(spec: dict[str, Any]) -> str | None:
    cats, series = spec.get("categories") or [], spec.get("series") or []
    if not cats or not series:
        return "categories and series are required"
    for s in series:
        if len(s.get("values") or []) != len(cats):
            return f"series '{s.get('name')}' has {len(s.get('values') or [])} values for {len(cats)} categories"
    return None


def _usage_dict(u: Any) -> dict[str, int]:
    return {k: int(getattr(u, k, 0) or 0) for k in
            ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}


async def run_turn(session: Session, user_text: str, model: str | None = None) -> AsyncIterator[dict[str, Any]]:
    model = model or settings.model
    t0 = time.monotonic()
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    yield {"type": "session", "session_id": session.id}

    session.messages.append({"role": "user", "content": user_text})
    session.turns += 1
    # Answers may quote figures retrieved in earlier turns, so verify against the whole conversation.
    evidence = session.evidence
    chart_values: list[tuple[float, str]] = []
    rounds = tool_calls = 0
    params = _request_params(model)

    async with Client(mcp) as mcp_client:
        tools = _tool_defs((await mcp_client.list_tools()).tools)

        async def run_tool(block: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            """Execute one tool call; returns (tool_result block, UI events)."""
            events: list[dict[str, Any]] = []
            args = block.input if isinstance(block.input, dict) else {}
            if block.name == "make_chart":
                err = _validate_chart(args)
                if err:
                    return {"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": f"Invalid chart: {err}"}, events
                for s in args["series"]:
                    chart_values.extend((v, args.get("unit", "")) for v in s["values"] if isinstance(v, (int, float)))
                events.append({"type": "chart", "id": block.id, "spec": args})
                return {"type": "tool_result", "tool_use_id": block.id, "content": "Chart shown to the user."}, events
            try:
                res = await mcp_client.call_tool(block.name, args)
                text = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text") or "{}"
                data = res.structured_content
                ok = not res.is_error
            except Exception as e:  # transport-level failure; let the model recover
                log.exception("tool %s failed", block.name)
                text, data, ok = f"Tool failed: {e}", None, False
            if ok and data is not None:
                evidence.append(data)
            events.append({"type": "tool_result", "id": block.id, "name": block.name, "ok": ok,
                           "summary": _summarise(block.name, data, text) if ok else text[:300], "data": data if ok else None})
            result = {"type": "tool_result", "tool_use_id": block.id, "content": text}
            if not ok:
                result["is_error"] = True
            return result, events

        for attempt in range(2):
            final_text = ""
            for rnd in range(settings.max_tool_rounds + 1):
                rounds += 1
                req = dict(params, tools=tools, messages=session.messages)
                if rnd == settings.max_tool_rounds:
                    req["tool_choice"] = {"type": "none"}  # out of tool budget: answer with what we have
                try:
                    async with client().beta.messages.stream(**req) as stream:
                        async for ev in stream:
                            if ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta":
                                yield {"type": "text", "delta": ev.delta.text, "round": rounds}
                        msg = await stream.get_final_message()
                except anthropic.AuthenticationError:
                    yield {"type": "error", "message": "The LLM API key is missing or invalid. Set LLM_API_KEY / ANTHROPIC_API_KEY."}
                    return
                except anthropic.RateLimitError:
                    yield {"type": "error", "message": "The LLM service is busy (rate limited). Please try again in a minute."}
                    return
                except anthropic.APIStatusError as e:
                    log.exception("LLM API error")
                    yield {"type": "error", "message": f"LLM service error ({e.status_code}). Please try again."}
                    return
                except anthropic.APIConnectionError:
                    yield {"type": "error", "message": "Could not reach the LLM service. Please try again."}
                    return

                for k, v in _usage_dict(msg.usage).items():
                    usage[k] += v
                # Append the full content (thinking blocks included) unchanged: history is append-only.
                session.messages.append({"role": "assistant", "content": msg.content})

                if msg.stop_reason == "refusal":
                    yield {"type": "text", "delta": "\n\nI can't help with that request. Try asking about the Scorecard data.", "round": rounds}
                    break
                tool_uses = [b for b in msg.content if b.type == "tool_use"]
                if msg.stop_reason == "max_tokens" and tool_uses:
                    yield {"type": "error", "message": "The answer was cut off. Please ask a narrower question."}
                    return
                if not tool_uses:
                    final_text = "".join(b.text for b in msg.content if b.type == "text")
                    break
                for b in tool_uses:
                    tool_calls += 1
                    yield {"type": "tool_call", "id": b.id, "name": b.name, "title": TOOL_TITLES.get(b.name, b.name), "input": b.input}
                outcomes = await asyncio.gather(*(run_tool(b) for b in tool_uses))
                for _, events in outcomes:
                    for e in events:
                        yield e
                # All results for one assistant turn go back in a single user message.
                session.messages.append({"role": "user", "content": [r for r, _ in outcomes]})

            check = verify_answer(final_text, evidence, chart_values, question=user_text)
            yield {"type": "verification", "attempt": attempt, **check.as_dict()}
            if check.status != "unverified" or attempt == 1 or not settings.verify_retry:
                break
            reason = ("Automated check: these figures in your answer do not match any number returned by the data tools: "
                      + ", ".join(check.unverified[:10])
                      + ". Rewrite the full answer so every figure comes from tool results (call tools again if needed), "
                        "or remove those figures. Do not mention this check.")
            yield {"type": "revision", "reason": "Some figures could not be matched to the data; revising the answer."}
            session.messages.append({"role": "user", "content": reason})
            chart_values.clear()

    usd = cost_usd(model, usage)
    budget.add(usd)
    yield {"type": "done", "model": model, "usage": usage, "cost_usd": round(usd, 5),
           "seconds": round(time.monotonic() - t0, 1), "rounds": rounds, "tool_calls": tool_calls}


def to_sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
