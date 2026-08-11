"""API dependencies: auth, bootstrap, URL helpers."""

from __future__ import annotations

import hashlib
import os
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from applypilot.config import load_env, ensure_dirs
from applypilot.database import get_connection, init_db


def bootstrap() -> None:
    load_env()
    ensure_dirs()
    init_db()


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def resolve_url_from_hash(url_hash_value: str) -> str:
    """Resolve a short hash back to a job URL (unique prefix match)."""
    conn = get_connection()
    # Prefer exact stored mapping via full scan of urls hashed — jobs are typically <10k
    rows = conn.execute("SELECT url FROM jobs").fetchall()
    matches = [r["url"] for r in rows if url_hash(r["url"]) == url_hash_value]
    if not matches:
        raise HTTPException(status_code=404, detail="Job not found")
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Ambiguous job hash")
    return matches[0]


def require_token(
    authorization: Annotated[str | None, Header()] = None,
    x_api_token: Annotated[str | None, Header(alias="X-API-Token")] = None,
) -> None:
    expected = os.environ.get("APPLYPILOT_API_TOKEN", "").strip()
    if not expected:
        # Dev convenience: allow unauthenticated when token unset and not in compose prod
        if os.environ.get("APPLYPILOT_REQUIRE_TOKEN", "").lower() in ("1", "true", "yes"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="APPLYPILOT_API_TOKEN is not configured",
            )
        return

    provided = None
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    elif x_api_token:
        provided = x_api_token.strip()

    if not provided or provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )


AuthDep = Annotated[None, Depends(require_token)]
