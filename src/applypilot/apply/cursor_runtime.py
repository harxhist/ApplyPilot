"""Run ApplyPilot apply jobs via local Cursor Agent SDK + Playwright MCP.

Replaces the Claude Code CLI subprocess. Same prompts and RESULT:/QA: contract;
only the executor changes.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from applypilot import config

log = logging.getLogger("applypilot.apply.cursor_runtime")

# Cursor Auto — works on included quota when composer-* usage is exhausted
DEFAULT_MODEL = "default"


def resolve_apply_model(explicit: str | None = None) -> str:
    """Resolve apply model: explicit arg → APPLY_MODEL → LLM_MODEL → default."""
    for candidate in (
        (explicit or "").strip(),
        (os.environ.get("APPLY_MODEL") or "").strip(),
        (os.environ.get("LLM_MODEL") or "").strip(),
        DEFAULT_MODEL,
    ):
        if candidate:
            return candidate
    return DEFAULT_MODEL


@dataclass
class CursorRunResult:
    """Normalized agent run output for launcher.result parsing."""

    output: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    screening_qs: list[dict] = field(default_factory=list)
    cancelled: bool = False
    error: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    status: str = "finished"  # finished | error | cancelled


def _api_key() -> str:
    config.load_env()
    key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "CURSOR_API_KEY missing. Add it to ~/.applypilot/.env "
            "(Cursor Dashboard → Integrations)."
        )
    return key


def make_playwright_mcp(cdp_port: int) -> dict[str, Any]:
    """Inline stdio MCP config for Playwright attached to a Chrome CDP port."""
    try:
        from cursor_sdk import StdioMcpServerConfig

        return {
            "playwright": StdioMcpServerConfig(
                command="npx",
                args=[
                    "-y",
                    "@playwright/mcp@0.0.75",
                    f"--cdp-endpoint=http://localhost:{cdp_port}",
                ],
            )
        }
    except ImportError:
        return {
            "playwright": {
                "type": "stdio",
                "command": "npx",
                "args": [
                    "-y",
                    "@playwright/mcp@0.0.75",
                    f"--cdp-endpoint=http://localhost:{cdp_port}",
                ],
            }
        }


def _parse_screening_qs(text: str, into: list[dict]) -> None:
    for tl in text.split("\n"):
        tl = tl.strip()
        if not tl.startswith("SCREENING_Q:"):
            continue
        payload = tl[len("SCREENING_Q:") :].strip()
        parts = payload.split("|")
        if len(parts) >= 2:
            into.append(
                {
                    "question": parts[0].strip(),
                    "field_type": parts[1].strip(),
                    "options": parts[2].strip() if len(parts) > 2 else "",
                }
            )


def _tool_summary(name: str, inp: dict) -> str:
    short = (
        name.replace("mcp__playwright__", "")
        .replace("playwright_", "")
        .replace("mcp_playwright_", "")
    )
    if "url" in inp:
        return f"{short} {str(inp['url'])[:60]}"
    if "ref" in inp:
        return f"{short} {str(inp.get('element', inp.get('text', '')))[:50]}"
    if "fields" in inp:
        return f"{short} ({len(inp['fields'])} fields)"
    if "paths" in inp:
        return f"{short} upload"
    return short


def run_cursor_job(
    prompt: str,
    *,
    cdp_port: int,
    worker_dir: Path,
    worker_id: int = 0,
    model: str = DEFAULT_MODEL,
    log_file: Any | None = None,
    should_stop: Callable[[], bool] | None = None,
    on_action: Callable[[str], None] | None = None,
) -> CursorRunResult:
    """Run one apply prompt with a local Cursor agent + Playwright MCP.

    Streams assistant text into ``log_file`` (if provided) and accumulates
    RESULT/QA/SCREENING_Q lines for the launcher parser.
    """
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError as e:
        raise RuntimeError(
            "cursor-sdk is not installed. Run: pip install cursor-sdk"
        ) from e

    result = CursorRunResult()
    text_parts: list[str] = []
    mcp_servers = make_playwright_mcp(cdp_port)
    worker_dir = Path(worker_dir)
    worker_dir.mkdir(parents=True, exist_ok=True)

    # Map Claude-oriented aliases to Cursor model ids
    model_map = {
        "sonnet": DEFAULT_MODEL,
        "haiku": "composer-2.5",
        "opus": "composer-2.5",
        "claude": DEFAULT_MODEL,
        "auto": "default",
    }
    requested = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    model_id = model_map.get(requested.lower(), requested)

    api_key = _api_key()
    stop_flag = threading.Event()
    status_error_msg = ""

    def _stopped() -> bool:
        if stop_flag.is_set():
            return True
        if should_stop and should_stop():
            stop_flag.set()
            return True
        return False

    def _handle_assistant_blocks(blocks: Any) -> None:
        for block in blocks or []:
            if isinstance(block, dict):
                bt = block.get("type")
                if bt == "text":
                    t = block.get("text") or ""
                    text_parts.append(t)
                    if log_file:
                        log_file.write(t + "\n")
                    _parse_screening_qs(t, result.screening_qs)
                elif bt == "tool_use":
                    name = block.get("name", "")
                    inp = block.get("input") or {}
                    desc = _tool_summary(name, inp)
                    result.tool_calls.append({"tool": name, "summary": desc})
                    if log_file:
                        log_file.write(f"  >> {desc}\n")
                    if on_action:
                        on_action(desc[:35])
            else:
                bt = getattr(block, "type", None)
                if bt == "text":
                    t = getattr(block, "text", "") or ""
                    text_parts.append(t)
                    if log_file:
                        log_file.write(t + "\n")
                    _parse_screening_qs(t, result.screening_qs)
                elif bt == "tool_use":
                    name = getattr(block, "name", "") or ""
                    inp = getattr(block, "input", None) or {}
                    if hasattr(inp, "model_dump"):
                        inp = inp.model_dump()
                    elif not isinstance(inp, dict):
                        inp = {}
                    desc = _tool_summary(name, inp)
                    result.tool_calls.append({"tool": name, "summary": desc})
                    if log_file:
                        log_file.write(f"  >> {desc}\n")
                    if on_action:
                        on_action(desc[:35])

    def _handle_tool_message(message: Any) -> None:
        name = getattr(message, "name", None) or (
            message.get("name") if isinstance(message, dict) else ""
        ) or ""
        inp = getattr(message, "input", None) or (
            message.get("input") if isinstance(message, dict) else {}
        ) or {}
        if hasattr(inp, "model_dump"):
            inp = inp.model_dump()
        if not isinstance(inp, dict):
            inp = {}
        desc = _tool_summary(str(name), inp)
        result.tool_calls.append({"tool": str(name), "summary": desc})
        if log_file:
            log_file.write(f"  >> {desc}\n")
        if on_action:
            on_action(desc[:35])

    def _run_once(active_model: str) -> None:
        nonlocal status_error_msg
        status_error_msg = ""
        with Agent.create(
            AgentOptions(
                api_key=api_key,
                model=active_model,
                local=LocalAgentOptions(cwd=str(worker_dir)),
                mcp_servers=mcp_servers,
            )
        ) as agent:
            result.agent_id = getattr(agent, "agent_id", None) or getattr(
                agent, "agentId", None
            )
            log.info(
                "[W%d] Cursor agent started id=%s model=%s cdp=%d cwd=%s",
                worker_id,
                result.agent_id,
                active_model,
                cdp_port,
                worker_dir,
            )

            run = agent.send(prompt)
            result.run_id = getattr(run, "id", None)

            # events() surfaces status ERROR messages that messages() omits
            for ev in run.events():
                if _stopped():
                    if run.supports("cancel"):
                        try:
                            run.cancel()
                        except Exception:
                            log.debug("cancel failed", exc_info=True)
                    result.cancelled = True
                    result.status = "cancelled"
                    break

                sm = getattr(ev, "sdk_message", None)
                if sm is None:
                    continue

                msg_type = getattr(sm, "type", None) or (
                    sm.get("type") if isinstance(sm, dict) else None
                )

                if msg_type == "status":
                    st = str(getattr(sm, "status", "") or "")
                    msg = getattr(sm, "message", "") or ""
                    if st.upper() == "ERROR" and msg:
                        status_error_msg = msg
                        if log_file:
                            log_file.write(f"[cursor status ERROR] {msg}\n")
                        log.error("[W%d] Cursor status ERROR: %s", worker_id, msg[:200])
                    continue

                if msg_type == "assistant":
                    content = None
                    if hasattr(sm, "message"):
                        content = getattr(sm.message, "content", None)
                    elif isinstance(sm, dict):
                        content = (sm.get("message") or {}).get("content")
                    if content is None and hasattr(sm, "text"):
                        content = [{"type": "text", "text": sm.text}]
                    _handle_assistant_blocks(content)
                elif msg_type in ("tool_call", "tool_use"):
                    _handle_tool_message(sm)

            wait_result = run.wait()
            wait_status = getattr(wait_result, "status", None) or "finished"
            result.status = str(wait_status)
            final_text = getattr(wait_result, "result", None) or ""
            if final_text and str(final_text) not in text_parts:
                text_parts.append(str(final_text))
                if log_file:
                    log_file.write(str(final_text) + "\n")

            if wait_status == "error":
                result.error = (
                    status_error_msg
                    or f"Cursor run error id={result.run_id}"
                )
                if log_file and status_error_msg:
                    log_file.write(f"[cursor_runtime error] {result.error}\n")
                log.error(
                    "[W%d] Cursor run failed model=%s: %s",
                    worker_id, active_model, result.error[:200],
                )

    try:
        _run_once(model_id)
        # Defensive: composer-* often hits paid-usage wall; retry once on Auto
        usage_hit = bool(result.error) and any(
            tok in (result.error or "").lower()
            for tok in ("out of usage", "increase limits", "usage", "rate limit")
        )
        if (
            usage_hit
            and not result.cancelled
            and model_id.lower().startswith("composer")
            and model_id.lower() not in ("default", "auto")
        ):
            log.warning(
                "[W%d] %s hit usage limit — retrying once with model=default",
                worker_id, model_id,
            )
            if log_file:
                log_file.write(
                    f"\n[cursor_runtime] usage limit on {model_id}; "
                    "retrying with default (Auto)\n"
                )
            text_parts.clear()
            result.tool_calls.clear()
            result.screening_qs.clear()
            result.error = None
            result.status = "finished"
            _run_once("default")

    except Exception as e:
        # Distinguish CursorAgentError when available
        err_name = type(e).__name__
        result.error = f"{err_name}: {e}"
        result.status = "error"
        log.exception("[W%d] Cursor agent failed: %s", worker_id, e)
        text_parts.append(f"\n[cursor_runtime error] {result.error}\n")

    result.output = "\n".join(text_parts)
    return result


def run_cursor_mini_task(
    instructions: str,
    *,
    cdp_port: int,
    worker_dir: Path,
    worker_id: int = 0,
    model: str = DEFAULT_MODEL,
) -> CursorRunResult:
    """Short Cursor agent run for HITL mini-tasks (same MCP wiring)."""
    prompt = (
        f"You have browser access via Playwright MCP (CDP port {cdp_port}).\n"
        f"Complete ONLY this task, then stop:\n\n{instructions}\n"
    )
    return run_cursor_job(
        prompt,
        cdp_port=cdp_port,
        worker_dir=worker_dir,
        worker_id=worker_id,
        model=model,
    )
