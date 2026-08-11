"""Job fit scoring: LLM-powered evaluation of candidate-job match quality.

Scores jobs on a 1-10 scale by comparing the user's resume against each
job description. All personal data is loaded at runtime from the user's
profile and resume file.
"""

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from applypilot.config import RESUME_PATH, load_profile
from applypilot.database import get_connection, get_jobs_by_stage, write_with_retry
from applypilot.llm import get_client

log = logging.getLogger(__name__)


# ── Scoring Prompt ────────────────────────────────────────────────────────

SCORE_PROMPT_TEMPLATE = """You are a job fit evaluator for Harsh Rajput.

THE CANDIDATE: {candidate_summary}

PROFILE CONSTRAINTS (hard):
- ~3 years of experience (mid-level IC). NOT Staff/Principal/Director.
- Target domains ONLY: Backend/API, Applied AI / LLM / RAG / Agents, Full-stack React/Next.js + backend.
- Compensation floor when stated: ≥30 LPA INR TC (~$40k USD). Below floor → low score.
- Geography: India-based; open to India office/remote, global remote, and US-transfer roles that accept sponsorship. EU/UK-only / Canada-only roles are INELIGIBLE (non_us_only is the tag used historically — treat as ineligible geo).

GEOGRAPHY CHECK — DO THIS FIRST:
Output ELIGIBILITY: non_us_only when the role is restricted to EU-only, UK-only, Canada-only, Germany-only, Australia-only with NO India/worldwide/US option.
Output ELIGIBILITY: eligible for India, India-remote, global remote, US remote/transfer, or unrestricted.

SCORING CRITERIA (Harsh-specific):
- 10: Excellent mid-level match. Backend/API or Applied AI/Agents or Full-stack React/Next+backend; stack overlap (Go/Python/TS, FastAPI, React/Next, RAG/LLM); YOE ~2-5; comp ≥30 LPA when stated.
- 8-9: Strong match. Allowed domain, good stack overlap, seniority OK (Senior only if JD YOE overlaps 2-5). Minor gaps OK.
- 6-7: Partial match. Allowed domain but weak stack overlap, OR generic Software Engineer with thin AI/backend signal.
- 3-5: Weak. Pure SRE / Infra / Storage / Observability / DevOps without AI/backend/fullstack focus; OR Senior with YOE requiring 6+; OR primary language Rust/C++/Ruby with no transfer path; OR frontend-only with no backend.
- 1-2: Poor / wrong career track. Non-engineering, Staff+/Director, Intern, or geo-ineligible.

HARD CAPS:
- Pure infra/SRE/storage/observability roles → SCORE ≤ 3
- Roles requiring 6+ YOE (or Staff/Principal) → SCORE ≤ 4
- Comp explicitly below 30 LPA / $40k → SCORE ≤ 3
- Frontend-only (no backend) → SCORE ≤ 4
- Allowed backend/AI/fullstack mid-level → prefer 8–10

ADDITIONAL RULES:
- Distinguish REQUIRED vs NICE-TO-HAVE skills.
- Value transferable: APIs, distributed systems, LLM apps, RAG, React/Next fullstack.
- LOCATION N/A: prefer India / remote / US-transfer; do not over-penalize missing city.

You MUST include all four lines below. Do not skip REASONING.

ELIGIBILITY: [eligible|non_us_only]
SCORE: [1-10]
KEYWORDS: [comma-separated ATS keywords from the job that match the candidate]
REASONING: [2-3 sentences: domain fit, YOE fit, stack gaps, comp if stated.]"""


# ── Rule-based pre-filter (catches obvious ineligible before LLM call) ─────
#
# Patterns validated 2026-04-23 against 5,938 historical scored jobs.
# Any pattern that would reject more than 1-2 jobs scored >=8 is omitted
# (those rare false positives tend to be LLM mis-scores anyway — jobs
# titled "Junior" / "Intern" don't belong in a Senior/Staff queue).

