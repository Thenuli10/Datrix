"""SQLModel tables (PLAN.md §6). JSON payloads are stored as JSON columns and
validated against the Pydantic schemas in app.schemas at the edges."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlmodel import JSON, Column, Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectStatus(StrEnum):
    DRAFT = "DRAFT"
    REQUIREMENTS_READY = "REQUIREMENTS_READY"
    DATA_UPLOADED = "DATA_UPLOADED"
    DATA_VALIDATED = "DATA_VALIDATED"
    PLAN_PROPOSED = "PLAN_PROPOSED"
    PLAN_APPROVED = "PLAN_APPROVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RERUNNING = "RERUNNING"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CHECKING = "CHECKING"  # sanity checks / dashboard QA
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Project(SQLModel, table=True):
    __tablename__ = "projects"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    status: ProjectStatus = ProjectStatus.DRAFT
    requirement_text: str
    context_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    analysis_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # RequirementAnalysis
    thumbnail_path: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime = Field(default_factory=utcnow)


class DataSpecRow(SQLModel, table=True):
    __tablename__ = "data_specs"
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    spec_json: dict[str, Any] = Field(sa_column=Column(JSON))  # DataSpec
    version: int = 1


class Dataset(SQLModel, table=True):
    __tablename__ = "datasets"
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    original_name: str
    file_path: str
    file_type: str  # csv | xlsx | parquet | json
    purpose: str = "initial"  # "initial" (first run) | "rerun" (uploaded to a saved pipeline)
    profile_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # DatasetProfile
    uploaded_at: datetime = Field(default_factory=utcnow)


class Validation(SQLModel, table=True):
    __tablename__ = "validations"
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    dataset_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    status: str  # ValidationStatus
    gap_report_json: dict[str, Any] = Field(sa_column=Column(JSON))  # ValidationReport
    column_mapping_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class Plan(SQLModel, table=True):
    __tablename__ = "plans"
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    path: str  # "ml" | "script"
    plan_json: dict[str, Any] = Field(sa_column=Column(JSON))  # AnalysisPlan
    approved: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Pipeline(SQLModel, table=True):
    __tablename__ = "pipelines"
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    version: int = 1
    path: str  # "ml" | "script"
    code_path: str | None = None
    spot_check_path: str | None = None  # Layer-2 recalculation script (§7a)
    model_path: str | None = None
    contract_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # DataContract
    dashboard_spec_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # DashboardSpec
    training_profile_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # for drift
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    pipeline_id: int | None = Field(default=None, foreign_key="pipelines.id", index=True)
    dataset_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    mode: str  # "train" | "predict" | "script"
    status: RunStatus = RunStatus.QUEUED
    stage: str = ""  # human-readable current step, e.g. "Generating code (attempt 2)"
    error: str | None = None
    logs_path: str | None = None
    results_path: str | None = None
    metrics_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    sanity_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # SanityReport
    dashboard_qa_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # DashboardQAReport
    contract_check_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # ContractCheckResult
    drift_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))  # DriftReport
    insights_md: str | None = None
    thumbnail_path: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class LLMCall(SQLModel, table=True):
    __tablename__ = "llm_calls"
    id: int | None = Field(default=None, primary_key=True)
    project_id: int | None = Field(default=None, index=True)
    run_id: int | None = Field(default=None, index=True)  # set for calls made inside a run
    agent: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    latency: float = 0.0
    created_at: datetime = Field(default_factory=utcnow, index=True)
