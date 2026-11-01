"""FastAPI entry point: `uvicorn app.main:app --reload` from backend/."""
import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import pipelines, projects, runs
from app.core.config import settings
from app.core.db import init_db
from app.services.jobs import log_bus
from app.services.orchestrator import WorkflowError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    log_bus.loop = asyncio.get_running_loop()
    yield


app = FastAPI(title="Datrix — Adaptive Data Analysis Platform", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(WorkflowError)
async def workflow_error(_: Request, exc: WorkflowError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


app.include_router(projects.router)
app.include_router(runs.router)
app.include_router(pipelines.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