# Patterns that make a job ineligible regardless of tech stack.
# Checked against title + location field only (not full description, to avoid
# false positives from US companies mentioning global offices).
_INELIGIBLE_TITLE_PATTERNS = re.compile(
    # Explicit non-US regions in title
    r'\bEMEA\b'
    r'|\bAPAC\b'
    r'|\bLATAM\b'
    r'|\bMENA\b'
    r'|\bTOLA\b'                    # sales region: Texas/Oklahoma/Louisiana/Arkansas
    r'|\bANZ\b'                     # Australia/New Zealand
    r'|\bNordics\b'
    r'|\bEU[- ]only\b'
    r'|\bUK[- ]only\b'
    r'|\bEurope[- ]only\b'
    r'|\(m/[fw]/d\)'                # German job title suffix (m/f/d) or (m/w/d)
    r'|\bm/[fw]/d\b'
    r'|\bOnly hiring in\b'
    # Seniority mismatches (user is Senior/Staff/Principal level)
    r'|\bJunior\b'
    r'|\bIntern(ship)?\b'
    r'|\bFresher\b'
    r'|\bEntry[- ]?Level\b'
    r'|\bNew[- ]Grad\b'
    r'|\bTrainee\b'
    r'|\bApprentice\b'
    # Sales-adjacency (not IC engineering)
    r'|\bSales Engineer\b'
    r'|\bSolutions Engineer\b'
    r'|\bPre[- ]?[Ss]ales\b'
    r'|\bCustomer Success Engineer\b'
    # Retail / warehouse / service roles (filter out Costco + similar noise)
    r'|\bCashier\b|\bBaker\b|\bCake Decorator\b|\bButcher\b|\bMeat Cutter\b'
    r'|\bGas Station Attendant\b|\bPharmacy Technician\b|\bHearing Aid Dispenser\b'
    r'|\bStocker\b|\bForklift\b|\bWarehouse Associate\b|\bTruck Driver\b'
    r'|\bBakery Clerk\b|\bDeli Clerk\b|\bProduce Clerk\b|\bMember Service\b'
    r'|\bOptician\b|\bOptical\b'
    # More seniority — "Graduate Developer"/"Graduate Software Engineer" patterns
    # Protected: "Graduate School", "Graduate Student" (those don't appear in job titles)
    r'|\bGraduate\b'
    # Non-engineering roles
    r'|\bRecruiter\b'
    r'|\bTalent Acquisition\b|\bTalent Scout\b|\bTalent Sourcer\b'
    r'|\bAccount Manager\b|\bAccount Executive\b'
    r'|\bUX Designer\b|\bUI Designer\b|\bProduct Designer\b|\bGraphic Designer\b'
    # Specialist IC roles outside the target stack (mobile, legacy enterprise)
    r'|\bAndroid Engineer\b|\biOS Engineer\b|\bMobile Engineer\b'
    r'|\bSalesforce Developer\b|\bApex Developer\b'
    r'|\bMainframe Engineer\b|\bCOBOL Developer\b|\bTIBCO\b',
    re.IGNORECASE,
)

# Patterns checked against the location field specifically.
# Harsh is India-based: India / Bangalore / remote-IN are eligible.
# Mark EU/UK/Canada/ANZ/LATAM/MEA (and non-India Asia) as geo-ineligible.
_INELIGIBLE_LOCATION_PATTERNS = re.compile(
    # Regions (APAC alone is ambiguous for India — keep as soft signal via title)
    r'\bEMEA\b'
    r'|\bEurope\b'
    # Europe / UK / Ireland
    r'|\bGermany\b|\bNetherlands\b|\bFrance\b|\bSpain\b|\bItaly\b'
    r'|\bPoland\b|\bUkraine\b|\bCzech\b|\bPortugal\b|\bIreland\b'
    r'|\bDenmark\b|\bSweden\b|\bNorway\b|\bFinland\b|\bBelgium\b'
    r'|\bSwitzerland\b|\bAustria\b|\bRomania\b|\bHungary\b|\bCroatia\b'
    r'|\bGreece\b|\bBulgaria\b|\bSerbia\b|\bSlovakia\b|\bSlovenia\b'
    r'|\bEstonia\b|\bLatvia\b|\bLithuania\b'
    r'|\bUnited\s+Kingdom\b|\bEngland\b|\bScotland\b|\bWales\b'
    r'|\bLondon\b|\bBerlin\b|\bAmsterdam\b|\bDublin\b|\bParis\b'
    # Non-India Asia
    r'|\bSingapore\b|\bJapan\b|\bVietnam\b|\bThailand\b'
    r'|\bPhilippines\b|\bIndonesia\b|\bKorea\b|\bTaiwan\b|\bHong Kong\b'
    r'|\bChina\b|\bPakistan\b|\bBangladesh\b|\bMalaysia\b'
    # Latin America
    r'|\bBrazil\b|\bBrasil\b|\bMexico\b|\bMéxico\b|\bArgentina\b'
    r'|\bChile\b|\bColombia\b|\bPeru\b|\bUruguay\b'
    # Middle East / Africa / Canada
    r'|\bEgypt\b|\bNigeria\b|\bKenya\b|\bSouth Africa\b|\bIsrael\b'
    r'|\bTurkey\b|\bTürkiye\b|\bUAE\b|\bSaudi Arabia\b'
    r'|\bCanada\b|\bToronto\b|\bVancouver\b|\bMontreal\b'
    # Oceania
    r'|\bAustralia\b|\bNew Zealand\b|\bSydney\b|\bMelbourne\b',
    re.IGNORECASE,
)

