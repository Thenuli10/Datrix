"""Projects: requirement chat, data spec, datasets, validation, plan (PLAN.md §8)."""
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.deps import get_or_404
from app.core.db import get_session
from app.models import Dataset, Message, Pipeline, Plan, Project, Run, Validation
from app.schemas import AnalysisPlan, ColumnMapping
from app.services import orchestrator as orch
from app.services import profiler
from app.services.jobs import jobs

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    requirement: str = Field(min_length=3)
    name: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)  # domain, goal, time_horizon


class MessageIn(BaseModel):
    content: str = Field(min_length=1)


class MappingIn(BaseModel):
    mapping: list[ColumnMapping]


class ApproveIn(BaseModel):
    plan: AnalysisPlan | None = None


def _detail(session: Session, p: Project) -> dict[str, Any]:
    msgs = session.exec(select(Message).where(Message.project_id == p.id).order_by(Message.id)).all()
    latest_run = session.exec(select(Run).where(Run.project_id == p.id).order_by(Run.id.desc())).first()
    pipe = session.exec(select(Pipeline).where(Pipeline.project_id == p.id, Pipeline.active == True)  # noqa: E712
                        .order_by(Pipeline.version.desc())).first()
    return p.model_dump(mode="json") | {
        "analysis": p.analysis_json,
        "messages": [m.model_dump(mode="json") for m in msgs],
        "latest_run_id": latest_run.id if latest_run else None,
        "latest_run_status": latest_run.status if latest_run else None,
        "pipeline_id": pipe.id if pipe else None,
    }


@router.post("")
def create_project(body: ProjectCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    name = body.name or (body.requirement[:60] + ("…" if len(body.requirement) > 60 else ""))
    p = Project(name=name, requirement_text=body.requirement, context_json=body.context)
    session.add(p)
    session.commit()
    session.refresh(p)
    orch.analyze_requirement(session, p)
    return _detail(session, p)


@router.get("")
def list_projects(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_detail(session, p) for p in session.exec(select(Project).order_by(Project.id.desc())).all()]


@router.get("/{project_id}")
def get_project(project_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    return _detail(session, get_or_404(session, Project, project_id))


@router.post("/{project_id}/messages")
def post_message(project_id: int, body: MessageIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    p = get_or_404(session, Project, project_id)
    orch.answer_message(session, p, body.content)
    return _detail(session, p)


@router.get("/{project_id}/data-spec")
def get_data_spec(project_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    get_or_404(session, Project, project_id)
    return orch.data_spec(session, project_id).model_dump(mode="json")


@router.get("/{project_id}/data-spec/template.csv", response_class=PlainTextResponse)
def template_csv(project_id: int, session: Session = Depends(get_session)) -> PlainTextResponse:
    get_or_404(session, Project, project_id)
    return PlainTextResponse(
        profiler.template_csv(orch.data_spec(session, project_id)), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="project-{project_id}-template.csv"'},
    )


@router.post("/{project_id}/datasets")
async def upload_datasets(project_id: int, files: list[UploadFile] = File(...),
                          session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    p = get_or_404(session, Project, project_id)
    out = []
    for f in files:
        ds = orch.add_dataset(session, p, f.filename or "upload.csv", await f.read())
        out.append(ds.model_dump(mode="json"))
    return out


@router.get("/{project_id}/datasets")
def list_datasets(project_id: int, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    get_or_404(session, Project, project_id)
    return [d.model_dump(mode="json") for d in orch.project_datasets(session, project_id)]


@router.delete("/{project_id}/datasets/{dataset_id}")
def delete_dataset(project_id: int, dataset_id: int, session: Session = Depends(get_session)) -> dict[str, bool]:
    ds = get_or_404(session, Dataset, dataset_id)
    if ds.project_id == project_id:
        session.delete(ds)
        session.commit()
    return {"ok": True}


@router.post("/{project_id}/validate")
def validate(project_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    return orch.validate(session, get_or_404(session, Project, project_id)).model_dump(mode="json")


@router.get("/{project_id}/validation")
def get_validation(project_id: int, session: Session = Depends(get_session)) -> dict[str, Any] | None:
    v = session.exec(select(Validation).where(Validation.project_id == project_id).order_by(Validation.id.desc())).first()
    return v.model_dump(mode="json") if v else None


@router.put("/{project_id}/column-mapping")
def put_mapping(project_id: int, body: MappingIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    p = get_or_404(session, Project, project_id)
    return orch.update_mapping(session, p, body.mapping).model_dump(mode="json")


@router.post("/{project_id}/plan")
def make_plan(project_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    return orch.propose_plan(session, get_or_404(session, Project, project_id)).model_dump(mode="json")


@router.get("/{project_id}/plan")
def get_plan(project_id: int, session: Session = Depends(get_session)) -> dict[str, Any] | None:
    row = session.exec(select(Plan).where(Plan.project_id == project_id).order_by(Plan.id.desc())).first()
    return row.model_dump(mode="json") if row else None


@router.post("/{project_id}/plan/approve")
def approve_plan(project_id: int, body: ApproveIn | None = None,
                 session: Session = Depends(get_session)) -> dict[str, Any]:
    run = orch.approve_plan(session, get_or_404(session, Project, project_id), body.plan if body else None)
    jobs.submit(orch.execute_first_run, run.id)
    return run.model_dump(mode="json")


@router.get("/{project_id}/runs")
def project_runs(project_id: int, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    runs = session.exec(select(Run).where(Run.project_id == project_id).order_by(Run.id.desc())).all()
    return [r.model_dump(mode="json") for r in runs]
