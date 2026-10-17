"""Grounding verifier: are the numbers in an answer supported by the tool results?

Extracts every quantitative claim from the answer text (and chart values),
normalises it ("258.4 million", "47%", "$1.2bn", "0.95 GW"), and matches it
against every number returned by the data tools in the same turn, allowing
for display rounding and for simple derivations the model is likely to make
(percentages of ratio fields, and differences, sums and multiples of comparable values).
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

SCALE_WORDS = {
    "thousand": 1e3, "k": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6, "mln": 1e6,
    "billion": 1e9, "bn": 1e9, "b": 1e9, "trillion": 1e12, "tn": 1e12,
}

NUM_RE = re.compile(
    r"""(?<![\w.])                       # not part of a word/code
        (?P<cur>US\$|\$)?\s?
        (?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
        (?:\s?(?P<scale>thousand|million|billion|trillion|mln|mn|bn|tn|k|m|b)\b)?
        (?:\s?(?P<pct>%|percent\b|per\s?cent\b|percentage\s+points?\b|pp\b))?
    """,
    re.I | re.X,
)
# Things that look like numbers but aren't claims about the data.
SKIP_PATTERNS = [
    re.compile(r"\bFY\s?\d{2,4}\b", re.I),                    # FY2026, FY24
    re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b"),             # indicator codes
    re.compile(r"\bP\d{6}\b"),                                # project ids
    re.compile(r"\b(?:19|20)\d{2}\s?[-–]\s?(?:19|20)?\d{2}\b"), # year ranges
    re.compile(r"\$\s?\d+(?:\.\d+)?\s?(?:/|a |per )\s?day", re.I),  # poverty lines
    re.compile(r"https?://\S+"),
    re.compile(r"^\s*\d+[.)]\s", re.M),                      # list numbering
    re.compile(r"\b\d{1,2}\s?(?:-|to)\s?\d{1,2}\s?(?:years?|yrs)\b", re.I),  # age ranges
    re.compile(r"\bages?\s+\d+(?:\s?[-–]\s?\d+)?", re.I),
    re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.I),
]


@dataclass
class Claim:
    text: str
    value: float          # absolute value (scale applied); for percents, the percent number
    is_pct: bool
    tolerance: float      # half a unit of the last displayed digit, in absolute terms


@dataclass
class Verification:
    status: str                                   # verified | unverified | no_numbers | no_data
    checked: int = 0
    verified: int = 0
    unverified: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "checked": self.checked, "verified": self.verified, "unverified": self.unverified}


def _mask(text: str) -> str:
    for pat in SKIP_PATTERNS:
        text = pat.sub(lambda m: " " * len(m.group(0)), text)
    return text


def extract_claims(text: str, ignore: Iterable[float] = ()) -> list[Claim]:
    ignore_set = {round(x, 6) for x in ignore}
    masked = _mask(text)
    claims = []
    for m in NUM_RE.finditer(masked):
        raw = m.group("num").replace(",", "")
        num = float(raw)
        scale_word = (m.group("scale") or "").lower()
        # "m"/"b" only count as scales when attached to a currency or clearly magnitude-like.
        if scale_word in ("m", "b") and not m.group("cur") and num >= 1000:
            scale_word = ""
        scale = SCALE_WORDS.get(scale_word, 1.0)
        pct = (m.group("pct") or "").lower()
        # "percentage points" are differences between two percentages: checked like plain numbers.
        is_pct = bool(pct) and "point" not in pct and pct != "pp"
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        # Standalone small integers ("top 3", "2 projects") and bare years are not data claims.
        if not pct and scale == 1.0 and decimals == 0:
            if num <= 12 or (1990 <= num <= 2040):
                continue
        if round(num, 6) in ignore_set:
            continue
        unit = 10 ** (-decimals) if decimals else 1.0
        claims.append(Claim(text=m.group(0).strip(), value=num * scale, is_pct=is_pct, tolerance=0.5 * unit * scale))
    return claims


RATIO_KEYS = ("achieved_to_expected", "share", "ratio", "coverage")
PCT_KEYS = ("pct", "percent")
PCT_UNITS = ("percent", "index")


@dataclass
class Pools:
    values: set[float] = field(default_factory=set)          # every number returned
    pcts: set[float] = field(default_factory=set)            # numbers that may be quoted with a % sign
    rows: list[tuple[int, dict[str, float]]] = field(default_factory=list)  # (list id, numeric fields) per record


def _walk(obj: Any, pools: Pools, unit_ctx: str = "", group: int = 0) -> None:
    """unit_ctx: the unit inherited from the enclosing result (rows usually don't repeat it)."""
    if isinstance(obj, dict):
        unit = str(obj.get("unit") or "").lower()
        if not unit and isinstance(obj.get("indicator"), dict):
            unit = str(obj["indicator"].get("unit") or "").lower()
        unit = unit or unit_ctx
        here_pct = any(u in unit for u in PCT_UNITS)
        row: dict[str, float] = {}
        for k, v in obj.items():
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, (int, float)) and math.isfinite(v):
                v = float(v)
                row[k] = v
                pools.values.add(v)
                if "mtco2" in unit:  # megatonnes may be quoted as "million tonnes"
                    pools.values.add(v * 1e6)
                if any(r in k for r in RATIO_KEYS) and abs(v) <= 10:
                    pools.pcts.add(v * 100)
                if any(p in k for p in PCT_KEYS) or (here_pct and -1000 <= v <= 1000):
                    pools.pcts.add(v)
            else:
                _walk(v, pools, unit, group)
        if row:
            pools.rows.append((group, row))
    elif isinstance(obj, (list, tuple)):
        gid = id(obj)
        for v in obj:
            _walk(v, pools, unit_ctx, gid)


def evidence_pools(evidence: list[Any]) -> Pools:
    pools = Pools()
    for result in evidence:
        _walk(result, pools)
    return pools


def _derived(pools: Pools) -> tuple[set[float], set[float]]:
    """Comparisons a writer plausibly makes: within a record (e.g. FY2026 minus FY2024, achieved vs
    expected) and between records on the same field (A minus B, A plus B, A as % of B, A / B)."""
    vals, pcts = set(), set()
    # Percentages are NOT derived: the tools already return the ones people quote (achieved_to_expected,
    # share_of_global_achieved, pct_change_*), and deriving more makes chance matches too likely.
    # Within one record: differences and multiples (e.g. FY2026 minus FY2024, achieved vs expected).
    for _, row in pools.rows:
        nums = [v for k, v in row.items() if v and k != "year"][:30]
        for a, b in itertools.permutations(nums, 2):
            vals.update((a - b, a / b))
    # Across records, same field only: differences, sums and multiples ("1.9 times"). For yearly series,
    # compare places in the same year, or the latest year of a series with its earlier years.
    by_key: dict[tuple, list[float]] = {}
    latest_change: set[float] = set()
    series: dict[int, list[dict[str, float]]] = {}
    for gid, row in pools.rows:
        if "year" in row:
            series.setdefault(gid, []).append(row)
        for k, v in row.items():
            if v and k != "year":
                by_key.setdefault((k, row.get("year")), []).append(v)
    for pts in series.values():
        last = max(pts, key=lambda r: r["year"])
        for r in pts:
            for k, v in r.items():
                if k != "year" and k in last and r is not last:
                    latest_change.add(last[k] - v)
                    if v:
                        latest_change.add(last[k] / v)
    vals |= latest_change
    for nums in by_key.values():
        for a, b in itertools.permutations(nums[:80], 2):
            vals.update((a - b, a + b, a / b))
    return vals, pcts


def _close(claim: Claim, v: float, relative: bool = True) -> bool:
    """Direct values compare by magnitude ("a reduction of 180 Mt" vs -180); derived values keep
    their sign so that "up 37%" cannot match a 37% fall."""
    tol = claim.tolerance * 1.01
    if relative:
        tol = max(tol, 0.006 * abs(v))
        return abs(abs(claim.value) - abs(v)) <= tol
    return abs(claim.value - v) <= tol


def _chart_claim(v: float, unit: str) -> Claim:
    """Chart values are checked like text figures; the chart's unit says how they were scaled."""
    u = (unit or "").lower()
    scale = next((f for w, f in (("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3)) if w in u), 1.0)
    s = f"{v:.10g}"
    decimals = len(s.split(".")[1]) if "." in s and "e" not in s else 0
    return Claim(text=f"chart value {s}{' ' + unit if unit else ''}", value=float(v) * scale,
                 is_pct="%" in u or "percent" in u, tolerance=0.5 * 10 ** (-decimals) * scale)


def verify_answer(text: str, evidence: list[Any], chart_values: Iterable[tuple[float, str]] = (), question: str = "") -> Verification:
    q_numbers = [c.value for c in extract_claims(question)] + [
        float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", question)]
    claims = extract_claims(text, ignore=q_numbers)
    claims += [_chart_claim(v, unit) for v, unit in chart_values if v is not None]
    if not claims:
        return Verification(status="no_numbers")
    if not evidence:
        return Verification(status="no_data", checked=len(claims), unverified=[c.text for c in claims])
    pools = evidence_pools(evidence)
    derived: tuple[set[float], set[float]] | None = None
    unverified = []
    for c in claims:
        if any(_close(c, v) for v in (pools.pcts if c.is_pct else pools.values)):
            continue
        if derived is None:
            derived = _derived(pools)
        if any(_close(c, v, relative=False) for v in (derived[1] if c.is_pct else derived[0])):
            continue
        unverified.append(c.text)
    return Verification(
        status="verified" if not unverified else "unverified",
        checked=len(claims),
        verified=len(claims) - len(unverified),
        unverified=unverified,
    )
