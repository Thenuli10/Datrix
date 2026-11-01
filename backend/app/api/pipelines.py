"""Pipelines: saved artifacts and repeat runs (PLAN.md §3 Stage 6, §8)."""
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlmodel import Session, select

from app.api.deps import get_or_404
from app.core.db import get_session
from app.models import Pipeline, Project, Run
from app.services import orchestrator as orch
from app.services.jobs import jobs
from app.services.locks import project_lock

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


def _summary(session: Session, p: Pipeline) -> dict[str, Any]:
    project = session.get(Project, p.project_id)
    runs = session.exec(select(Run).where(Run.pipeline_id == p.id)).all()
    return p.model_dump(mode="json", exclude={"training_profile_json"}) | {
        "project_name": project.name if project else "",
        "run_count": len(runs),
    }


@router.get("")
def list_pipelines(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.exec(select(Pipeline).order_by(Pipeline.id.desc())).all()
    return [_summary(session, p) for p in rows]


@router.get("/{pipeline_id}")
def get_pipeline(pipeline_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _summary(session, get_or_404(session, Pipeline, pipeline_id))


@router.get("/{pipeline_id}/code")
def get_code(pipeline_id: int, session: Session = Depends(get_session)) -> dict[str, str | None]:
    p = get_or_404(session, Pipeline, pipeline_id)
    read = lambda f: Path(f).read_text(encoding="utf-8") if f and Path(f).exists() else None  # noqa: E731
    return {"code": read(p.code_path), "spot_check": read(p.spot_check_path)}


@router.post("/{pipeline_id}/runs")
async def new_run(
    pipeline_id: int,
    files: list[UploadFile] = File(...),
    mode: Literal["predict", "retrain", "script"] = Form("script"),
    data_mode: Literal["replace", "append"] = Form("replace"),
    mapping_override: str = Form("{}"),  # JSON {contract source column: new column}
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """New data → contract check → run. The check happens inside the job; a failed check
    ends the run as FAILED with `contract_check_json` explaining why."""
    pipe = get_or_404(session, Pipeline, pipeline_id)
    project = get_or_404(session, Project, pipe.project_id)
    orch.ensure_no_active_run(session, project.id)  # before storing uploads
    blobs = [(f.filename or "upload.csv", await f.read()) for f in files]
    with project_lock(project.id, "re-run start"):
        ids = [orch.add_dataset(session, project, name, data, purpose="rerun").id for name, data in blobs]
        run = orch.rerun(session, pipe, ids, mode, data_mode, json.loads(mapping_override or "{}"))
    jobs.submit(orch.execute_rerun, run.id)
    return run.model_dump(mode="json")


@router.post("/{pipeline_id}/runs/{run_id}/retry")
def retry_run(pipeline_id: int, run_id: int, body: dict[str, Any] | None = None,
              session: Session = Depends(get_session)) -> dict[str, Any]:
    """Retry a failed re-run on the same files, optionally with a column-mapping override."""
    pipe = get_or_404(session, Pipeline, pipeline_id)
    old = get_or_404(session, Run, run_id)
    opts = old.contract_check_json or {}
    mode = {"train": "retrain"}.get(old.mode, old.mode)
    with project_lock(pipe.project_id, "re-run start"):
        run = orch.rerun(session, pipe, old.dataset_ids, mode,
                         (body or {}).get("data_mode", opts.get("data_mode", "replace")),
                         (body or {}).get("mapping_override", opts.get("mapping_override")))
    jobs.submit(orch.execute_rerun, run.id)
    return run.model_dump(mode="json")


@router.post("/{pipeline_id}/automap")
def automap(pipeline_id: int, body: dict[str, list[int]], session: Session = Depends(get_session)) -> dict[str, str]:
    """LLM-suggested column mapping for new files that failed the contract check."""
    pipe = get_or_404(session, Pipeline, pipeline_id)
    with project_lock(pipe.project_id, "auto-mapping"):
        return orch.suggest_mapping(session, pipe, body.get("dataset_ids", []))


@router.post("/{pipeline_id}/fork")
def fork(pipeline_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Go back to Stage 3: the project returns to DATA_VALIDATED so a new plan can be made."""
    pipe = get_or_404(session, Pipeline, pipeline_id)
    project = get_or_404(session, Project, pipe.project_id)
    project.status = orch.ProjectStatus.DATA_VALIDATED
    session.add(project)
    session.commit()
    return {"project_id": project.id}


@router.get("/{pipeline_id}/runs")
def pipeline_runs(pipeline_id: int, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    pipe = get_or_404(session, Pipeline, pipeline_id)
    # History spans every version of the project's pipeline, so retrains stay comparable.
    runs = session.exec(select(Run).where(Run.project_id == pipe.project_id).order_by(Run.id.desc())).all()
    out = []
    for r in runs:
        kpis = []
        if r.results_path and Path(r.results_path).exists():
            kpis = json.loads(Path(r.results_path).read_text(encoding="utf-8")).get("kpis", [])
        out.append(r.model_dump(mode="json") | {"kpis": kpis})
    return out
