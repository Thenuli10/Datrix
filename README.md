# Datrix — Adaptive Data Analysis Platform

Describe what you want to learn → Datrix says what data it needs → validates your files →
trains an ML model or generates a Python analysis script (run in a locked-down Docker sandbox) →
checks the results → shows an interactive dashboard. The result is saved as a reusable
**Pipeline**: upload new data of the same shape later and get updated results with no LLM calls
unless a check flags something.

- Spec: [PLAN.md](PLAN.md) · module contracts: [INTERFACES.md](INTERFACES.md) · [architecture diagram](architecture.html)

## Layout

| Path | What |
|---|---|
| `backend/` | FastAPI app: API, orchestrator (state machine), agents, code-only checks, sandbox manager |
| `sandbox-image/` | Docker image `analysis-runner:py3.12` + `runner.py` that executes generated code |
| `frontend/` | Next.js 15 app: wizard, data upload & gap report, plan review, live logs, dashboard, pipelines |
| `storage/` | SQLite DB, uploads, pipelines, runs (gitignored) |

## Run locally (Windows / macOS / Linux)

Prerequisites: Python 3.12+, Node 20+, Docker Desktop running, an OpenAI API key.

```bash
# 1. Sandbox image (once)
docker build -t analysis-runner:py3.12 sandbox-image

# 2. Backend
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m playwright install chromium  # dashboard screenshot QA
cp .env.example .env                                  # then set OPENAI_API_KEY
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev                                           # http://localhost:3000
```

Without Docker you can set `SANDBOX_BACKEND=local` in `backend/.env` to run generated code as a
plain subprocess. **That has no isolation**; use it only for development.

## OpenAI spend limits

Every OpenAI request goes through one gateway (`OpenAIClient._call`) that checks the spend logged
in `llm_calls` first. If a cap is reached the request is **not sent**: a run ends `FAILED` with the
reason, and request-time steps (chat, validate, plan, auto-map) return HTTP 402. The nav bar shows
today's estimated spend (`GET /usage`). Defaults suit a ~$5 prepaid balance; change them in
`backend/.env` (see `.env.example`) and restart the backend.

| Setting | Default | Meaning |
|---|---|---|
| `LLM_MAX_COST_PER_RUN_USD` | 0.50 | per first run / re-run |
| `LLM_MAX_COST_PER_PROJECT_USD` | 2.00 | all calls of one project |
| `LLM_DAILY_BUDGET_USD` | 3.00 | all projects, per UTC day |
| `LLM_MAX_CALLS_PER_PROJECT` | 150 | request count per project |
| `LLM_MAX_OUTPUT_TOKENS` / `_OTHER` | 8000 / 4000 | `max_completion_tokens` for code generation / other agents |
| `LLM_MAX_INPUT_CHARS` | 200000 | prompt text per request |
| `LLM_TOOL_MAX_STEPS`, `LLM_TOOL_OUTPUT_CHARS`, `LLM_TOOL_TOTAL_OUTPUT_CHARS` | 8, 8000, 60000 | validator tool loop |
| `LLM_MAX_IMAGES`, `LLM_VISION_DETAIL` | 4, high | dashboard vision review |
| `MAX_FIX_ATTEMPTS`, `MAX_SANITY_ROUNDS`, `MAX_DASHBOARD_QA_ROUNDS` | 4, 2, 2 | agent loop bounds |

Costs are estimates (`PRICES` in `app/llm/openai_client.py`); a cap can be overshot by at most the
one request in flight. Only one run per project can be active, duplicate LLM requests for a busy
project get 409, and runs interrupted by a backend restart are marked `FAILED` (never resumed).

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q          # Docker tests skip if the daemon is down
cd frontend && npm run build && npm run lint
```

Tests use a fake LLM (`LLM_FAKE=true`), so they never call OpenAI.

## Offline demo

`.claude/launch.json` has a `backend-demo` config: fake LLM, local sandbox, data in `storage/demo`.
It exercises the whole UI flow without an API key or Docker, but the fake LLM returns placeholder
specs and plans, so the dashboards it produces are minimal.
