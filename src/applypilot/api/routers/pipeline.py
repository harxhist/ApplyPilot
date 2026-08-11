"""Pipeline run control + SSE log tail."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from applypilot.api.deps import AuthDep, bootstrap
from applypilot.api.runner import start_pipeline_run, tail_log
from applypilot.api.schemas import PipelineRunRequest
from applypilot.database import get_pipeline_run, list_pipeline_runs

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/runs")
def runs(_: AuthDep = None, limit: int = 50) -> dict:
    bootstrap()
    return {"items": list_pipeline_runs(limit=limit)}


@router.post("/runs")
def create_run(body: PipelineRunRequest, _: AuthDep = None) -> dict:
    bootstrap()
    return start_pipeline_run(body.model_dump())


@router.get("/runs/{run_id}")
def get_run(run_id: str, _: AuthDep = None) -> dict:
    bootstrap()
    run = get_pipeline_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, _: AuthDep = None):
    bootstrap()
    run = get_pipeline_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    log_path = run.get("log_path")
    if not log_path:
        raise HTTPException(404, "No log for run")

    async def gen():
        pos = 0
        idle = 0
        while True:
            text, pos = await asyncio.to_thread(tail_log, log_path, pos)
            if text:
                for line in text.splitlines():
                    yield f"data: {line}\n\n"
                idle = 0
            else:
                idle += 1
                # Re-check status
                current = await asyncio.to_thread(get_pipeline_run, run_id)
                status = (current or {}).get("status")
                if status in ("completed", "failed") and idle > 3:
                    yield f"event: done\ndata: {status}\n\n"
                    break
                if idle > 600:
                    yield "event: done\ndata: timeout\n\n"
                    break
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")
