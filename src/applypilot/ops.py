"""Shared operator actions used by CLI and the HTTP control plane.

Thin wrappers around existing launcher/database/chrome helpers so both
surfaces stay in sync without duplicating business logic.
"""

from __future__ import annotations

from typing import Any


def mark_job_applied(url: str) -> None:
    from applypilot.apply.launcher import mark_job

    mark_job(url, "applied")


def mark_job_failed(url: str, reason: str | None = None) -> None:
    from applypilot.apply.launcher import mark_job

    mark_job(url, "failed", reason=reason)


def reset_failed_jobs() -> int:
    from applypilot.apply.launcher import reset_failed

    return reset_failed()


def reset_jobs_by_category(category: str) -> int:
    from applypilot.database import reset_by_category

    return reset_by_category(category)


def list_ats_sessions() -> list[dict[str, Any]]:
    from applypilot.apply.chrome import list_ats_sessions as _list

    return _list()


def clear_ats_session(slug: str) -> bool:
    from applypilot.apply.chrome import clear_ats_session as _clear

    return _clear(slug)


def resolve_hitl(url: str, action: str = "done") -> dict[str, Any]:
    """Clear needs_human parking so the job can be retried on next apply.

    action:
      - done: clear HITL fields and set apply_status back to failed/pending for retry
      - skip: archive as manual_only
    """
    from applypilot.database import get_connection, transition_state, commit_with_retry

    conn = get_connection()
    row = conn.execute(
        "SELECT url, apply_status, state FROM jobs WHERE url = ?", (url,)
    ).fetchone()
    if not row:
        raise ValueError(f"Job not found: {url}")

    if action == "skip":
        conn.execute(
            """UPDATE jobs SET
                   needs_human_reason = NULL,
                   needs_human_url = NULL,
                   needs_human_instructions = NULL,
                   apply_status = 'manual',
                   apply_category = 'manual_only'
               WHERE url = ?""",
            (url,),
        )
        transition_state(conn, url, "archived", reason="hitl_skip", force=True)
        commit_with_retry(conn)
        return {"url": url, "action": "skip", "ok": True}

    # done → requeue for next apply run
    conn.execute(
        """UPDATE jobs SET
               needs_human_reason = NULL,
               needs_human_url = NULL,
               needs_human_instructions = NULL,
               apply_status = 'failed',
               apply_error = COALESCE(apply_error, 'hitl_resolved'),
               apply_category = 'pending'
           WHERE url = ?""",
        (url,),
    )
    transition_state(conn, url, "ready_to_apply", reason="hitl_done", force=True)
    commit_with_retry(conn)
    return {"url": url, "action": "done", "ok": True}
