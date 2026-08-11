#!/usr/bin/env python3
"""Seed ApplyPilot DB from Harsh's curated day1 / job_pool queues + master CSV dedupe.

Usage (from ApplyPilot repo, venv active):
  python scripts/seed_harsh_queue.py
  python scripts/seed_harsh_queue.py --pool   # also import job_pool.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARSH = ROOT / "config" / "harsh"
LISTS = HARSH / "lists"


def _infer_track(job: dict) -> str:
    if job.get("india"):
        return "india"
    loc = (job.get("location") or job.get("mode") or "").lower()
    if any(x in loc for x in ("india", "bangalore", "bengaluru", "delhi", "hyderabad")):
        return "india"
    if "remote" in loc and "us" not in loc:
        return "remote_35lpa"
    if any(x in loc for x in ("united states", "usa", "remote-us", "us remote")):
        return "us_transfer"
    if job.get("remote"):
        return "remote_35lpa"
    return "india"


def load_queue(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    jobs = data["jobs"] if isinstance(data, dict) else data
    return list(jobs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", action="store_true", help="Also import job_pool.json")
    parser.add_argument("--min-fit", type=int, default=8,
                        help="Unused for scoring (seeds leave fit_score NULL); kept for CLI compat")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "src"))
    from applypilot.database import get_connection, init_db, store_jobs
    from applypilot.discovery.url_normalize import canonicalize_application_url

    init_db()
    conn = get_connection()

    paths = [LISTS / "day1_queue.json"]
    if args.pool:
        paths.append(LISTS / "job_pool.json")

    all_jobs: list[dict] = []
    for p in paths:
        if not p.exists():
            print(f"skip missing {p}")
            continue
        all_jobs.extend(load_queue(p))
        print(f"loaded {p.name}: {len(load_queue(p))} jobs")

    # Dedupe by apply URL
    seen: set[str] = set()
    normalized: list[dict] = []
    for j in all_jobs:
        url = j.get("apply_url") or j.get("url") or ""
        if not url:
            continue
        url = canonicalize_application_url(url)
        if url in seen:
            continue
        seen.add(url)
        track = _infer_track(j)
        # Do NOT inflate fit_score from curated list scores — leave unscored
        # so enrich → relevance → LLM score must pass before apply.
        company = j.get("company") or ""
        normalized.append(
            {
                "url": url,
                "title": j.get("title") or "",
                "salary": j.get("salary"),
                "description": j.get("description")
                or f"{j.get('title')} at {company}. Location: {j.get('location')}. Track: {track}.",
                "location": j.get("location") or "",
                "company": company,
                "track": track,
                "india": bool(j.get("india")),
                "application_url": url,
            }
        )

    new, dup = store_jobs(conn, normalized, site="harsh_queue", strategy="seed_json")
    print(f"store_jobs: new={new} dup={dup}")

    # Enrich seed rows: application_url / company / description only — no fit_score
    now = datetime.now(timezone.utc).isoformat()
    for j in normalized:
        url = j["url"]
        conn.execute(
            """
            UPDATE jobs SET
              application_url = COALESCE(application_url, ?),
              company = COALESCE(NULLIF(company, ''), ?),
              full_description = COALESCE(full_description, ?),
              detail_scraped_at = COALESCE(detail_scraped_at, ?)
            WHERE url = ?
            """,
            (
                j["application_url"],
                j["company"],
                j["description"],
                now,
                url,
            ),
        )
    conn.commit()

    # Mark master_applications.csv attempts so we don't re-blast
    master = HARSH / "master_applications.csv"
    if master.exists():
        marked = 0
        with master.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                status = (row.get("Status") or "").strip().lower()
                url = (row.get("JobURL") or "").strip()
                if not url:
                    continue
                url = canonicalize_application_url(url)
                if status in ("submitted", "applied"):
                    conn.execute(
                        "UPDATE jobs SET apply_status = 'applied', applied_at = COALESCE(applied_at, ?) WHERE url = ? OR application_url = ?",
                        (now, url, url),
                    )
                    marked += 1
                elif status in ("paused_user", "blocked_batch", "still_blocked", "ready_to_submit"):
                    # leave as applyable but note prior attempt
                    conn.execute(
                        "UPDATE jobs SET apply_error = COALESCE(apply_error, ?) WHERE url = ? OR application_url = ?",
                        (f"prior:{status}", url, url),
                    )
        conn.commit()
        print(f"master CSV reconciled rows touched≈{marked}")

    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    scored = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE fit_score >= ?", (args.min_fit,)
    ).fetchone()[0]
    print(f"DB totals: jobs={total} fit>={args.min_fit}={scored}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
