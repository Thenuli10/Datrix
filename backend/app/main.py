"""FastAPI entry point: `uvicorn app.main:app --reload` from backend/."""
import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import pipelines, projects, runs, usage
from app.core.config import settings
from app.core.db import init_db
from app.llm.base import LLMBudgetExceeded
from app.services.jobs import log_bus
from app.services.locks import ProjectBusy
from app.services.orchestrator import WorkflowError, fail_interrupted_runs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    fail_interrupted_runs()  # never auto-resume runs (and their LLM spend) after a crash/reload
    log_bus.loop = asyncio.get_running_loop()
    yield


app = FastAPI(title="Datrix — Adaptive Data Analysis Platform", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(WorkflowError)
async def workflow_error(_: Request, exc: WorkflowError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ProjectBusy)
async def project_busy(_: Request, exc: ProjectBusy) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(LLMBudgetExceeded)
async def budget_exceeded(_: Request, exc: LLMBudgetExceeded) -> JSONResponse:
    return JSONResponse(status_code=402, content={"detail": str(exc)})


app.include_router(projects.router)
app.include_router(runs.router)
app.include_router(pipelines.router)
app.include_router(usage.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
