#!/usr/bin/env python3
"""Refilter Harsh ApplyPilot queue with relevance gate.

Clears inflated seed scores / tailored packs for non-applied jobs that fail
the Harsh relevance policy (backend/AI/fullstack, soft Senior 2–5 YOE, 30 LPA).

Usage:
  python scripts/refilter_harsh_queue.py --dry-run
  python scripts/refilter_harsh_queue.py
  python scripts/refilter_harsh_queue.py --rescore   # also null fit_score on keepers for LLM rescoring
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print actions only")
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Also clear fit_score on kept non-applied jobs so LLM rescoring is required",
    )
    parser.add_argument("--min-score", type=int, default=8)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "src"))
    from applypilot.database import get_connection, init_db, transition_state
    from applypilot.scoring.relevance import evaluate_relevance

    init_db()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT url, title, company, site, fit_score, full_description, description,
               tailored_resume_path, cover_letter_path, apply_status, applied_at, state
        FROM jobs
        """
    ).fetchall()

    drop = []
    keep = []
    skip_applied = 0
    by_reason: Counter[str] = Counter()
    by_family: Counter[str] = Counter()

    for r in rows:
        job = dict(r)
        if job.get("applied_at") or (job.get("apply_status") or "") == "applied":
            skip_applied += 1
            continue
        rel = evaluate_relevance(job)
        if rel.ok:
            keep.append((job, rel))
            by_family[rel.family or "?"] += 1
        else:
            drop.append((job, rel))
            # Truncate reason key for grouping
            key = rel.reason.split(":")[0][:60]
            by_reason[key] += 1

    print(f"jobs={len(rows)} applied_skipped={skip_applied} keep={len(keep)} drop={len(drop)}")
    print("\n--- drop reasons ---")
    for k, n in by_reason.most_common(20):
        print(f"  {n:3d}  {k}")
    print("\n--- keep families ---")
    for k, n in by_family.most_common():
        print(f"  {n:3d}  {k}")

    print("\n--- sample drops ---")
    for job, rel in drop[:25]:
        print(f"  DROP  {(job.get('company') or '?')[:20]:20} | {(job.get('title') or '')[:50]:50} | {rel.reason[:70]}")
    print("\n--- sample keeps ---")
    for job, rel in keep[:25]:
        print(f"  KEEP  {(job.get('company') or '?')[:20]:20} | {(job.get('title') or '')[:50]:50} | {rel.family}")

    if args.dry_run:
        print("\n(dry-run — no DB writes)")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    dropped_n = 0
    for job, rel in drop:
        url = job["url"]
        conn.execute(
            """
            UPDATE jobs SET
              fit_score = 2,
              score_reasoning = ?,
              scored_at = ?,
              tailored_resume_path = NULL,
              cover_letter_path = NULL,
              apply_status = CASE
                WHEN apply_status = 'failed' THEN apply_status
                ELSE NULL
              END
            WHERE url = ? AND applied_at IS NULL
            """,
            (f"relevance:{rel.reason}", now, url),
        )
        try:
            transition_state(
                conn, url, "low_score",
                reason=f"relevance:{rel.reason[:80]}",
                force=True,
            )
        except Exception:
            pass
        dropped_n += 1

    rescored_n = 0
    if args.rescore:
        for job, rel in keep:
            url = job["url"]
            conn.execute(
                """
                UPDATE jobs SET
                  fit_score = NULL,
                  score_reasoning = NULL,
                  scored_at = NULL,
                  tailored_resume_path = NULL,
                  cover_letter_path = NULL
                WHERE url = ? AND applied_at IS NULL
                """,
                (url,),
            )
            rescored_n += 1

    conn.commit()
    print(f"\nwrote: dropped={dropped_n} cleared_for_rescore={rescored_n}")
    print(f"Next: applypilot run score --min-score {args.min_score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
