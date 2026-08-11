"""Config editors + tracking + harsh ops + dashboard export."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException

from applypilot.api.deps import AuthDep, bootstrap
from applypilot.api.schemas import (
    ConfigPutRequest,
    OpsRefilterRequest,
    OpsSeedRequest,
    TrackRunRequest,
)
from applypilot.config import (
    APP_DIR,
    COMPANY_LIMITS_PATH_NAME,
    PROFILE_PATH,
    SEARCH_CONFIG_PATH,
)
from applypilot.database import get_connection

router = APIRouter(tags=["config-ops"])


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


@router.get("/config/profile")
def get_profile(_: AuthDep = None) -> dict:
    bootstrap()
    raw = _read_text(PROFILE_PATH)
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    return {"path": str(PROFILE_PATH), "content": data, "raw": raw}


@router.put("/config/profile")
def put_profile(body: ConfigPutRequest, _: AuthDep = None) -> dict:
    bootstrap()
    if isinstance(body.content, str):
        text = body.content
        json.loads(text)  # validate
    else:
        text = json.dumps(body.content, indent=2)
    PROFILE_PATH.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")
    return {"ok": True, "path": str(PROFILE_PATH)}


@router.get("/config/searches")
def get_searches(_: AuthDep = None) -> dict:
    bootstrap()
    raw = _read_text(SEARCH_CONFIG_PATH)
    try:
        data = yaml.safe_load(raw) if raw else {}
    except yaml.YAMLError:
        data = {}
    return {"path": str(SEARCH_CONFIG_PATH), "content": data, "raw": raw}


@router.put("/config/searches")
def put_searches(body: ConfigPutRequest, _: AuthDep = None) -> dict:
    bootstrap()
    if isinstance(body.content, str):
        text = body.content
        yaml.safe_load(text)
    else:
        text = yaml.safe_dump(body.content, sort_keys=False)
    SEARCH_CONFIG_PATH.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return {"ok": True, "path": str(SEARCH_CONFIG_PATH)}


@router.get("/config/company-limits")
def get_limits(_: AuthDep = None) -> dict:
    bootstrap()
    path = APP_DIR / COMPANY_LIMITS_PATH_NAME
    raw = _read_text(path)
    try:
        data = yaml.safe_load(raw) if raw else {}
    except yaml.YAMLError:
        data = {}
    return {"path": str(path), "content": data, "raw": raw}


@router.put("/config/company-limits")
def put_limits(body: ConfigPutRequest, _: AuthDep = None) -> dict:
    bootstrap()
    path = APP_DIR / COMPANY_LIMITS_PATH_NAME
    if isinstance(body.content, str):
        text = body.content
        yaml.safe_load(text)
    else:
        text = yaml.safe_dump(body.content, sort_keys=False)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    return {"ok": True, "path": str(path)}


@router.get("/tracking")
def tracking_overview(_: AuthDep = None, limit: int = 100) -> dict:
    bootstrap()
    conn = get_connection()
    emails = conn.execute(
        "SELECT email_id, thread_id, job_url, sender, subject, received_at, "
        "classification, snippet FROM tracking_emails "
        "ORDER BY received_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    jobs = conn.execute(
        """SELECT url, title, company, tracking_status, next_action, next_action_due,
                  last_email_at, applied_at
           FROM jobs
           WHERE tracking_status IS NOT NULL OR next_action IS NOT NULL
           ORDER BY COALESCE(last_email_at, applied_at) DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return {
        "emails": [dict(r) for r in emails],
        "jobs": [dict(r) for r in jobs],
    }


@router.post("/tracking/run")
def tracking_run(body: TrackRunRequest, _: AuthDep = None) -> dict:
    bootstrap()
    try:
        from applypilot.tracking import run_tracking

        result = run_tracking(
            days=body.days,
            ghosted_days=body.ghosted_days,
            limit=body.limit,
            dry_run=body.dry_run,
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/ops/seed")
def ops_seed(body: OpsSeedRequest, _: AuthDep = None) -> dict:
    """Invoke seed_harsh_queue.py via subprocess."""
    bootstrap()
    import subprocess
    import sys

    script = None
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "scripts" / "seed_harsh_queue.py"
        if cand.exists():
            script = cand
            break
    if script is None:
        raise HTTPException(404, "seed_harsh_queue.py not found")

    cmd = [sys.executable, str(script)]
    if body.pool:
        cmd.append("--pool")
    # seed script has no --dry-run; when dry_run, only report that seeding would run
    if body.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_run": cmd,
            "note": "seed_harsh_queue.py has no --dry-run; pass dry_run=false to execute",
        }
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-4000:],
    }


@router.post("/ops/refilter")
def ops_refilter(body: OpsRefilterRequest, _: AuthDep = None) -> dict:
    bootstrap()
    import subprocess
    import sys

    script = None
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "scripts" / "refilter_harsh_queue.py"
        if cand.exists():
            script = cand
            break
    if script is None:
        raise HTTPException(404, "refilter_harsh_queue.py not found")

    cmd = [sys.executable, str(script)]
    if body.dry_run:
        cmd.append("--dry-run")
    if body.rescore:
        cmd.append("--rescore")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-4000:],
    }


@router.post("/ops/export-dashboard")
def export_dashboard(_: AuthDep = None) -> dict:
    bootstrap()
    from applypilot.view import generate_dashboard

    path = generate_dashboard()
    return {"ok": True, "path": path}
