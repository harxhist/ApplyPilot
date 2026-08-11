"""FastAPI application factory."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from applypilot.api.routers import apply_ops, config_ops, jobs, pipeline, qa_accounts, system


def create_app() -> FastAPI:
    app = FastAPI(
        title="ApplyPilot Operator API",
        version="0.2.0",
        description="Control plane for ApplyPilot pipeline, jobs, and operator tools.",
    )

    origins = os.environ.get("APPLYPILOT_CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = "/api/v1"
    app.include_router(system.router, prefix=prefix)
    app.include_router(jobs.router, prefix=prefix)
    app.include_router(pipeline.router, prefix=prefix)
    app.include_router(apply_ops.router, prefix=prefix)
    app.include_router(qa_accounts.router, prefix=prefix)
    app.include_router(config_ops.router, prefix=prefix)

    @app.get("/")
    def root():
        return {"service": "applypilot-api", "docs": "/docs", "api": prefix}

    return app


app = create_app()
