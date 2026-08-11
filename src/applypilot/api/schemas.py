"""Pydantic schemas for the operator API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PipelineRunRequest(BaseModel):
    stages: list[str] = Field(default_factory=lambda: ["all"])
    min_score: Optional[int] = None
    max_age_days: Optional[int] = None
    limit: Optional[int] = None
    workers: int = 1
    stream: bool = False
    dry_run: bool = False
    sources: Optional[list[str]] = None
    doc_format: str = "docx"


class ApplyStartRequest(BaseModel):
    limit: Optional[int] = None
    workers: int = 2
    min_score: Optional[int] = None
    max_score: Optional[int] = None
    max_age_days: Optional[int] = None
    model: Optional[str] = None
    continuous: bool = False
    dry_run: bool = False
    headless: bool = False
    no_hitl: bool = False
    url: Optional[str] = None
    doc_format: str = "docx"


class MarkRequest(BaseModel):
    url: str
    status: str = Field(..., pattern="^(applied|failed)$")
    reason: Optional[str] = None


class ResetCategoryRequest(BaseModel):
    category: str


class HitlResolveRequest(BaseModel):
    action: str = Field("done", pattern="^(done|skip)$")


class QaCreateRequest(BaseModel):
    question_text: str
    answer_text: str
    question_key: Optional[str] = None
    answer_source: str = "manual"
    outcome: str = "unknown"
    field_type: Optional[str] = None
    ats: Optional[str] = None


class QaUpdateRequest(BaseModel):
    answer_text: Optional[str] = None
    outcome: Optional[str] = None
    answer_source: Optional[str] = None


class AccountUpsertRequest(BaseModel):
    domain: str
    email: str
    password: Optional[str] = None
    site: Optional[str] = None
    notes: Optional[str] = None


class ConfigPutRequest(BaseModel):
    content: str | dict[str, Any]


class TrackRunRequest(BaseModel):
    days: int = 14
    ghosted_days: int = 7
    limit: int = 100
    dry_run: bool = False


class OpsSeedRequest(BaseModel):
    pool: bool = False
    dry_run: bool = False


class OpsRefilterRequest(BaseModel):
    dry_run: bool = True
    rescore: bool = False
