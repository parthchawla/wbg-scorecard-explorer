"""Guardrails for a public deployment: per-visitor rate limit, daily spend cap,
conversation sessions, and cost accounting. All in-memory (single container)."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from threading import Lock
from typing import Any

from app.config import PRICES, settings


def cost_usd(model: str, usage: dict[str, int]) -> float:
    inp, out, cache_read = PRICES.get(model, PRICES["claude-opus-5-5"])
    return (
        usage.get("input_tokens", 0) * inp
        + usage.get("cache_creation_input_tokens", 0) * inp * 1.25
        + usage.get("cache_read_input_tokens", 0) * cache_read
        + usage.get("output_tokens", 0) * out
    ) / 1e6


class RateLimiter:
    def __init__(self, per_hour: int) -> None:
        self.per_hour = per_hour
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Record a hit; returns (allowed, seconds_until_next_slot)."""
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= self.per_hour:
                return False, int(3600 - (now - q[0])) + 1
            q.append(now)
            return True, 0


class Budget:
    def __init__(self, daily_usd: float) -> None:
        self.daily_usd = daily_usd
        self.day = date.today()
        self.spent = 0.0
        self.lock = Lock()

    def _roll(self) -> None:
        if date.today() != self.day:
            self.day, self.spent = date.today(), 0.0

    def available(self) -> bool:
        with self.lock:
            self._roll()
            return self.spent < self.daily_usd

    def add(self, usd: float) -> None:
        with self.lock:
            self._roll()
            self.spent += usd


@dataclass
class Session:
    id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[Any] = field(default_factory=list)  # every data-tool result in this conversation
    turns: int = 0
    last_used: float = field(default_factory=time.time)


class SessionStore:
    """Conversation history per browser session. Append-only: earlier turns (including
    thinking blocks) are never edited, as current Claude models require."""

    def __init__(self, ttl_minutes: int, max_sessions: int = 2000) -> None:
        self.ttl = ttl_minutes * 60
        self.max_sessions = max_sessions
        self.sessions: dict[str, Session] = {}
        self.lock = Lock()

    def get(self, session_id: str | None) -> Session:
        now = time.time()
        with self.lock:
            for sid in [s for s, v in self.sessions.items() if now - v.last_used > self.ttl]:
                del self.sessions[sid]
            if session_id and session_id in self.sessions:
                s = self.sessions[session_id]
            else:
                if len(self.sessions) >= self.max_sessions:
                    oldest = min(self.sessions.values(), key=lambda v: v.last_used)
                    del self.sessions[oldest.id]
                s = Session(id=uuid.uuid4().hex)
                self.sessions[s.id] = s
            s.last_used = now
            return s

    def reset(self, session_id: str) -> None:
        with self.lock:
            self.sessions.pop(session_id, None)


rate_limiter = RateLimiter(settings.rate_limit_per_hour)
budget = Budget(settings.daily_budget_usd)
sessions = SessionStore(settings.session_ttl_minutes)