# Description-level geo restrictions. India-based / IST / Bangalore OK for Harsh.
# Only flag when JD explicitly restricts to EU/UK/Canada/ANZ (no India/US/world option).
_INELIGIBLE_DESC_PATTERNS = re.compile(
    r'Remote\s*[\(\-—–]\s*(EMEA|Europe|EU|UK|United\s+Kingdom|Germany|Canada|Ireland|Netherlands|Brazil|Mexico|Argentina|Colombia|Australia|New\s+Zealand)'
    r'|EMEA\s*(only|region|remote|based)'
    r'|(Europe|European)\s*(only|Time\s*Zone|timezone|based|remote)'
    r'|based\s+in\s+(the\s+)?(Europe|EU|UK|United\s+Kingdom|Germany|Netherlands|Canada|Ireland|France|Spain|Italy|Brazil|Mexico|Australia|New\s+Zealand|Singapore|Japan|Israel|South\s+Africa|Portugal|Poland|Romania)'
    r'|will\s+be\s+remote\s+and\s+based\s+in\s+(the\s+)?(UK|United\s+Kingdom|Canada|Ireland|Germany|Europe|EMEA)'
    r'|Remote\s+(in|from|—|-)\s*(Ontario|British\s+Columbia|Alberta|Quebec|Manitoba|Nova\s+Scotia|Saskatchewan)'
    r'|Ontario,\s*British\s+Columbia'
    r"|right\s+to\s+work\s+in\s+(the\s+)?(UK|United\s+Kingdom|Canada|Ireland|EU|European\s+Union)"
    r"|requires?\s+(the\s+)?right\s+to\s+work\s+in\s+(the\s+)?(UK|United\s+Kingdom|Canada|Ireland|EU)"
    r'|CET\s+timezone'
    r'|GMT[+\-]\d+\s+timezone',
    re.IGNORECASE,
)

# Window scanned for description-level patterns. Bumped from 800 to 6000 chars
# 2026-04-30 — Twilio buried the UK restriction in a paragraph below the
# requirements list, past the 800-char head.
_DESC_SCAN_CHARS = 6000


def _check_ineligible(job: dict) -> str | None:
    """Return an ineligibility reason if the job is geo/title-ineligible for Harsh.

    India / Bangalore / IST / global remote / US-transfer are eligible.
    EU/UK/Canada/ANZ-only (and similar) are ineligible. Checked before the
    LLM call to save tokens. Scans title, location, and description head.
    """
    title = job.get("title") or ""
    location = job.get("location") or ""
    desc_head = (job.get("full_description") or "")[:_DESC_SCAN_CHARS]

    if _INELIGIBLE_TITLE_PATTERNS.search(title):
        return f"non-US geography in title: {title}"
    if location and _INELIGIBLE_LOCATION_PATTERNS.search(location):
        return f"non-US location field: {location}"
    m = _INELIGIBLE_DESC_PATTERNS.search(desc_head)
    if m:
        return f"non-US geography in description: {m.group(0)[:80]}"
    return None


