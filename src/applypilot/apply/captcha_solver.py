# CapSolver integration for reCAPTCHA v2 / Enterprise on ATS pages.
# Prefer calling solve_recaptcha + inject_token_js from the apply agent
# (via browser_evaluate) or from launcher helpers that evaluate JS over CDP.

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Any, Callable

from applypilot import config

CAPSOLVER_API = "https://api.capsolver.com"

log = logging.getLogger("applypilot.apply.captcha_solver")

# JS snippet for CapSolver token injection (browser_evaluate / CDP Runtime.evaluate)
INJECT_TOKEN_JS_TEMPLATE = """(() => {{
  const token = {token_json};
  const areas = [
    ...document.querySelectorAll('textarea[name=g-recaptcha-response], #g-recaptcha-response, textarea[id*=recaptcha]')
  ];
  for (const ta of areas) {{
    ta.style.display = 'block';
    ta.value = token;
    ta.innerHTML = token;
    ta.dispatchEvent(new Event('input', {{bubbles: true}}));
    ta.dispatchEvent(new Event('change', {{bubbles: true}}));
  }}
  let ent = document.querySelector('input[name=g-recaptcha-enterprise-token], textarea[name=g-recaptcha-enterprise-token]');
  if (!ent) {{
    ent = document.createElement('input');
    ent.type = 'hidden';
    ent.name = 'g-recaptcha-enterprise-token';
    document.body.appendChild(ent);
  }}
  ent.value = token;

  let callbackFired = false;
  const tryCallback = (fn) => {{
    if (typeof fn === 'function') {{
      try {{ fn(token); callbackFired = true; }} catch (e) {{}}
    }}
  }};
  document.querySelectorAll('[data-callback]').forEach(el => {{
    const name = el.getAttribute('data-callback');
    if (name && typeof window[name] === 'function') tryCallback(window[name]);
  }});
  try {{
    const clients = window.___grecaptcha_cfg && ___grecaptcha_cfg.clients;
    if (clients) {{
      const visit = (o, depth) => {{
        if (!o || depth > 6) return;
        if (typeof o === 'function') {{ tryCallback(o); return; }}
        if (typeof o === 'object') {{
          for (const [k, v] of Object.entries(o)) {{
            if (/callback/i.test(k) && typeof v === 'function') tryCallback(v);
            else visit(v, depth + 1);
          }}
        }}
      }};
      for (const id of Object.keys(clients)) visit(clients[id], 0);
    }}
  }} catch (e) {{}}
  return {{filled: areas.length, tokenLen: token.length, callbackFired}};
}})()"""

DETECT_RECAPTCHA_JS = """(() => {
  const url = location.href;
  let sitekey = null;
  let enterprise = false;
  let invisible = false;
  const el = document.querySelector('.g-recaptcha[data-sitekey], [data-sitekey]');
  if (el) {
    sitekey = el.getAttribute('data-sitekey');
    enterprise = /enterprise/i.test(el.className + (el.getAttribute('data-size')||''));
    invisible = el.getAttribute('data-size') === 'invisible';
  }
  const iframe = document.querySelector('iframe[src*=recaptcha]');
  if (!sitekey && iframe && iframe.src) {
    try {
      const u = new URL(iframe.src);
      sitekey = u.searchParams.get('k');
      enterprise = /enterprise/i.test(iframe.src);
    } catch (e) {}
  }
  try {
    if (!sitekey && window.___grecaptcha_cfg && ___grecaptcha_cfg.clients) {
      const clients = ___grecaptcha_cfg.clients;
      for (const id of Object.keys(clients)) {
        const c = clients[id];
        const dig = (o, depth) => {
          if (!o || depth > 5) return null;
          if (typeof o === 'string' && /^6L/.test(o)) return o;
          if (typeof o === 'object') {
            for (const v of Object.values(o)) {
              const hit = dig(v, depth + 1);
              if (hit) return hit;
            }
          }
          return null;
        };
        sitekey = dig(c, 0) || sitekey;
      }
    }
  } catch (e) {}
  if (/enterprise/i.test(document.body.innerHTML.slice(0, 50000))) enterprise = true;
  const hcaptcha = !!(document.querySelector('iframe[src*=hcaptcha], .h-captcha, [data-hcaptcha-widget-id]'));
  const present = !!(sitekey || iframe || document.querySelector('textarea[name=g-recaptcha-response]'));
  return {url, sitekey, enterprise, invisible, present, hcaptcha};
})()"""


