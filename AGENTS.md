# ApplyPilot — Cursor Agent Operating Manual (Harsh Rajput)

## Mission

Autonomous job applications for Harsh: discover → score → tailor → cover → **apply via Cursor Agent SDK** (not Claude Code). Target ~100 applies/day across three tracks.

## Tracks

| Track | Meaning | Sponsorship answers |
|-------|---------|---------------------|
| `india` | India office / India-remote / hybrid India | **No** |
| `us_transfer` | US remote or US-transfer employers | **Yes** |
| `remote_35lpa` | Fully remote ≥35 LPA (~$42k USD) | Auto (India/worldwide → No; US-only → Yes) |

Company research: `../companies/india_remote_dream.md`, `../companies/us_transfer_focus.md`.

## Your role (Cursor)

Operate the pipeline. Do **not** manually fill ATS forms in chat — that is `applypilot apply` spawning local Cursor Agents with Playwright MCP.

### Daily loop

```bash
cd ApplyPilot
source .venv/bin/activate   # or project venv

# First-time / refresh seed from curated queue
python scripts/seed_harsh_queue.py

# Full day
./scripts/daily_apply.sh

# Overnight (park HITL blockers, keep going)
./scripts/daily_apply.sh --overnight

# Smoke one URL without submit
applypilot apply --dry-run --url 'https://job-boards.greenhouse.io/...'
```

### Required secrets (`~/.applypilot/.env`)

- `CURSOR_API_KEY` — apply stage **and** score/tailor/cover LLM (`LLM_PROVIDER=cursor`)
- `CAPSOLVER_API_KEY` — CAPTCHAs
- Optional: `GEMINI_API_KEY` / `OPENAI_API_KEY` as LLM fallbacks when Cursor usage is exhausted

Set `LLM_PROVIDER=cursor` (default in `daily_apply.sh`) and `LLM_MODEL=default` (Cursor Auto).
Composer models (`composer-2.5`) need paid usage; Auto/`default` works on included quota.

### Profile & resume

- Profile: `~/.applypilot/profile.json` (vault copy: `config/harsh/profile.json`)
- Resume PDF: `~/.applypilot/resume.pdf` ← `../resume/master/HarshRajput_resume.pdf`
- Searches: `~/.applypilot/searches.yaml`
- Q&A seed: `applypilot qa import config/harsh/qa_seed.yaml`

## Apply runtime

- Executor: `applypilot.apply.cursor_runtime` → local `cursor-sdk` Agent + `@playwright/mcp` on each worker CDP port
- Default apply model: `default` (Cursor Auto). Override with `--model` / `APPLY_MODEL` / `LLM_MODEL`
- Start with `--workers 2`, scale to 3–5 when stable
- CapSolver: agent prompt + `applypilot.apply.captcha_solver`

## Ground truth

- Never invent salary, visa, dates, employers, or metrics
- India roles: sponsorship No; US/EU: Yes
- Comp floor: ~35 LPA / $42k; never below 30 LPA / $40k
- ~3 YOE — skip clear 8+/10+ YOE requirements

## Status commands

```bash
applypilot status
applypilot dashboard
applypilot qa list
applypilot track          # if Gmail OAuth configured
applypilot serve          # operator HTTP API on :8080
```

### Operator UI

- SPA: `cd web && npm install && npm run dev` (proxies `/api` → API)
- Docker: `cp .env.example .env && docker compose up --build` → UI `:3000`, API `:8080`
- Set `APPLYPILOT_API_TOKEN` and paste it in the UI sidebar
- Compose keeps `APPLY_MODE=off` — run Chrome apply on the host with `applypilot apply`
