"""Runtime settings, read from environment variables (and a local .env file).

Real environment variables (e.g. Hugging Face Space secrets) take precedence
over .env, which is only for local development and is never committed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v:
            return v.strip()
    return default


@dataclass(frozen=True)
class Settings:
    # LLM_* names follow the assessment brief; ANTHROPIC_* are the SDK's own names.
    api_key: str = _env("LLM_API_KEY", "ANTHROPIC_API_KEY")
    model: str = _env("LLM_MODEL_NAME", "ANTHROPIC_MODEL", default="claude-sonnet-5-5")
    base_url: str = _env("LLM_BASE_URL", "ANTHROPIC_BASE_URL")
    effort: str = _env("LLM_EFFORT", default="medium")
    max_tool_rounds: int = int(_env("MAX_TOOL_ROUNDS", default="8"))
    max_output_tokens: int = int(_env("MAX_OUTPUT_TOKENS", default="16000"))
    # Public-deployment guardrails
    rate_limit_per_hour: int = int(_env("RATE_LIMIT_PER_HOUR", default="30"))
    daily_budget_usd: float = float(_env("DAILY_BUDGET_USD", default="10"))
    max_input_chars: int = int(_env("MAX_INPUT_CHARS", default="2000"))
    max_turns_per_session: int = int(_env("MAX_TURNS_PER_SESSION", default="20"))
    session_ttl_minutes: int = int(_env("SESSION_TTL_MINUTES", default="120"))
    verify_retry: bool = _env("VERIFY_RETRY", default="true").lower() == "true"


settings = Settings()

# USD per million tokens: (input, output, cache read). Cache writes bill at 1.25x input.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-fable-5-1": (10.00, 50.00, 0.25),
}
