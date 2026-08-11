"""QA knowledge + accounts CRUD."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from applypilot.api.deps import AuthDep, bootstrap
from applypilot.api.schemas import AccountUpsertRequest, QaCreateRequest, QaUpdateRequest
from applypilot.database import (
    commit_with_retry,
    delete_account,
    get_all_accounts,
    get_all_qa,
    get_connection,
    get_qa_stats,
    upsert_account,
)

router = APIRouter(tags=["qa-accounts"])


@router.get("/qa")
def qa_list(_: AuthDep = None, limit: int = 200) -> dict:
    bootstrap()
    items = get_all_qa()[:limit]
    return {"items": items, "stats": get_qa_stats()}


@router.post("/qa")
def qa_create(body: QaCreateRequest, _: AuthDep = None) -> dict:
    bootstrap()
    from applypilot.database import store_qa

    qa_id = store_qa(
        question=body.question_text,
        answer=body.answer_text,
        source=body.answer_source,
        field_type=body.field_type,
        ats_slug=body.ats,
    )
    return {"ok": True, "id": qa_id}


@router.patch("/qa/{qa_id}")
def qa_update(qa_id: int, body: QaUpdateRequest, _: AuthDep = None) -> dict:
    bootstrap()
    conn = get_connection()
    row = conn.execute("SELECT id FROM qa_knowledge WHERE id = ?", (qa_id,)).fetchone()
    if not row:
        raise HTTPException(404, "QA not found")
    updates = []
    params = []
    if body.answer_text is not None:
        updates.append("answer_text = ?")
        params.append(body.answer_text)
    if body.outcome is not None:
        updates.append("outcome = ?")
        params.append(body.outcome)
    if body.answer_source is not None:
        updates.append("answer_source = ?")
        params.append(body.answer_source)
    if not updates:
        return {"ok": True}
    updates.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat())
    params.append(qa_id)
    conn.execute(f"UPDATE qa_knowledge SET {', '.join(updates)} WHERE id = ?", params)
    commit_with_retry(conn)
    return {"ok": True}


@router.delete("/qa/{qa_id}")
def qa_delete(qa_id: int, _: AuthDep = None) -> dict:
    bootstrap()
    conn = get_connection()
    cur = conn.execute("DELETE FROM qa_knowledge WHERE id = ?", (qa_id,))
    commit_with_retry(conn)
    if cur.rowcount == 0:
        raise HTTPException(404, "QA not found")
    return {"ok": True}


@router.get("/accounts")
def accounts_list(_: AuthDep = None) -> dict:
    bootstrap()
    items = get_all_accounts()
    # Mask passwords
    for a in items:
        pw = a.get("password") or ""
        a["password_set"] = bool(pw)
        a["password"] = "********" if pw else None
    return {"items": items}


@router.put("/accounts")
def accounts_upsert(body: AccountUpsertRequest, _: AuthDep = None) -> dict:
    bootstrap()
    upsert_account(
        domain=body.domain,
        email=body.email,
        password=body.password,
        site=body.site or body.domain,
        notes=body.notes,
    )
    return {"ok": True, "domain": body.domain}


@router.delete("/accounts/{domain}")
def accounts_delete(domain: str, _: AuthDep = None) -> dict:
    bootstrap()
    n = delete_account(domain)
    if not n:
        raise HTTPException(404, "Account not found")
    return {"ok": True, "domain": domain}