def _parse_score_response(response: str) -> dict:
    """Parse the LLM's score response into structured data.

    Args:
        response: Raw LLM response text.

    Returns:
        {"score": int, "keywords": str, "reasoning": str, "eligibility": str}
        eligibility is one of: 'eligible' | 'non_us_only'.
        Older models that omit ELIGIBILITY default to 'eligible' (preserves
        prior behavior; new prompt requires the line so absence is rare).
    """
    score = 0
    keywords = ""
    reasoning = response
    eligibility = "eligible"

    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("ELIGIBILITY:"):
            value = line.replace("ELIGIBILITY:", "").strip().lower()
            value = re.sub(r"[\[\]\s]+", "_", value).strip("_")
            if "non" in value and "us" in value:
                eligibility = "non_us_only"
            else:
                eligibility = "eligible"
        elif line.startswith("SCORE:"):
            try:
                score = int(re.search(r"\d+", line).group())
                score = max(1, min(10, score))
            except (AttributeError, ValueError):
                score = 0
        elif line.startswith("KEYWORDS:"):
            keywords = line.replace("KEYWORDS:", "").strip()
        elif line.startswith("REASONING:"):
            reasoning = line.replace("REASONING:", "").strip()

    return {"score": score, "keywords": keywords, "reasoning": reasoning,
            "eligibility": eligibility}


def _build_candidate_summary(profile: dict) -> str:
    """Build a candidate summary string from profile for the scoring prompt."""
    exp = profile.get("experience", {})
    boundary = profile.get("skills_boundary", {})
    comp = profile.get("compensation", {})
    years = exp.get("years_of_experience_total", "3")
    current_title = exp.get("current_job_title", "Software Engineer")
    target = exp.get(
        "target_role",
        "backend engineer / applied AI engineer / fullstack React+Next engineer",
    )
    languages = boundary.get("languages", [])
    frameworks = boundary.get("frameworks", [])
    tools = boundary.get("tools", [])
    platforms = boundary.get("platforms", [])
    min_lpa = comp.get("salary_range_min_inr_lpa") or "30"
    parts = [
        f"{current_title} with {years} years experience (mid-level IC, not Staff/Principal).",
        "Domains: Backend/API, Applied AI/LLM/RAG/Agents, Full-stack React/Next.js + backend.",
    ]
    if languages:
        parts.append(f"Languages: {', '.join(languages[:8])}.")
    if frameworks:
        parts.append(f"Frameworks: {', '.join(frameworks[:8])}.")
    if tools:
        parts.append(f"AI/tools: {', '.join(tools[:6])}.")
    if platforms:
        parts.append(f"Platforms: {', '.join(platforms[:6])}.")
    parts.append(f"Targets: {target}.")
    parts.append(f"Comp floor: ≥{min_lpa} LPA INR (~$40k USD) when stated.")
    return " ".join(parts)


def score_job(resume_text: str, job: dict, profile: dict | None = None) -> dict:
    """Score a single job against the resume.

    Args:
        resume_text: The candidate's full resume text.
        job: Job dict with keys: title, site, location, full_description.

    Returns:
        {"score": int, "keywords": str, "reasoning": str}
    """
    if profile is None:
        profile = load_profile()

    # Harsh relevance pre-filter (role family / Senior YOE / comp floor)
    from applypilot.scoring.relevance import evaluate_relevance
    rel = evaluate_relevance(job)
    if not rel.ok:
        log.info(
            "Pre-filter IRRELEVANT: %s — %s",
            (job.get("title") or "?")[:60], rel.reason,
        )
        return {
            "score": 2,
            "keywords": "",
            "reasoning": f"Irrelevant for target profile: {rel.reason}",
            "eligibility": "eligible",  # geo-ok but low_score path
        }

    # Rule-based pre-filter: catch obvious non-US ineligible jobs before LLM call.
    # Tags eligibility=non_us_only so downstream stages skip the job; the score
    # is still recorded so audit views can see the original LLM-style severity.
    ineligible_reason = _check_ineligible(job)
    if ineligible_reason:
        log.info("Pre-filter INELIGIBLE (non_us_only): %s — %s", (job.get("title") or "?")[:60], ineligible_reason)
        return {
            "score": 2,
            "keywords": "",
            "reasoning": f"Ineligible: {ineligible_reason}. Candidate is US-based.",
            "eligibility": "non_us_only",
        }

    try:
        candidate_summary = _build_candidate_summary(profile)
        score_prompt = SCORE_PROMPT_TEMPLATE.format(candidate_summary=candidate_summary)

        job_text = (
            f"TITLE: {job['title']}\n"
            f"COMPANY: {job['site']}\n"
            f"LOCATION: {job.get('location', 'N/A')}\n\n"
            f"DESCRIPTION:\n{(job.get('full_description') or '')[:6000]}"
        )

        messages = [
            {"role": "system", "content": score_prompt},
            {"role": "user", "content": f"RESUME:\n{resume_text}\n\n---\n\nJOB POSTING:\n{job_text}"},
        ]

        client = get_client()
        response = client.chat(messages, max_tokens=8192, temperature=0.2)
        return _parse_score_response(response)
    except Exception as e:
        log.error("LLM error scoring job '%s': %s", (job or {}).get("title") or "?", e)
        return {"score": None, "keywords": "", "reasoning": "", "eligibility": None,
                "error": f"LLM error: {e}"}


