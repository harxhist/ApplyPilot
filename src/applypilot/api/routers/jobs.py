"""FastAPI operator API route order: static paths before {job_id}."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

from applypilot.api.deps import AuthDep, bootstrap, resolve_url_from_hash, url_hash
from applypilot.api.schemas import MarkRequest, ResetCategoryRequest
from applypilot.database import get_job, list_jobs
from applypilot import ops

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _enrich_item(item: dict) -> dict:
    item = dict(item)
    item["id"] = url_hash(item["url"])
    return item


@router.get("")
def jobs_list(
    _: AuthDep = None,
    q: str | None = None,
    state: str | None = None,
    min_score: int | None = None,
    max_score: int | None = None,
    site: str | None = None,
    company: str | None = None,
    applied: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    order_by: str = "discovered_at",
    order_dir: str = "desc",
) -> dict:
    bootstrap()
    result = list_jobs(
        q=q,
        state=state,
        min_score=min_score,
        max_score=max_score,
        site=site,
        company=company,
        applied=applied,
        limit=limit,
        offset=offset,
        order_by=order_by,
        order_dir=order_dir,
    )
    result["items"] = [_enrich_item(i) for i in result["items"]]
    return result


@router.post("/mark")
def mark(body: MarkRequest, _: AuthDep = None) -> dict:
    bootstrap()
    if body.status == "applied":
        ops.mark_job_applied(body.url)
    else:
        ops.mark_job_failed(body.url, body.reason)
    return {"ok": True, "url": body.url, "status": body.status}


@router.post("/reset-failed")
def reset_failed(_: AuthDep = None) -> dict:
    bootstrap()
    count = ops.reset_failed_jobs()
    return {"ok": True, "count": count}


@router.post("/reset-category")
def reset_category(body: ResetCategoryRequest, _: AuthDep = None) -> dict:
    bootstrap()
    count = ops.reset_jobs_by_category(body.category)
    return {"ok": True, "count": count, "category": body.category}


@router.get("/{job_id}")
def job_detail(job_id: str, _: AuthDep = None) -> dict:
    bootstrap()
    url = resolve_url_from_hash(job_id)
    job = get_job(url)
    if not job:
        raise HTTPException(404, "Job not found")
    job["id"] = job_id
    return job


@router.get("/{job_id}/resume")
def job_resume(job_id: str, _: AuthDep = None):
    bootstrap()
    url = resolve_url_from_hash(job_id)
    job = get_job(url)
    if not job or not job.get("tailored_resume_path"):
        raise HTTPException(404, "No tailored resume")
    path = Path(job["tailored_resume_path"])
    if not path.exists():
        raise HTTPException(404, "Resume file missing on disk")
    if path.suffix.lower() in (".txt", ".md"):
        return PlainTextResponse(path.read_text(encoding="utf-8", errors="replace"))
    return FileResponse(path)


@router.get("/{job_id}/cover")
def job_cover(job_id: str, _: AuthDep = None):
    bootstrap()
    url = resolve_url_from_hash(job_id)
    job = get_job(url)
    if not job or not job.get("cover_letter_path"):
        raise HTTPException(404, "No cover letter")
    path = Path(job["cover_letter_path"])
    if not path.exists():
        raise HTTPException(404, "Cover letter file missing on disk")
    if path.suffix.lower() in (".txt", ".md"):
        return PlainTextResponse(path.read_text(encoding="utf-8", errors="replace"))
    return FileResponse(path)
