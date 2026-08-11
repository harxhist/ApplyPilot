"""Background pipeline / apply process runners."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from applypilot.config import LOG_DIR
from applypilot.database import create_pipeline_run, finish_pipeline_run, get_pipeline_run

log = logging.getLogger(__name__)

_apply_lock = threading.Lock()
_apply_proc: subprocess.Popen | None = None
_apply_meta: dict = {}


def start_pipeline_run(req_dict: dict) -> dict:
    run_id = uuid.uuid4().hex[:12]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"pipeline_run_{run_id}.log"

    stages = req_dict.get("stages") or ["all"]
    create_pipeline_run(run_id, stages, req_dict, str(log_path))

    def _worker() -> None:
        try:
            from applypilot.pipeline import run_pipeline

            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"=== pipeline run {run_id} started {datetime.now(timezone.utc).isoformat()} ===\n")
                fh.flush()

            # Route rich/logging to file is hard; capture via redirect of stdout
            result = run_pipeline(
                stages=stages,
                min_score=req_dict.get("min_score"),
                max_age_days=req_dict.get("max_age_days"),
                limit=req_dict.get("limit"),
                dry_run=bool(req_dict.get("dry_run")),
                stream=bool(req_dict.get("stream")),
                workers=int(req_dict.get("workers") or 1),
                sources=req_dict.get("sources"),
                doc_format=req_dict.get("doc_format") or "docx",
            )
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"result": result}, default=str) + "\n")
                fh.write(f"=== finished ok ===\n")
            finish_pipeline_run(run_id, "completed", result=result)
        except Exception as exc:
            log.exception("pipeline run %s failed", run_id)
            try:
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(f"ERROR: {exc}\n")
            except Exception:
                pass
            finish_pipeline_run(run_id, "failed", error=str(exc))

    threading.Thread(target=_worker, daemon=True, name=f"pipeline-{run_id}").start()
    return get_pipeline_run(run_id) or {"id": run_id, "status": "running"}


def apply_mode() -> str:
    return (os.environ.get("APPLY_MODE") or "off").strip().lower()


def get_apply_status() -> dict:
    with _apply_lock:
        running = _apply_proc is not None and _apply_proc.poll() is None
        return {
            "mode": apply_mode(),
            "running": running,
            "pid": _apply_proc.pid if running and _apply_proc else None,
            "meta": dict(_apply_meta) if _apply_meta else {},
            "host_command_hint": (
                "applypilot apply --workers 2 --min-score 8"
            ),
        }


def start_apply(req_dict: dict) -> dict:
    global _apply_proc, _apply_meta
    mode = apply_mode()
    if mode in ("off", "disabled", "0", "false", "no"):
        return {
            "ok": False,
            "error": "APPLY_MODE=off — browser apply is disabled in this environment. "
            "Run on the host: applypilot apply …",
            "status": get_apply_status(),
        }
    if mode != "subprocess":
        return {
            "ok": False,
            "error": f"Unknown APPLY_MODE={mode!r}; use off|subprocess",
            "status": get_apply_status(),
        }

    with _apply_lock:
        if _apply_proc is not None and _apply_proc.poll() is None:
            return {"ok": False, "error": "Apply already running", "status": get_apply_status()}

        cmd = [sys.executable, "-m", "applypilot", "apply"]
        if req_dict.get("limit") is not None:
            cmd += ["--limit", str(req_dict["limit"])]
        cmd += ["--workers", str(req_dict.get("workers") or 2)]
        if req_dict.get("min_score") is not None:
            cmd += ["--min-score", str(req_dict["min_score"])]
        if req_dict.get("max_score") is not None:
            cmd += ["--max-score", str(req_dict["max_score"])]
        if req_dict.get("max_age_days") is not None:
            cmd += ["--max-age-days", str(req_dict["max_age_days"])]
        if req_dict.get("model"):
            cmd += ["--model", str(req_dict["model"])]
        if req_dict.get("continuous"):
            cmd.append("--continuous")
        if req_dict.get("dry_run"):
            cmd.append("--dry-run")
        if req_dict.get("headless"):
            cmd.append("--headless")
        if req_dict.get("no_hitl"):
            cmd.append("--no-hitl")
        if req_dict.get("url"):
            cmd += ["--url", str(req_dict["url"])]
        if req_dict.get("doc_format"):
            cmd += ["--doc-format", str(req_dict["doc_format"])]

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"apply_api_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"
        fh = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _apply_proc = proc
        _apply_meta = {
            "cmd": cmd,
            "log_path": str(log_path),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"ok": True, "status": get_apply_status()}


def stop_apply() -> dict:
    global _apply_proc
    with _apply_lock:
        if _apply_proc is None or _apply_proc.poll() is not None:
            return {"ok": False, "error": "No apply process running", "status": get_apply_status()}
        _apply_proc.terminate()
        try:
            _apply_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _apply_proc.kill()
        _apply_proc = None
        return {"ok": True, "status": get_apply_status()}


def tail_log(path: str | Path, from_byte: int = 0) -> tuple[str, int]:
    p = Path(path)
    if not p.exists():
        return "", from_byte
    data = p.read_bytes()
    chunk = data[from_byte:]
    return chunk.decode("utf-8", errors="replace"), len(data)
