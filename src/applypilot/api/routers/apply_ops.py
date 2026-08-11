"""Apply console + HITL + sessions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from applypilot.api.deps import AuthDep, bootstrap, resolve_url_from_hash, url_hash
from applypilot.api.runner import get_apply_status, start_apply, stop_apply
from applypilot.api.schemas import ApplyStartRequest, HitlResolveRequest
from applypilot.database import list_hitl_jobs
from applypilot import ops

router = APIRouter(tags=["apply"])


@router.get("/apply/status")
def apply_status(_: AuthDep = None) -> dict:
    bootstrap()
    return get_apply_status()


@router.post("/apply/start")
def apply_start(body: ApplyStartRequest, _: AuthDep = None) -> dict:
    bootstrap()
    return start_apply(body.model_dump())


@router.post("/apply/stop")
def apply_stop(_: AuthDep = None) -> dict:
    bootstrap()
    return stop_apply()


@router.get("/hitl")
def hitl_list(_: AuthDep = None) -> dict:
    bootstrap()
    items = list_hitl_jobs()
    for i in items:
        i["id"] = url_hash(i["url"])
    return {"items": items}


@router.post("/hitl/{job_id}/resolve")
def hitl_resolve(job_id: str, body: HitlResolveRequest, _: AuthDep = None) -> dict:
    bootstrap()
    url = resolve_url_from_hash(job_id)
    try:
        return ops.resolve_hitl(url, body.action)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/sessions")
def sessions(_: AuthDep = None) -> dict:
    bootstrap()
    return {"items": ops.list_ats_sessions()}


@router.delete("/sessions/{slug}")
def clear_session(slug: str, _: AuthDep = None) -> dict:
    bootstrap()
    ok = ops.clear_ats_session(slug)
    if not ok:
        raise HTTPException(404, f"No session for {slug}")
    return {"ok": True, "slug": slug}
