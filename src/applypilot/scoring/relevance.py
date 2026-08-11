"""Harsh-specific role relevance gate.

Policy:
  Allow: Backend/API · Applied AI/LLM/RAG/Agents · Full-stack React/Next + backend
  Drop:  Pure SRE / Infra / Storage / Observability (unless also clearly AI/backend/fullstack)
  Senior: only if JD YOE overlaps ~2–5 and role family is allowed
  Comp:  floor 30 LPA / ~$40k when pay is stated; unstated → OK

Used by scorer (pre-LLM) and apply acquire_job (last-line skip).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Title patterns
# ---------------------------------------------------------------------------

_HARD_SENIORITY_BLOCK = re.compile(
    r"\b(Staff|Principal|Distinguished|Fellow|Director|VP|Vice\s*President|"
    r"Head\s+of|Manager|Intern(ship)?|Co-?op|Apprentice|Trainee|Fresher|"
    r"Entry[- ]?Level|New[- ]Grad)\b",
    re.I,
)

# Pure infra / ops domains — blocked unless an allow-family also matches
_PURE_INFRA_BLOCK = re.compile(
    r"\b("
    r"SRE|Site\s+Reliability|"
    r"Observability|"
    r"Storage|"
    r"Baremetal|Bare[- ]metal|"
    r"IaC|"
    r"Infrastructure|"
    r"Platform\s+Engineer|"
    r"Multigres|"
    r"Postgres\s+Engineer|"
    r"Database\s+Administrator|\bDBA\b|"
    r"Network\s+Engineer|"
    r"DevOps|"
    r"Fabric\s+Gateway|"
    r"Edge\s+Functions|"
    r"Auth\b"
    r")\b",
    re.I,
)

_ALLOW_BACKEND = re.compile(
    r"\b("
    r"Backend|Back[- ]end|API\s+Engineer|API\s+Platform|"
    r"Server[- ]?side|Services\s+Engineer|"
    r"Software\s+Engineer.*Backend|Backend.*Software\s+Engineer"
    r")\b",
    re.I,
)

_ALLOW_AI = re.compile(
    r"\b("
    r"AI\s+Engineer|Applied\s+AI|GenAI|Generative\s+AI|"
    r"LLM|RAG|Machine\s+Learning\s+Engineer|ML\s+Engineer|"
    r"AI\s+Agents?|Agent\s+Harness|Agents?\b|"
    r"AI\s+Platform|AI\s+Gateway|AI\s+Foundations|"
    r"Model\s+Routing|Inference|"
    r"Software\s+Engineer.*\bAI\b|\bAI\b.*Software\s+Engineer|"
    r"Backend.*\bAI\b|\bAI\b.*Backend"
    r")\b",
    re.I,
)

_ALLOW_FULLSTACK = re.compile(
    r"\b("
    r"Full[- ]?stack|Fullstack|"
    r"React|Next\.?js|NextJS|"
    r"Frontend.*Backend|Backend.*Frontend"
    r")\b",
    re.I,
)

# Generic "Software Engineer" alone is weak — need AI/backend/fullstack context
# in title OR description. Title-only soft allow when description later confirms.
_GENERIC_SWE = re.compile(
    r"\b(Software\s+Engineer|SDE|SDE[- ]?[I1]|Member\s+of\s+(Technical\s+)?Staff|"
    r"MTS)\b",
    re.I,
)

_SENIOR_TITLE = re.compile(r"\bSenior\b", re.I)

# YOE extraction from JD
_YOE_RANGE = re.compile(
    r"(?P<a>\d+)\s*[-–—to]+\s*(?P<b>\d+)\s*\+?\s*"
    r"(?:years?|yrs?|yoe)\b",
    re.I,
)
_YOE_MIN = re.compile(
    r"(?P<a>\d+)\s*\+\s*(?:years?|yrs?|yoe)\b|"
    r"(?:at\s+least|minimum(?:\s+of)?|min\.?)\s*(?P<b>\d+)\s*(?:years?|yrs?|yoe)\b|"
    r"(?P<c>\d+)\s*(?:years?|yrs?|yoe)\s+(?:of\s+)?(?:experience|exp\.?)",
    re.I,
)

# Compensation
_LPA = re.compile(
    r"(?P<v>\d{1,3}(?:\.\d+)?)\s*(?:\+|–|-)?\s*(?:LPA|Lacs?\s*P\.?A\.?|Lakhs?\s*(?:per\s*annum)?)",
    re.I,
)
_INR_L = re.compile(
    r"(?:₹|INR|Rs\.?)\s*(?P<v>\d{1,3}(?:\.\d+)?)\s*(?:L|Lac|Lakh)s?",
    re.I,
)
_USD = re.compile(
    r"\$\s*(?P<v>\d{2,3}(?:,\d{3})?|\d{2,3}k)\b|"
    r"(?P<v2>\d{2,3})\s*k\s*(?:USD|\/\s*year|per\s*year)",
    re.I,
)

MIN_LPA = 30.0
MIN_USD = 40_000.0
SENIOR_YOE_LO = 2
SENIOR_YOE_HI = 5


@dataclass(frozen=True)
class RelevanceResult:
    ok: bool
    reason: str
    family: str = ""  # backend | ai | fullstack | swe_generic | ""


def _family(title: str, desc: str) -> str:
    blob = f"{title}\n{desc[:4000]}"
    if _ALLOW_AI.search(title) or _ALLOW_AI.search(blob):
        # Prefer title match for family label
        if _ALLOW_AI.search(title):
            return "ai"
        if _ALLOW_BACKEND.search(title):
            return "backend"
        if _ALLOW_FULLSTACK.search(title):
            return "fullstack"
        return "ai"
    if _ALLOW_FULLSTACK.search(title) or _ALLOW_FULLSTACK.search(blob):
        return "fullstack"
    if _ALLOW_BACKEND.search(title) or _ALLOW_BACKEND.search(blob):
        return "backend"
    if _GENERIC_SWE.search(title) and (
        _ALLOW_AI.search(blob) or _ALLOW_BACKEND.search(blob) or _ALLOW_FULLSTACK.search(blob)
    ):
        return "swe_generic"
    if _GENERIC_SWE.search(title):
        # Soft: generic SWE — allow through to LLM only if not pure-infra title
        return "swe_generic"
    return ""


def _yoe_bands(desc: str) -> list[tuple[int, int]]:
    """Return list of (min_yoe, max_yoe) bands found in description."""
    bands: list[tuple[int, int]] = []
    for m in _YOE_RANGE.finditer(desc):
        a, b = int(m.group("a")), int(m.group("b"))
        lo, hi = min(a, b), max(a, b)
        bands.append((lo, hi))
    for m in _YOE_MIN.finditer(desc):
        v = m.group("a") or m.group("b") or m.group("c")
        if v is None:
            continue
        n = int(v)
        # "3+ years" → (3, 99); "3 years experience" → (2, 4) soft band
        if m.group("a") or m.group("b"):
            bands.append((n, 99))
        else:
            bands.append((max(1, n - 1), n + 2))
    return bands


def _senior_yoe_ok(desc: str) -> tuple[bool, str]:
    """Senior titles need a YOE band overlapping 2–5."""
    bands = _yoe_bands(desc or "")
    if not bands:
        return False, "Senior title but JD has no 2–5 YOE signal"
    for lo, hi in bands:
        # Overlap with [2, 5]
        if lo <= SENIOR_YOE_HI and hi >= SENIOR_YOE_LO:
            # Reject if minimum required is clearly 6+
            if lo >= 6:
                continue
            return True, f"YOE band {lo}-{hi} overlaps 2–5"
    return False, f"Senior title; YOE bands {bands} do not overlap 2–5 (or require 6+)"


def _comp_ok(desc: str) -> tuple[bool, str]:
    """If pay is stated below floor, reject. Unstated → OK."""
    text = desc or ""
    lpas: list[float] = []
    for m in _LPA.finditer(text):
        lpas.append(float(m.group("v")))
    for m in _INR_L.finditer(text):
        lpas.append(float(m.group("v")))
    usds: list[float] = []
    for m in _USD.finditer(text):
        raw = m.group("v") or m.group("v2") or ""
        raw = raw.replace(",", "").lower()
        if raw.endswith("k"):
            usds.append(float(raw[:-1]) * 1000)
        else:
            v = float(raw)
            # Heuristic: 40–200 without k is likely thousands if small
            if v < 1000:
                usds.append(v * 1000)
            else:
                usds.append(v)

    if lpas:
        # Use max stated if range; reject only if the high end is still below floor
        # or a single value is below floor
        top = max(lpas)
        if top < MIN_LPA:
            return False, f"Comp stated ~{top} LPA (< {MIN_LPA} LPA floor)"
    if usds:
        top = max(usds)
        if top < MIN_USD:
            return False, f"Comp stated ~${int(top):,} (< ${int(MIN_USD):,} floor)"
    return True, "comp ok or unstated"


def evaluate_relevance(job: dict) -> RelevanceResult:
    """Return whether ``job`` is relevant for Harsh's target profile."""
    title = (job.get("title") or "").strip()
    desc = (job.get("full_description") or job.get("description") or "")[:12000]

    if not title:
        return RelevanceResult(False, "missing title", "")

    if _HARD_SENIORITY_BLOCK.search(title):
        return RelevanceResult(
            False, f"blocked seniority/level in title: {title}", ""
        )

    family = _family(title, desc)

    # Pure infra title without allow-family → drop
    if _PURE_INFRA_BLOCK.search(title) and family not in ("ai", "backend", "fullstack"):
        return RelevanceResult(
            False, f"pure infra/SRE/storage title without AI/backend/fullstack: {title}", ""
        )

    if not family:
        return RelevanceResult(
            False,
            f"title not in allow families (backend/AI/fullstack): {title}",
            "",
        )

    # Generic SWE with no AI/backend/fullstack signal in title or desc → drop
    if family == "swe_generic":
        blob = f"{title}\n{desc[:4000]}"
        if not (
            _ALLOW_AI.search(blob)
            or _ALLOW_BACKEND.search(blob)
            or _ALLOW_FULLSTACK.search(blob)
        ):
            # Still allow plain "Software Engineer" mid-level through to LLM
            # only when not infra-tagged — keep but flag family
            if _PURE_INFRA_BLOCK.search(title):
                return RelevanceResult(
                    False, f"generic SWE + infra title blocked: {title}", ""
                )

    if _SENIOR_TITLE.search(title):
        ok, why = _senior_yoe_ok(desc)
        if not ok:
            return RelevanceResult(False, why, family)

    ok_c, why_c = _comp_ok(desc)
    if not ok_c:
        return RelevanceResult(False, why_c, family)

    return RelevanceResult(True, f"allowed family={family}", family)
