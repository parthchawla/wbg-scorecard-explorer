"""FastAPI app: chat API (SSE), dashboard data API, docs, the MCP endpoint, and the built frontend.

    uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from app.agent.guardrails import budget, rate_limiter, sessions
from app.agent.loop import run_turn, to_sse
from app.config import settings
from app.mcp_server import KNOWLEDGE, guide_parts, mcp
from app.scorecard import queries as q

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

# Public MCP endpoint at /mcp. Stateless + JSON responses work behind proxies (Hugging Face) without
# sticky sessions. DNS-rebinding protection is off: the server is read-only public data with no credentials.
mcp_http = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    host="0.0.0.0",
)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    q.catalog()  # warm caches and fail fast if the database is missing
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="WBG Scorecard Explorer", version="1.0", lifespan=lifespan, docs_url="/api/docs")
app.router.routes.extend(mcp_http.routes)
app.add_middleware(GZipMiddleware, minimum_size=1024)

EXAMPLES = [
    "Which regions made the most progress in digital access in recent years?",
    "Compare climate resilience results in fragile and conflict-affected states with the global total.",
    "What are the top 3 lagging WBG Results indicators, comparing achieved with expected results?",
    "What has the World Bank Group achieved in Kenya?",
    "Which regions have the lowest electricity access, and how many people are WBG projects reaching there?",
    "Which projects are bringing clean water to Ethiopia?",
]


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


# ------------------------------------------------------------------------------- chat


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    text = req.message.strip()

    async def error_stream(msg: str):
        yield to_sse({"type": "error", "message": msg})

    def refuse(msg: str) -> StreamingResponse:
        return StreamingResponse(error_stream(msg), media_type="text/event-stream")

    if not settings.api_key:
        return refuse("No LLM API key is configured. Add ANTHROPIC_API_KEY (or LLM_API_KEY) to .env and restart.")
    if len(text) > settings.max_input_chars:
        return refuse(f"Please keep questions under {settings.max_input_chars} characters.")
    allowed, wait = rate_limiter.check(client_ip(request))
    if not allowed:
        return refuse(f"You've reached the hourly question limit for this demo. Please try again in {wait // 60 + 1} minutes.")
    if not budget.available():
        return refuse("The demo's daily usage budget has been reached. Please try again tomorrow, or run the app locally with your own key.")
    session = sessions.get(req.session_id)
    if session.turns >= settings.max_turns_per_session:
        return refuse("This conversation is getting long. Please start a new chat to keep answers fast and accurate.")

    async def stream():
        try:
            async for event in run_turn(session, text):
                yield to_sse(event)
        except Exception:
            log.exception("chat turn failed")
            yield to_sse({"type": "error", "message": "Something went wrong while answering. Please try again."})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat/reset")
async def reset(payload: dict[str, Any]) -> dict[str, bool]:
    if sid := payload.get("session_id"):
        sessions.reset(sid)
    return {"ok": True}


# ------------------------------------------------------------------------------- meta & docs


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "llm_configured": bool(settings.api_key), "latest_snapshot": q.latest_snapshot()}


@app.get("/api/meta")
def meta(request: Request) -> dict[str, Any]:
    return {
        "model": settings.model,
        "snapshots": q.snapshots(),
        "latest_snapshot": q.latest_snapshot(),
        "examples": EXAMPLES,
        "mcp_url": str(request.base_url).rstrip("/") + "/mcp",
        "limits": {"questions_per_hour": settings.rate_limit_per_hour, "max_input_chars": settings.max_input_chars},
        "llm_configured": bool(settings.api_key),
    }


@app.get("/api/content/{name}", response_class=PlainTextResponse)
def content(name: str) -> str:
    part_a, part_b = guide_parts()
    docs = {"guide": part_a, "sop": part_b, "how-to-use": (KNOWLEDGE / "how_to_use.md").read_text(), "schema": q.SCHEMA_DOC}
    if name not in docs:
        raise HTTPException(404, f"unknown document '{name}'")
    return docs[name]


# ---------------------------------------------------------------------- dashboard data (Step 4)


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except q.ScorecardQueryError as e:
        raise HTTPException(400, str(e)) from None


@app.get("/api/overview")
def api_overview() -> list[dict[str, Any]]:
    return q.overview()


@app.get("/api/countries")
def api_countries() -> list[dict[str, Any]]:
    return q.country_list()


@app.get("/api/indicators")
def api_indicators() -> list[dict[str, Any]]:
    return list(q.catalog().values())


@app.get("/api/indicators/{ind_code}")
def api_indicator(ind_code: str) -> dict[str, Any]:
    return _wrap(q.get_indicator_profile, ind_code)


@app.get("/api/results/{ind_code}")
def api_results(ind_code: str, breakdown: str = "region", institution: str = "WBG", snapshot_fy: int | None = None,
                compare_snapshots: bool = False, series: str | None = None, sort_by: str = "achieved", top_n: int = 250) -> dict[str, Any]:
    return _wrap(q.get_results, ind_code, breakdown, institution, snapshot_fy, compare_snapshots, series, sort_by, top_n)


@app.get("/api/countries/{country}")
def api_country(country: str, snapshot_fy: int | None = None) -> dict[str, Any]:
    return _wrap(q.get_country_profile, country, snapshot_fy)


@app.get("/api/context/{ind_code}")
def api_context(ind_code: str, areas: str | None = None, country_group: str = "WBG", start_year: int | None = None) -> dict[str, Any]:
    return _wrap(q.get_context_trend, ind_code, areas.split(",") if areas else None, country_group, start_year)


@app.get("/api/projects")
def api_projects(ind_code: str | None = None, country: str | None = None, region: str | None = None,
                 keyword: str | None = None, sort_by: str = "expected", limit: int = 20) -> dict[str, Any]:
    return _wrap(q.search_projects, ind_code, country, region, keyword, None, sort_by, limit)


# ------------------------------------------------------------------------------- frontend

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = FRONTEND_DIST / path
        if path and file.is_file() and FRONTEND_DIST in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def root() -> JSONResponse:
        return JSONResponse({"message": "API running. Build the frontend (cd frontend && npm run build) to serve the UI.",
                             "docs": "/api/docs", "mcp": "/mcp"})
