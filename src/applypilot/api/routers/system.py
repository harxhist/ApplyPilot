"""Health, stats, and discovery source listing."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from applypilot import __version__
from applypilot.api.deps import AuthDep, bootstrap
from applypilot.config import APP_DIR, ENV_PATH, get_tier
from applypilot.database import get_stats
from applypilot.pipeline import DISCOVERY_SOURCES

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    """Unauthenticated for Docker healthchecks."""
    bootstrap()
    return {
        "ok": True,
        "version": __version__,
        "tier": get_tier(),
        "apply_mode": (os.environ.get("APPLY_MODE") or "off").lower(),
        "app_dir": str(APP_DIR),
    }


@router.get("/stats")
def stats(_: AuthDep = None) -> dict:
    bootstrap()
    return get_stats()


@router.get("/sources")
def sources(_: AuthDep = None) -> dict:
    return {"sources": DISCOVERY_SOURCES}


@router.get("/integrations")
def integrations(_: AuthDep = None) -> dict:
    """Secret presence only — never return values."""
    bootstrap()
    keys = [
        "CURSOR_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "CAPSOLVER_API_KEY",
        "LLM_PROVIDER",
        "LLM_MODEL",
        "APPLYPILOT_API_TOKEN",
    ]
    env_exists = ENV_PATH.exists()
    present = {}
    for k in keys:
        present[k] = bool(os.environ.get(k, "").strip())
    return {
        "env_file": str(ENV_PATH),
        "env_file_exists": env_exists,
        "configured": present,
        "tier": get_tier(),
    }