MAX_SCORE_RETRIES = 5


def _score_backoff_minutes(retry_count: int) -> int:
    """Exponential backoff for scoring retries: 5, 20, 80, ~5h, ~21h."""
    return min(5 * (4 ** retry_count), 24 * 60)


def _flush_score_batch(conn, batch: list[dict], now: str) -> None:
    """Write a batch of scoring results to the DB.

    On success (score is not None): writes fit_score, clears score_error.
    On failure (score is None): leaves fit_score NULL, writes score_error + backoff.
    Jobs that have already hit MAX_SCORE_RETRIES stay unscored indefinitely (manual rescue needed).
    """
    from applypilot.database import transition_state
    from applypilot.config import DEFAULTS as _cfg_DEFAULTS
    _min_score = _cfg_DEFAULTS["min_score"]

    for r in batch:
        if r["score"] is not None:
            eligibility = r.get("eligibility") or "eligible"
            conn.execute(
                "UPDATE jobs SET fit_score = ?, score_reasoning = ?, scored_at = ?, "
                "eligibility = ?, "
                "score_error = NULL, score_attempts = 0, score_next_retry_at = NULL "
                "WHERE url = ?",
                (r["score"], f"{r['keywords']}\n{r['reasoning']}", now, eligibility,
                 r["url"]),
            )
            # Eligibility-driven state transition. Non-US roles go straight to
            # `archived` (terminal) so tailor/cover/apply never pick them up,
            # bypassing the scored→tailored→ready_to_apply chain entirely.
            if eligibility == "non_us_only":
                transition_state(conn, r["url"], "archived",
                                 reason="non_us_only employer/role",
                                 metadata={"score": r["score"],
                                           "eligibility": eligibility},
                                 force=True)
            else:
                to_state = "scored" if r["score"] >= _min_score else "low_score"
                transition_state(conn, r["url"], to_state,
                                 reason=f"scored {r['score']}/10",
                                 metadata={"score": r["score"],
                                           "eligibility": eligibility})
        else:
            # LLM failure — keep fit_score NULL so it stays in pending_score
            row = conn.execute(
                "SELECT COALESCE(score_attempts, 0) FROM jobs WHERE url = ?", (r["url"],)
            ).fetchone()
            retry_count = row[0] if row else 0
            if retry_count >= MAX_SCORE_RETRIES:
                # Give up — write score_error but don't schedule another retry
                conn.execute(
                    "UPDATE jobs SET score_error = ?, score_attempts = ?, "
                    "score_next_retry_at = NULL, scored_at = ? WHERE url = ?",
                    (r["error"], retry_count + 1, now, r["url"]),
                )
                transition_state(conn, r["url"], "score_failed",
                                 reason=f"LLM failed after {retry_count+1} attempts",
                                 metadata={"error": r["error"]})
            else:
                delay = _score_backoff_minutes(retry_count)
                next_retry = (
                    datetime.now(timezone.utc) + timedelta(minutes=delay)
                ).isoformat()
                conn.execute(
                    "UPDATE jobs SET score_error = ?, score_attempts = ?, "
                    "score_next_retry_at = ?, scored_at = ? WHERE url = ?",
                    (r["error"], retry_count + 1, next_retry, now, r["url"]),
                )
                log.info("  score retry %d/%d scheduled in %d min for %s",
                         retry_count + 1, MAX_SCORE_RETRIES, delay, r["url"][:60])


