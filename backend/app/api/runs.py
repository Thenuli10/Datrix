"""Runs: status, live logs (SSE), results, dashboard payload, thumbnail (PLAN.md §8)."""
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_or_404
from app.core.db import get_session
from app.models import Run
from app.services import orchestrator as orch
from app.services.jobs import log_bus

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}")
def get_run(run_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    return get_or_404(session, Run, run_id).model_dump(mode="json")


@router.get("/{run_id}/logs/stream")
async def stream_logs(run_id: int, session: Session = Depends(get_session)) -> EventSourceResponse:
    run = get_or_404(session, Run, run_id)
    logs_path = Path(run.logs_path) if run.logs_path else None
    finished = run.status in ("COMPLETED", "FAILED")

    async def events():
        async for line in log_bus.subscribe(run_id, logs_path if finished else None):
            yield {"event": "log", "data": line}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(events())


@router.get("/{run_id}/results")
def get_results(run_id: int, session: Session = Depends(get_session)) -> Any:
    run = get_or_404(session, Run, run_id)
    if not run.results_path or not Path(run.results_path).exists():
        raise HTTPException(404, "Results not available yet")
    return json.loads(Path(run.results_path).read_text(encoding="utf-8"))


@router.get("/{run_id}/dashboard")
def get_dashboard(run_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    payload = orch.run_dashboard(session, get_or_404(session, Run, run_id))
    payload["run"] = payload["run"].model_dump(mode="json")
    return payload


@router.get("/{run_id}/thumbnail")
def get_thumbnail(run_id: int, session: Session = Depends(get_session)) -> FileResponse:
    run = get_or_404(session, Run, run_id)
    if not run.thumbnail_path or not Path(run.thumbnail_path).exists():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(run.thumbnail_path, media_type="image/png")
