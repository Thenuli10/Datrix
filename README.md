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