def run_scoring(limit: int = 0, rescore: bool = False, workers: int = 1,
                max_age_days: int | None = None) -> dict:
    """Score unscored jobs that have full descriptions.

    Args:
        limit: Maximum number of jobs to score in this run.
        rescore: If True, re-score all jobs (not just unscored ones).
        workers: Parallel LLM threads (default 1 = sequential).

    Returns:
        {"scored": int, "errors": int, "elapsed": float, "distribution": list}
    """
    resume_text = RESUME_PATH.read_text(encoding="utf-8")
    conn = get_connection()

    if rescore:
        query = "SELECT * FROM jobs WHERE full_description IS NOT NULL"
        if limit > 0:
            query += f" LIMIT {limit}"
        jobs = conn.execute(query).fetchall()
    else:
        # Note: get_jobs_by_stage now applies a 14-day discovered_at filter by
        # default (config.DEFAULTS["max_job_age_days"]). Pass max_age_days=0
        # to disable.
        jobs = get_jobs_by_stage(conn=conn, stage="pending_score",
                                 max_age_days=max_age_days, limit=limit)

    if not jobs:
        log.info("No unscored jobs with descriptions found.")
        return {"scored": 0, "errors": 0, "elapsed": 0.0, "distribution": []}

    # Convert sqlite3.Row to dicts if needed
    if jobs and not isinstance(jobs[0], dict):
        columns = jobs[0].keys()
        jobs = [dict(zip(columns, row)) for row in jobs]

    log.info("Scoring %d jobs (workers=%d)...", len(jobs), workers)
    t0 = time.time()
    completed = 0
    errors = 0
    batch_size = 25  # Commit every N jobs so downstream stages see results sooner
    batch: list[dict] = []

    def _score_one(job: dict) -> dict:
        try:
            result = score_job(resume_text, job)
            result["url"] = job["url"]
        except Exception as e:
            log.error("Unexpected error scoring '%s': %s", (job or {}).get("title") or "?", e)
            result = {
                "score": None, "keywords": "", "reasoning": "",
                "error": f"Unexpected: {e}", "url": (job or {}).get("url", ""),
            }
        return result

    def _flush_and_log(batch: list[dict], completed: int) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        try:
            write_with_retry(conn, _flush_score_batch, conn, batch, now)
        except Exception as flush_err:
            log.exception("Batch flush failed (batch of %d): %s", len(batch), flush_err)
        log.info("Committed batch of %d scores to DB (%d/%d total)", len(batch), completed, len(jobs))
        return []

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_score_one, job): job for job in jobs}
            for future in as_completed(futures):
                job = futures[future]
                result = future.result()
                completed += 1
                if result["score"] is None:
                    errors += 1
                batch.append(result)
                log.info(
                    "[%d/%d] score=%s  %s",
                    completed, len(jobs),
                    result["score"] if result["score"] is not None else "ERR",
                    (job.get("title") or "")[:60],
                )
                if len(batch) >= batch_size:
                    batch = _flush_and_log(batch, completed)
    else:
        for job in jobs:
            result = _score_one(job)
            completed += 1
            if result["score"] is None:
                errors += 1
            batch.append(result)
            log.info(
                "[%d/%d] score=%s  %s",
                completed, len(jobs),
                result["score"] if result["score"] is not None else "ERR",
                (job.get("title") or "")[:60],
            )
            if len(batch) >= batch_size:
                batch = _flush_and_log(batch, completed)

    # Flush remaining
    if batch:
        now = datetime.now(timezone.utc).isoformat()
        try:
            write_with_retry(conn, _flush_score_batch, conn, batch, now)
        except Exception as flush_err:
            log.exception("Final batch flush failed (batch of %d): %s", len(batch), flush_err)

    elapsed = time.time() - t0
    log.info("Done: %d scored in %.1fs (%.1f jobs/sec)", completed, elapsed, completed / elapsed if elapsed > 0 else 0)

    # Score distribution
    try:
        dist = conn.execute("""
            SELECT fit_score, COUNT(*) FROM jobs
            WHERE fit_score IS NOT NULL
            GROUP BY fit_score ORDER BY fit_score DESC
        """).fetchall()
        distribution = [(row[0], row[1]) for row in dist]
    except Exception as dist_err:
        log.exception("Distribution query failed: %s", dist_err)
        distribution = []

    return {
        "scored": completed,
        "errors": errors,
        "elapsed": elapsed,
        "distribution": distribution,
    }
