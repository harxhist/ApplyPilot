"""
Unified LLM client for ApplyPilot.

Auto-detects provider from environment:
  CURSOR_API_KEY    -> Cursor Agent SDK (primary when set / LLM_PROVIDER=cursor)
  GEMINI_API_KEY    -> Google Gemini
  OPENAI_API_KEY    -> OpenAI (fallback)
  ANTHROPIC_API_KEY -> Anthropic (fallback)
  LLM_URL           -> Local llama.cpp / Ollama compatible endpoint

LLM_PROVIDER env: cursor | gemini | openai | auto (default: auto)
  auto = Cursor first if CURSOR_API_KEY is set, else Gemini, else OpenAI/local.

LLM_MODEL env var overrides the default (fast) model for any provider.
LLM_MODEL_QUALITY env var sets a higher-quality model for critical steps
(resume tailoring, cover letters). Falls back to LLM_MODEL if not set.

When a model hits a 429 / usage limit, the client automatically tries the
next model in the fallback chain — including cross-provider fallback.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global pacing — reduces 429s on free-tier Gemini / shared Cursor pool
# ---------------------------------------------------------------------------

_rate_lock = threading.Lock()
_last_request_at = 0.0
# Shared across quality + fast singletons so a 429 on one skips the same model on the other
_global_exhausted: dict[str, float] = {}

# Durable Cursor agents (create-once, many sends) — keyed by model id
_cursor_agents: dict[str, object] = {}
_cursor_agent_lock = threading.Lock()
_cursor_cwd: Path | None = None


def _min_interval_sec() -> float:
    """Minimum seconds between LLM HTTP/SDK calls (all threads share one bucket)."""
    default = "2" if (os.environ.get("CURSOR_API_KEY") or "").strip() else "5"
    try:
        return max(0.0, float(os.environ.get("LLM_MIN_INTERVAL_SEC", default)))
    except ValueError:
        return float(default)


def _quota_cooldown_sec() -> float:
    """How long to skip a model after a hard quota/429 exhaustion."""
    try:
        return max(60.0, float(os.environ.get("LLM_QUOTA_COOLDOWN_SEC", "600")))
    except ValueError:
        return 600.0


def _pace_request() -> None:
    """Block until the global min-interval since the last LLM request has elapsed."""
    global _last_request_at
    interval = _min_interval_sec()
    if interval <= 0:
        return
    with _rate_lock:
        now = time.time()
        wait = interval - (now - _last_request_at)
        if wait > 0:
            log.debug("LLM pace: sleeping %.1fs (min interval %.1fs)", wait, interval)
            time.sleep(wait)
        _last_request_at = time.time()


def _llm_provider_pref() -> str:
    return (os.environ.get("LLM_PROVIDER") or "auto").strip().lower()


def _cursor_scratch_cwd() -> Path:
    """Stable empty-ish cwd for text-only Cursor Agent runs."""
    global _cursor_cwd
    if _cursor_cwd is not None:
        return _cursor_cwd
    base = Path(os.environ.get("APPLYPILOT_DIR", Path.home() / ".applypilot"))
    cwd = base / "llm_scratch"
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "README.txt").write_text(
        "ApplyPilot LLM scratch workspace. Cursor Agent should not edit files here.\n"
    )
    _cursor_cwd = cwd
    return cwd


# ---------------------------------------------------------------------------
# Model registry — each entry knows its provider, endpoint, and API key
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelEntry:
    """A model with everything needed to call it."""
    name: str
    provider: str           # "cursor", "gemini", "openai", "anthropic", "local", "deepseek"
    base_url: str
    api_key: str


def _build_fallback_chain(primary_model: str, quality: bool = False) -> list[ModelEntry]:
    """Build a cross-provider fallback chain starting from the preferred provider.

    Cursor (when keyed) → Gemini → OpenAI → DeepSeek → Anthropic.
    Only includes providers whose API keys are configured.
    """
    cursor_key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    gemini_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    openai_url = "https://api.openai.com/v1"
    anthropic_url = "https://api.anthropic.com"
    deepseek_url = "https://api.deepseek.com/v1"

    pref = _llm_provider_pref()

    # Cursor: "default"/"auto" use included Auto routing when composer usage is exhausted.
    if quality:
        cursor_models = ["default", "auto", "composer-2.5"]
    else:
        cursor_models = ["default", "auto", "composer-2.5"]

    # Gemini chains — prefer aliases that still have free-tier headroom.
    if quality:
        gemini_models = [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-flash-latest",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.5-flash",
        ]
    else:
        gemini_models = [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-flash-latest",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.5-flash",
        ]

    if quality:
        openai_models = ["gpt-4.1-mini", "gpt-4.1-nano"]
    else:
        openai_models = ["gpt-4.1-nano", "gpt-4.1-mini"]

    if quality:
        anthropic_models = ["claude-sonnet-4-5-20250514", "claude-haiku-4-5-20251001"]
    else:
        anthropic_models = ["claude-haiku-4-5-20251001"]

    deepseek_models = ["deepseek-chat"]

    chain: list[ModelEntry] = []

    def _add_cursor() -> None:
        if not cursor_key:
            return
        ordered: list[str] = []
        cursor_like = primary_model in cursor_models or primary_model.startswith(
            ("composer", "claude", "gpt-", "grok", "default", "auto")
        )
        if primary_model and cursor_like:
            ordered.append(primary_model)
        for m in cursor_models:
            if m not in ordered:
                ordered.append(m)
        for m in ordered:
            chain.append(ModelEntry(m, "cursor", "cursor-sdk", cursor_key))

    def _add_gemini() -> None:
        if not gemini_key:
            return
        started = False
        for m in gemini_models:
            if m == primary_model:
                started = True
            if started:
                chain.append(ModelEntry(m, "gemini", gemini_url, gemini_key))
        if not started:
            # Only inject primary as gemini if it looks like a gemini model
            if primary_model.startswith("gemini") or primary_model not in (
                "default", "auto", "composer-2.5", "composer-2"
            ):
                if primary_model.startswith("gemini"):
                    chain.append(ModelEntry(primary_model, "gemini", gemini_url, gemini_key))
            for m in gemini_models:
                if m != primary_model:
                    chain.append(ModelEntry(m, "gemini", gemini_url, gemini_key))

    def _add_openai() -> None:
        if openai_key:
            for m in openai_models:
                chain.append(ModelEntry(m, "openai", openai_url, openai_key))

    def _add_deepseek() -> None:
        if deepseek_key:
            for m in deepseek_models:
                chain.append(ModelEntry(m, "deepseek", deepseek_url, deepseek_key))

    def _add_anthropic() -> None:
        if anthropic_key:
            for m in anthropic_models:
                chain.append(ModelEntry(m, "anthropic", anthropic_url, anthropic_key))

    # Provider order
    want_cursor_first = (
        pref == "cursor"
        or (pref == "auto" and bool(cursor_key))
    )
    if pref == "gemini":
        _add_gemini()
        _add_cursor()
        _add_openai()
        _add_deepseek()
        _add_anthropic()
    elif pref == "openai":
        _add_openai()
        _add_cursor()
        _add_gemini()
        _add_deepseek()
        _add_anthropic()
    elif want_cursor_first:
        _add_cursor()
        _add_gemini()
        _add_openai()
        _add_deepseek()
        _add_anthropic()
    else:
        _add_gemini()
        _add_cursor()
        _add_openai()
        _add_deepseek()
        _add_anthropic()

    if not chain:
        raise RuntimeError(
            "No LLM provider configured. "
            "Set CURSOR_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, "
            "DEEPSEEK_API_KEY, or ANTHROPIC_API_KEY."
        )

    return chain


# ---------------------------------------------------------------------------
# Provider detection (for primary model selection)
# ---------------------------------------------------------------------------

def _detect_provider(quality: bool = False) -> tuple[str, str, str]:
    """Return (base_url, model, api_key) for the primary provider."""
    cursor_key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    local_url = os.environ.get("LLM_URL", "")
    pref = _llm_provider_pref()

    model_override = os.environ.get("LLM_MODEL", "")
    quality_model = os.environ.get("LLM_MODEL_QUALITY", "")

    if quality and quality_model:
        chosen_model = quality_model
    else:
        chosen_model = model_override

    use_cursor = (
        cursor_key
        and not local_url
        and (
            pref == "cursor"
            or (pref == "auto" and bool(cursor_key))
        )
        and pref != "gemini"
        and pref != "openai"
    )
    if use_cursor:
        return ("cursor-sdk", chosen_model or "default", cursor_key)

    if gemini_key and not local_url and pref != "openai":
        return (
            "https://generativelanguage.googleapis.com/v1beta/openai",
            chosen_model or "gemini-flash-lite-latest",
            gemini_key,
        )
    if openai_key and not local_url:
        return (
            "https://api.openai.com/v1",
            chosen_model or "gpt-4.1-nano",
            openai_key,
        )
    if cursor_key and not local_url:
        return ("cursor-sdk", chosen_model or "default", cursor_key)
    if local_url:
        return (
            local_url.rstrip("/"),
            chosen_model or "local-model",
            os.environ.get("LLM_API_KEY", ""),
        )
    raise RuntimeError(
        "No LLM provider configured. "
        "Set CURSOR_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, or LLM_URL."
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_TIMEOUT = 300  # seconds


def _messages_to_prompt(messages: list[dict]) -> str:
    """Flatten chat messages into a single Cursor Agent prompt."""
    parts: list[str] = [
        "You are a text-only assistant for ApplyPilot.",
        "Do not use tools, do not read or write files, do not run shell commands.",
        "Reply with ONLY the requested content — no preamble, no markdown fences unless asked.",
        "",
    ]
    for msg in messages:
        role = (msg.get("role") or "user").upper()
        content = msg.get("content") or ""
        parts.append(f"[{role}]\n{content}\n")
    return "\n".join(parts)


def _extract_assistant_text(run) -> str:
    """Collect assistant text from a Cursor run."""
    err_msg = ""
    # Prefer convenience helper when available
    try:
        text = (run.text() or "").strip()
        status = str(getattr(run, "status", "") or "")
        if status == "error" and not text:
            raise RuntimeError("Cursor run error (empty result)")
        if text:
            return text
    except RuntimeError:
        raise
    except Exception:
        log.debug("Cursor run.text() unavailable", exc_info=True)

    parts: list[str] = []
    try:
        for ev in run.events():
            sm = getattr(ev, "sdk_message", None)
            if sm is None:
                continue
            stype = getattr(sm, "type", None)
            if stype == "status":
                st = str(getattr(sm, "status", "") or "")
                msg = getattr(sm, "message", "") or ""
                if st.upper() == "ERROR" and msg:
                    err_msg = msg
            elif stype == "assistant":
                inner = getattr(sm, "message", None)
                content = getattr(inner, "content", None) if inner is not None else None
                for block in content or []:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block.get("text") or "")
                    elif getattr(block, "type", None) == "text":
                        parts.append(getattr(block, "text", "") or "")
    except Exception:
        log.debug("Cursor run.events() failed", exc_info=True)

    wait = run.wait()
    status = str(getattr(wait, "status", "") or "")
    final = getattr(wait, "result", None) or ""
    if final and str(final) not in parts:
        parts.append(str(final))

    text = "\n".join(p for p in parts if p).strip()
    if status == "error" and not text:
        raise RuntimeError(err_msg or "Cursor run error (empty result)")
    if status == "error":
        raise RuntimeError(err_msg or f"Cursor run error: {status}")
    return text


def _get_cursor_agent(model: str, api_key: str):
    """Return a durable Cursor Agent for text generation (create-once per model)."""
    with _cursor_agent_lock:
        existing = _cursor_agents.get(model)
        if existing is not None:
            return existing
        try:
            from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
        except ImportError as e:
            raise RuntimeError(
                "cursor-sdk is not installed. Run: pip install cursor-sdk"
            ) from e

        cwd = _cursor_scratch_cwd()
        agent = Agent.create(
            AgentOptions(
                api_key=api_key,
                model=model,
                mode="ask",
                local=LocalAgentOptions(cwd=str(cwd)),
            )
        )
        # Enter context manually so it stays open for reuse
        if hasattr(agent, "__enter__"):
            agent = agent.__enter__()
        _cursor_agents[model] = agent
        log.info("Cursor LLM agent ready model=%s cwd=%s id=%s",
                 model, cwd, getattr(agent, "agent_id", None))
        return agent


class LLMClient:
    """Multi-provider LLM client with automatic model fallback."""

    def __init__(self, base_url: str, model: str, api_key: str,
                 quality: bool = False) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.quality = quality
        self._fallback_chain = _build_fallback_chain(model, quality=quality)
        self._client = httpx.Client(timeout=_TIMEOUT)
        # Track which models are temporarily exhausted (daily limit) — process-wide
        self._exhausted = _global_exhausted

        chain_names = [f"{e.name} ({e.provider})" for e in self._fallback_chain]
        log.info("Fallback chain (%s): %s",
                 "quality" if quality else "fast", " -> ".join(chain_names))

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        """Send a chat completion request with automatic cross-provider fallback."""
        # Qwen3 optimization
        if "qwen" in self.model.lower() and messages:
            first = messages[0]
            if first.get("role") == "user" and not first["content"].startswith("/no_think"):
                messages = [{"role": first["role"], "content": f"/no_think\n{first['content']}"}] + messages[1:]

        # Build list of models to try: skip recently exhausted ones
        now = time.time()
        cooldown = _quota_cooldown_sec()
        entries_to_try = [
            e for e in self._fallback_chain
            if e.name not in self._exhausted or (now - self._exhausted[e.name]) > cooldown
        ]
        if not entries_to_try:
            # Soft reset only entries whose cooldown fully elapsed; else wait a bit
            self._exhausted = {
                k: v for k, v in self._exhausted.items()
                if (now - v) <= cooldown
            }
            # Keep shared dict in sync when we filter locally
            _global_exhausted.clear()
            _global_exhausted.update(self._exhausted)
            self._exhausted = _global_exhausted
            entries_to_try = [
                e for e in self._fallback_chain
                if e.name not in self._exhausted
            ] or list(self._fallback_chain)

        for idx, entry in enumerate(entries_to_try):
            is_last = (idx == len(entries_to_try) - 1)
            result = self._try_entry(entry, messages, temperature, max_tokens, is_last)
            if result is not None:
                return result
            # Brief pause before next model after a hard failure (quota/503)
            if not is_last:
                time.sleep(min(3.0, _min_interval_sec() or 3.0))

        raise RuntimeError(
            f"All models exhausted after trying: "
            f"{[e.name for e in entries_to_try]}. "
            "Wait a few minutes for rate limits to reset, "
            "or set OPENAI_API_KEY / raise LLM_MIN_INTERVAL_SEC."
        )

    def _try_entry(self, entry: ModelEntry, messages: list[dict],
                   temperature: float, max_tokens: int,
                   is_last: bool = False) -> str | None:
        """Try a single model entry. Dispatches to the right provider."""
        if entry.provider == "cursor":
            return self._try_cursor(entry, messages, is_last=is_last)
        if entry.provider == "anthropic":
            return self._try_anthropic(entry, messages, temperature, max_tokens, is_last)
        return self._try_openai_compat(entry, messages, temperature, max_tokens, is_last)

    def _try_cursor(self, entry: ModelEntry, messages: list[dict],
                    is_last: bool = False) -> str | None:
        """Call Cursor Agent SDK (text-only / ask mode)."""
        _pace_request()
        prompt = _messages_to_prompt(messages)
        try:
            agent = _get_cursor_agent(entry.name, entry.api_key)
            with _cursor_agent_lock:
                run = agent.send(prompt)
                text = _extract_assistant_text(run)
            if not text:
                if not is_last:
                    log.warning("cursor/%s empty response, trying next", entry.name)
                    return None
                raise RuntimeError(f"Empty response from cursor/{entry.name}")
            if entry.name != self.model:
                log.info("Used fallback cursor/%s (primary: %s)", entry.name, self.model)
            return text
        except Exception as e:
            err = str(e)
            low = err.lower()
            usage_hit = any(
                tok in low
                for tok in (
                    "out of usage",
                    "increase limits",
                    "rate limit",
                    "usage",
                    "quota",
                    "429",
                )
            )
            if usage_hit:
                cooldown = _quota_cooldown_sec()
                log.warning(
                    "cursor/%s usage/limit — cooling %.0fs, trying next: %s",
                    entry.name, cooldown, err[:160],
                )
                self._exhausted[entry.name] = time.time()
                return None
            if not is_last:
                log.warning("cursor/%s failed, trying next: %s", entry.name, err[:160])
                return None
            raise

    def _try_openai_compat(self, entry: ModelEntry, messages: list[dict],
                           temperature: float, max_tokens: int,
                           is_last: bool = False) -> str | None:
        """Try an OpenAI-compatible endpoint (Gemini, OpenAI, local)."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {entry.api_key}",
        }
        # DeepSeek deepseek-chat has an 8192 max output token limit
        if entry.provider == "deepseek":
            max_tokens = min(max_tokens, 8192)
        payload = {
            "model": entry.name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        for attempt in range(_MAX_RETRIES):
            _pace_request()
            try:
                resp = self._client.post(
                    f"{entry.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 402:
                    # Payment Required — account out of credits; mark exhausted for 1 hour
                    log.warning("%s/%s payment required (402), marking exhausted for 1h",
                                entry.provider, entry.name)
                    self._exhausted[entry.name] = time.time() + 3600 - 300  # 1h from now
                    return None

                if resp.status_code == 400:
                    body = resp.text.lower()
                    if "api_key_invalid" in body or "api key expired" in body:
                        log.warning("%s/%s API key invalid/expired, trying next",
                                    entry.provider, entry.name)
                        self._exhausted[entry.name] = time.time()
                        return None
                    # Any other 400 (content safety, model not found, malformed prompt)
                    # — don't mark exhausted (it's per-request, not a quota), just skip
                    if not is_last:
                        log.warning("%s/%s 400 Bad Request, trying next: %.120s",
                                    entry.provider, entry.name, resp.text)
                        return None

                if resp.status_code == 404:
                    log.warning("%s/%s model not found (404), trying next",
                                entry.provider, entry.name)
                    self._exhausted[entry.name] = time.time()
                    return None

                if resp.status_code == 429:
                    body = resp.text.lower()
                    retry_after = resp.headers.get("retry-after")
                    try:
                        hinted = float(retry_after) if retry_after else None
                    except ValueError:
                        hinted = None

                    # Hard quota / daily limit — cool this model down, try next
                    if "resource has been exhausted" in body or "quota" in body:
                        cooldown = _quota_cooldown_sec()
                        log.warning(
                            "%s/%s hit quota/429 — cooling %.0fs, trying next",
                            entry.provider, entry.name, cooldown,
                        )
                        self._exhausted[entry.name] = time.time()
                        time.sleep(min(hinted or 8.0, 30.0))
                        return None

                    # Soft RPM limit — back off then retry same model
                    if attempt < _MAX_RETRIES - 1:
                        wait = hinted if hinted is not None else (15 * (2 ** attempt))
                        wait = max(5.0, min(wait, 90.0))
                        log.warning("%s/%s 429 (RPM), retry in %.0fs (%d/%d)",
                                    entry.provider, entry.name, wait,
                                    attempt + 1, _MAX_RETRIES)
                        time.sleep(wait)
                        continue
                    elif not is_last:
                        log.warning("%s/%s still 429, trying next model",
                                    entry.provider, entry.name)
                        self._exhausted[entry.name] = time.time()
                        return None
                    else:
                        resp.raise_for_status()

                if resp.status_code == 503:
                    # Capacity blip — hop to next model immediately (8s same-model
                    # retries were burning throughput while lite was flaky).
                    soft_cool = 45.0
                    self._exhausted[entry.name] = (
                        time.time() - (_quota_cooldown_sec() - soft_cool)
                    )
                    if not is_last:
                        log.warning(
                            "%s/%s 503 — soft-cool %.0fs, trying next model",
                            entry.provider, entry.name, soft_cool,
                        )
                        time.sleep(1.0)
                        return None
                    if attempt < 1:
                        wait = 3
                        log.warning("%s/%s 503 (last model), retry in %ds",
                                    entry.provider, entry.name, wait)
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()

                resp.raise_for_status()
                data = resp.json()
                # Guard against malformed responses (null body, null choices, null content)
                if not isinstance(data, dict) or not data.get("choices"):
                    if not is_last:
                        log.warning("%s/%s: malformed response (no choices), trying next",
                                    entry.provider, entry.name)
                        return None
                    raise RuntimeError(
                        f"Malformed response from {entry.provider}/{entry.name}: "
                        f"no choices in {type(data).__name__}"
                    )
                text = data["choices"][0]["message"]["content"]
                if text is None:
                    # Model returned null content (refusal, tool_call, etc.)
                    if not is_last:
                        log.warning("%s/%s: null content in response, trying next",
                                    entry.provider, entry.name)
                        return None
                    raise RuntimeError(
                        f"Null content from {entry.provider}/{entry.name} "
                        f"(refusal: {data['choices'][0]['message'].get('refusal', 'none')})"
                    )

                if entry.name != self.model:
                    log.info("Used fallback %s/%s (primary: %s)",
                             entry.provider, entry.name, self.model)
                return text

            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    log.warning("%s/%s timeout, retry in %ds",
                                entry.provider, entry.name, wait)
                    time.sleep(wait)
                    continue
                if not is_last:
                    log.warning("%s/%s timeout after retries, trying next",
                                entry.provider, entry.name)
                    return None
                raise

        return None

    def _try_anthropic(self, entry: ModelEntry, messages: list[dict],
                       temperature: float, max_tokens: int,
                       is_last: bool = False) -> str | None:
        """Try the Anthropic Messages API (different format from OpenAI)."""
        headers = {
            "Content-Type": "application/json",
            "x-api-key": entry.api_key,
            "anthropic-version": "2023-06-01",
        }

        # Convert OpenAI message format to Anthropic format
        # Extract system message if present
        system_text = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                api_messages.append({"role": msg["role"], "content": msg["content"]})

        payload: dict = {
            "model": entry.name,
            "messages": api_messages,
            "max_tokens": max_tokens,
        }
        if system_text:
            payload["system"] = system_text
        if temperature > 0:
            payload["temperature"] = temperature

        for attempt in range(_MAX_RETRIES):
            _pace_request()
            try:
                resp = self._client.post(
                    f"{entry.base_url}/v1/messages",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 429:
                    body = resp.text.lower()
                    if "rate_limit" in body or "quota" in body:
                        log.warning("anthropic/%s hit rate limit, trying next", entry.name)
                        self._exhausted[entry.name] = time.time()
                        return None

                    if attempt < _MAX_RETRIES - 1:
                        wait = 2 ** attempt + 1
                        log.warning("anthropic/%s 429, retry in %ds (%d/%d)",
                                    entry.name, wait, attempt + 1, _MAX_RETRIES)
                        time.sleep(wait)
                        continue
                    elif not is_last:
                        return None
                    else:
                        resp.raise_for_status()

                resp.raise_for_status()
                data = resp.json()
                # Anthropic returns content as a list of blocks
                content_blocks = data.get("content") or []
                texts = [
                    b.get("text", "") for b in content_blocks
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                text = "".join(texts)
                if not text:
                    if not is_last:
                        return None
                    raise RuntimeError(f"Empty content from anthropic/{entry.name}")
                if entry.name != self.model:
                    log.info("Used fallback anthropic/%s (primary: %s)",
                             entry.name, self.model)
                return text

            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    log.warning("anthropic/%s timeout, retry in %ds",
                                entry.name, wait)
                    time.sleep(wait)
                    continue
                if not is_last:
                    return None
                raise

        return None

    def ask(self, prompt: str, **kwargs) -> str:
        """Convenience: single user prompt -> assistant response."""
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: LLMClient | None = None
_quality_instance: LLMClient | None = None


def get_client(quality: bool = False) -> LLMClient:
    """Return (or create) the module-level LLMClient singleton.

    Args:
        quality: If True, return a client configured for quality work
                 (resume tailoring, cover letters) with the quality model chain.
    """
    global _instance, _quality_instance

    if quality:
        if _quality_instance is None:
            base_url, model, api_key = _detect_provider(quality=True)
            log.info("LLM quality provider: %s  model: %s", base_url, model)
            _quality_instance = LLMClient(base_url, model, api_key, quality=True)
        return _quality_instance

    if _instance is None:
        base_url, model, api_key = _detect_provider()
        log.info("LLM provider: %s  model: %s", base_url, model)
        _instance = LLMClient(base_url, model, api_key, quality=False)
    return _instance