def api_key() -> str:
    config.load_env()
    key = os.environ.get("CAPSOLVER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("CAPSOLVER_API_KEY missing in ~/.applypilot/.env")
    return key


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{CAPSOLVER_API}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def inject_token_js(token: str) -> str:
    """Return browser_evaluate JS that injects a solved reCAPTCHA token."""
    return INJECT_TOKEN_JS_TEMPLATE.format(token_json=json.dumps(token))


def solve_recaptcha(
    website_url: str,
    website_key: str,
    *,
    enterprise: bool = False,
    invisible: bool = False,
    timeout_sec: int = 180,
) -> str:
    """Return gRecaptchaResponse token from CapSolver."""
    task_type = (
        "ReCaptchaV2EnterpriseTaskProxyLess" if enterprise else "ReCaptchaV2TaskProxyLess"
    )
    task: dict[str, Any] = {
        "type": task_type,
        "websiteURL": website_url,
        "websiteKey": website_key,
    }
    if invisible:
        task["isInvisible"] = True

    t0 = time.time()
    log.info(
        "CapSolver createTask type=%s enterprise=%s invisible=%s key=%s…",
        task_type,
        enterprise,
        invisible,
        website_key[:12],
    )
    created = _post("/createTask", {"clientKey": api_key(), "task": task})
    if created.get("errorId"):
        raise RuntimeError(f"CapSolver createTask: {created}")
    task_id = created.get("taskId")
    if not task_id:
        raise RuntimeError(f"CapSolver no taskId: {created}")

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        time.sleep(2.5)
        res = _post("/getTaskResult", {"clientKey": api_key(), "taskId": task_id})
        if res.get("errorId"):
            raise RuntimeError(f"CapSolver getTaskResult: {res}")
        if res.get("status") == "ready":
            sol = res.get("solution") or {}
            token = sol.get("gRecaptchaResponse") or sol.get("token")
            if not token:
                raise RuntimeError(f"CapSolver empty solution: {res}")
            log.info(
                "CapSolver ready task=%s latency=%.1fs tokenLen=%d",
                task_id,
                time.time() - t0,
                len(token),
            )
            return token
    raise TimeoutError(f"CapSolver timeout after {timeout_sec}s task={task_id}")


def solve_and_inject(
    *,
    evaluate: Callable[[str], Any],
    retries: int = 2,
) -> dict[str, Any]:
    """Detect via evaluate(DETECT_RECAPTCHA_JS), solve, inject via evaluate(inject_token_js).

    ``evaluate`` should run JS in the page context and return the expression result
    (dict for detect / inject).
    """
    last_err: str | None = None
    meta: dict[str, Any] = {}
    for attempt in range(1, retries + 1):
        raw = evaluate(DETECT_RECAPTCHA_JS)
        meta = raw if isinstance(raw, dict) else {}
        if meta.get("hcaptcha") and not meta.get("sitekey"):
            log.warning("hCaptcha present — prefer agent CapSolver hCaptcha path or HITL")
            return {
                "ok": False,
                "error": "hcaptcha_unsupported",
                "blocker": "hcaptcha",
                "meta": meta,
            }
        if not meta.get("present"):
            return {"ok": True, "skipped": True, "meta": meta}
        sitekey = meta.get("sitekey")
        if not sitekey:
            return {"ok": False, "error": "no_sitekey", "meta": meta}
        try:
            token = solve_recaptcha(
                meta.get("url") or "",
                sitekey,
                enterprise=bool(meta.get("enterprise")),
                invisible=bool(meta.get("invisible")),
            )
            inj = evaluate(inject_token_js(token))
            return {"ok": True, "attempt": attempt, "meta": meta, "inject": inj}
        except Exception as e:
            last_err = str(e)
            log.warning("CapSolver attempt %d failed: %s", attempt, last_err)
            time.sleep(1)
    return {"ok": False, "error": last_err or "solve_failed", "meta": meta}
