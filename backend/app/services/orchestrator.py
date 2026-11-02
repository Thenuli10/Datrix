"""Workflow orchestrator: the project state machine (PLAN.md §3, §4).

DRAFT → REQUIREMENTS_READY → DATA_UPLOADED → DATA_VALIDATED → PLAN_PROPOSED
      → PLAN_APPROVED → RUNNING → COMPLETED (Pipeline saved) | FAILED
COMPLETED → (new data) → RERUNNING → COMPLETED

Request-time steps (analyze, validate, plan) are synchronous and called from the API
in a worker thread. Runs (`execute_first_run`, `execute_rerun`) are long and are
submitted to the JobRunner; they stream progress through the LogBus.
"""
import json
import logging
import shutil
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
from sqlmodel import Session, select

from app.agents import analyst, automap, coder, composer, dashboard_qa, insights, planner, sanity, validator
from app.checks import dashboard_rules, run_compare, sanity_rules
from app.core.config import settings
from app.core.db import engine
from app.llm import get_llm
from app.llm.base import LLMBudgetExceeded, llm_run_scope
from app.models import (
    DataSpecRow, Dataset, Message, Pipeline, Plan, Project, ProjectStatus, Run, RunStatus, Validation,
)
from app.models.tables import utcnow
from app.schemas import (
    AnalysisPlan, ColumnMapping, ContractCheckResult, DashboardIssue, DashboardQAReport, DashboardSpec,
    DataContract, DataSpec, DatasetProfile, RequirementAnalysis, Results, SanityIssue, SanityReport,
    SpotCheck, ValidationReport,
)
from app.services import contract as contract_svc
from app.services import drift as drift_svc
from app.services import profiler, screenshot, storage
from app.services.inputs import prepare_inputs
from app.services.jobs import log_bus
from app.sandbox import manager as sandbox

log = logging.getLogger(__name__)


class WorkflowError(Exception):
    """A user-facing error: wrong state or missing prerequisite."""


ACTIVE_RUN = (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.CHECKING)
INTERRUPTED = "Interrupted by server restart"


# ---------------------------------------------------------------- helpers

def _session() -> Session:
    """Worker-thread session; objects stay readable after the `with` block closes."""
    return Session(engine, expire_on_commit=False)


def _latest(session: Session, model: Any, project_id: int) -> Any:
    return session.exec(
        select(model).where(model.project_id == project_id).order_by(model.id.desc())  # type: ignore[attr-defined]
    ).first()


def _datasets(session: Session, ids: list[int]) -> list[Dataset]:
    rows = {d.id: d for d in session.exec(select(Dataset).where(Dataset.id.in_(ids))).all()}  # type: ignore[union-attr]
    return [rows[i] for i in ids if i in rows]


def _load_df(ds: Dataset) -> pd.DataFrame:
    return profiler.load_dataframe(Path(ds.file_path), ds.file_type)


def _profiles(datasets: list[Dataset]) -> list[DatasetProfile]:
    return [DatasetProfile.model_validate(d.profile_json) for d in datasets if d.profile_json]


def _set_status(session: Session, project: Project, status: ProjectStatus) -> None:
    project.status = status
    session.add(project)
    session.commit()
    session.refresh(project)


def _date_range(profiles: list[DatasetProfile]) -> tuple[str, str] | None:
    lo: str | None = None
    hi: str | None = None
    for p in profiles:
        for c in p.columns:
            if c.inferred_type in ("date", "datetime") and c.min is not None and c.max is not None:
                lo = str(c.min) if lo is None else min(lo, str(c.min))
                hi = str(c.max) if hi is None else max(hi, str(c.max))
    return (lo, hi) if lo and hi else None


class RunContext:
    """Updates a run's stage in the DB and streams log lines."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id

    def log(self, line: str) -> None:
        log_bus.publish(self.run_id, line)

    def stage(self, text: str, status: RunStatus | None = None) -> None:
        with _session() as s:
            run = s.get(Run, self.run_id)
            assert run is not None
            run.stage = text
            if status:
                run.status = status
            s.add(run)
            s.commit()
        self.log(f"[stage] {text}")


# ---------------------------------------------------------------- stage 1

def analyze_requirement(session: Session, project: Project) -> RequirementAnalysis:
    msgs = session.exec(select(Message).where(Message.project_id == project.id).order_by(Message.id)).all()
    analysis = analyst.analyze(
        get_llm(), project.requirement_text, project.context_json,
        [(m.role, m.content) for m in msgs], project.id,
    )
    project.analysis_json = analysis.model_dump()
    prev = _latest(session, DataSpecRow, project.id)
    session.add(DataSpecRow(
        project_id=project.id, spec_json=analysis.data_spec.model_dump(),
        version=(prev.version + 1) if prev else 1,
    ))
    if analysis.clarifying_questions and not analysis.ready:
        session.add(Message(project_id=project.id, role="assistant",
                            content="\n".join(f"- {q}" for q in analysis.clarifying_questions)))
    if project.status in (ProjectStatus.DRAFT, ProjectStatus.REQUIREMENTS_READY):
        project.status = ProjectStatus.REQUIREMENTS_READY if analysis.ready else ProjectStatus.DRAFT
    session.add(project)
    session.commit()
    session.refresh(project)
    return analysis


def answer_message(session: Session, project: Project, text: str) -> RequirementAnalysis:
    session.add(Message(project_id=project.id, role="user", content=text))
    session.commit()
    return analyze_requirement(session, project)


def data_spec(session: Session, project_id: int) -> DataSpec:
    row = _latest(session, DataSpecRow, project_id)
    if not row:
        raise WorkflowError("No data spec yet: analyse the requirement first.")
    return DataSpec.model_validate(row.spec_json)


# ---------------------------------------------------------------- stage 2

def add_dataset(session: Session, project: Project, file_name: str, data: bytes,
                purpose: str = "initial") -> Dataset:
    ext = Path(file_name).suffix.lower().lstrip(".")
    file_type = {"csv": "csv", "txt": "csv", "tsv": "csv", "xlsx": "xlsx", "xls": "xlsx",
                 "parquet": "parquet", "pq": "parquet", "json": "json", "jsonl": "json"}.get(ext)
    if not file_type:
        raise WorkflowError(f"Unsupported file type '.{ext}'. Use CSV, Excel, Parquet or JSON.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise WorkflowError(f"File larger than {settings.max_upload_mb} MB.")
    ds = Dataset(project_id=project.id, original_name=file_name, file_path="", file_type=file_type, purpose=purpose)
    session.add(ds)
    session.commit()
    session.refresh(ds)
    path = storage.upload_path(project.id, ds.id, ext)
    path.write_bytes(data)
    ds.file_path = str(path)
    try:
        ds.profile_json = profiler.profile_file(path, file_type, ds.id, file_name).model_dump(mode="json")
    except Exception as e:
        session.delete(ds)
        session.commit()
        path.unlink(missing_ok=True)
        raise WorkflowError(f"Could not read '{file_name}': {e}") from e
    session.add(ds)
    if purpose == "initial" and project.status in (
            ProjectStatus.DRAFT, ProjectStatus.REQUIREMENTS_READY, ProjectStatus.DATA_VALIDATED):
        project.status = ProjectStatus.DATA_UPLOADED
        session.add(project)
    session.commit()
    session.refresh(ds)
    return ds


def project_datasets(session: Session, project_id: int, purpose: str = "initial") -> list[Dataset]:
    return list(session.exec(select(Dataset).where(
        Dataset.project_id == project_id, Dataset.purpose == purpose).order_by(Dataset.id)).all())


def validate(session: Session, project: Project, dataset_ids: list[int] | None = None) -> Validation:
    spec = data_spec(session, project.id)
    datasets = _datasets(session, dataset_ids) if dataset_ids else project_datasets(session, project.id)
    if not datasets:
        raise WorkflowError("Upload at least one file first.")
    dfs = {d.id: _load_df(d) for d in datasets}
    report = validator.validate(get_llm(), spec, _profiles(datasets), dfs, project.id)
    v = Validation(
        project_id=project.id, dataset_ids=[d.id for d in datasets], status=report.status,
        gap_report_json=report.model_dump(), column_mapping_json=[m.model_dump() for m in report.mapping],
    )
    session.add(v)
    project.status = ProjectStatus.DATA_UPLOADED if report.status == "needs_more_data" else ProjectStatus.DATA_VALIDATED
    session.add(project)
    session.commit()
    session.refresh(v)
    return v


def update_mapping(session: Session, project: Project, mapping: list[ColumnMapping]) -> Validation:
    v = _latest(session, Validation, project.id)
    if not v:
        raise WorkflowError("Validate the data first.")
    v.column_mapping_json = [m.model_dump() for m in mapping]
    report = ValidationReport.model_validate(v.gap_report_json)
    report.mapping = mapping
    mapped = {m.spec_column for m in mapping}
    spec = data_spec(session, project.id)
    # The user fixed missing-column blockers by mapping them manually.
    report.gaps = [g for g in report.gaps if not (g.kind == "missing_column" and g.column in mapped)]
    missing = [c.name for c in spec.columns if c.required and c.name not in mapped]
    if not missing and report.status == "needs_more_data" and not any(g.severity == "blocker" for g in report.gaps):
        report.status = "ready_with_warnings" if report.gaps else "ready"
    v.gap_report_json = report.model_dump()
    v.status = report.status
    session.add(v)
    if report.status != "needs_more_data" and project.status == ProjectStatus.DATA_UPLOADED:
        project.status = ProjectStatus.DATA_VALIDATED
        session.add(project)
    session.commit()
    session.refresh(v)
    return v


# ---------------------------------------------------------------- stage 3

def propose_plan(session: Session, project: Project) -> Plan:
    v = _latest(session, Validation, project.id)
    if not v or v.status == "needs_more_data":
        raise WorkflowError("Data is not validated yet.")
    if not project.analysis_json:
        raise WorkflowError("Requirement not analysed yet.")
    report = ValidationReport.model_validate(v.gap_report_json)
    analysis = RequirementAnalysis.model_validate(project.analysis_json)
    analysis.data_spec = data_spec(session, project.id)
    plan = planner.plan(get_llm(), project.requirement_text, analysis, report,
                        _profiles(_datasets(session, v.dataset_ids)), project.id)
    row = Plan(project_id=project.id, path=plan.path, plan_json=plan.model_dump())
    session.add(row)
    _set_status(session, project, ProjectStatus.PLAN_PROPOSED)
    session.refresh(row)
    return row


def ensure_no_active_run(session: Session, project_id: int) -> None:
    """One run per project at a time: a duplicate approve/re-run must not start a second (paid) run."""
    active = session.exec(select(Run).where(Run.project_id == project_id,
                                            Run.status.in_(ACTIVE_RUN))).first()  # type: ignore[attr-defined]
    if active:
        raise WorkflowError(f"Run #{active.id} is still {active.status.lower()} for this project; "
                            "wait for it to finish.")


def fail_interrupted_runs() -> int:
    """Startup: runs left QUEUED/RUNNING/CHECKING by a crash or reload have no worker any more.
    Mark them FAILED (never auto-resume: that would spend LLM credits unasked)."""
    with _session() as s:
        stuck = s.exec(select(Run).where(Run.status.in_(ACTIVE_RUN))).all()  # type: ignore[attr-defined]
        for run in stuck:
            run.status, run.error, run.stage, run.finished_at = RunStatus.FAILED, INTERRUPTED, "Failed", utcnow()
            s.add(run)
            project = s.get(Project, run.project_id)
            if project and project.status in (ProjectStatus.PLAN_APPROVED, ProjectStatus.RUNNING,
                                              ProjectStatus.RERUNNING):
                project.status = ProjectStatus.COMPLETED if _has_pipeline(s, project.id) else ProjectStatus.FAILED
                s.add(project)
        s.commit()
    if stuck:
        log.warning("marked %d interrupted run(s) as FAILED", len(stuck))
    return len(stuck)


def approve_plan(session: Session, project: Project, edited: AnalysisPlan | None = None) -> Run:
    ensure_no_active_run(session, project.id)
    row = _latest(session, Plan, project.id)
    if not row:
        raise WorkflowError("No plan to approve.")
    if edited:
        row.plan_json = edited.model_dump()
        row.path = edited.path
    row.approved = True
    session.add(row)
    v = _latest(session, Validation, project.id)
    run = Run(project_id=project.id, dataset_ids=v.dataset_ids if v else [],
              mode="train" if row.path == "ml" else "script", stage="Queued")
    session.add(run)
    project.status = ProjectStatus.PLAN_APPROVED
    session.add(project)
    session.commit()
    session.refresh(run)
    return run


# ---------------------------------------------------------------- stage 4-5: first run

def _canonical_profiles(input_dir: Path) -> tuple[dict[str, Any], list[DatasetProfile]]:
    manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    profiles = []
    for i, f in enumerate(manifest["files"]):
        p = Path(f["path"])
        p = p if p.is_absolute() else input_dir / p
        profiles.append(profiler.profile_file(p, "parquet", -(i + 1), f["name"]))
    return manifest, profiles


def _sandbox_runner(ctx: RunContext, entry: str, input_dir: Path, output_dir: Path,
                    model_dir: Path | None, params: dict[str, Any]):
    def run_fn(code: str) -> sandbox.SandboxResult:
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        ctx.log("[sandbox] starting container")
        return sandbox.run_in_sandbox(code, entry, input_dir, output_dir, params, model_dir, on_log=ctx.log)
    return run_fn


def _spot_checks(ctx: RunContext, spot_code: str | None, input_dir: Path, work_dir: Path,
                 results: Results) -> list[SanityIssue]:
    if not spot_code:
        return []
    try:
        raw = sandbox.run_spot_check(spot_code, input_dir, work_dir)
        items = raw.get("checks", raw) if isinstance(raw, dict) else raw
        spots = [SpotCheck.model_validate(x) for x in items]
        ctx.log(f"[sanity] {len(spots)} spot-check(s) recalculated")
        return sanity_rules.compare_spot_checks(spots, results)
    except Exception as e:  # a broken spot-check must not block results
        ctx.log(f"[sanity] spot-check failed: {e}")
        return [SanityIssue(severity="low", check="spot_check", layer=2, message=f"Spot-check could not run: {e}")]


def _layer12(ctx: RunContext, results: Results, plan: AnalysisPlan, input_rows: int,
             date_range: tuple[str, str] | None, spot_code: str | None, input_dir: Path,
             work_dir: Path) -> tuple[list[SanityIssue], int, int]:
    issues, run_n, passed = sanity_rules.run_layer1(results, input_rows, date_range, plan)
    spot = _spot_checks(ctx, spot_code, input_dir, work_dir, results)
    run_n += 1 if spot_code else 0
    passed += 1 if spot_code and not spot else 0
    return issues + spot, run_n, passed


def _merge_report(code_issues: list[SanityIssue], run_n: int, passed: int,
                  llm_report: SanityReport | None) -> SanityReport:
    issues = list(code_issues)
    if llm_report:
        issues += [i.model_copy(update={"layer": 3}) for i in llm_report.issues]
        run_n += 1
        passed += 1 if llm_report.status == "pass" else 0
    return sanity_rules.summarize(issues, run_n, passed)


def _format_issues(issues: list[SanityIssue]) -> str:
    return "\n".join(f"- [{i.severity}] {i.check}: {i.message}" + (f" Fix: {i.suggested_fix}" if i.suggested_fix else "")
                     for i in issues)


def _compose_dashboard(ctx: RunContext, run_id: int, run_dir: Path, results: Results,
                       plan: AnalysisPlan, project_id: int, previous: DashboardSpec | None = None,
                       quick: bool = False) -> tuple[DashboardSpec, DashboardQAReport]:
    """Composer → rule checks → screenshot + vision review → fix loop (§7b)."""
    llm = get_llm()
    if quick and previous:
        spec = previous
    else:
        spec = _cosmetic(ctx, "composer", lambda: composer.compose(llm, results, plan, project_id),
                         lambda: composer.default_spec(results, plan.title))
    all_issues: list[DashboardIssue] = []
    shots: list[str] = []
    rounds = 0
    # QA round r reviews the current spec; rounds 1..max_dashboard_qa_rounds may send it back to the
    # composer, the final round only verifies the last fix: <= 1 + max rounds composer and vision calls.
    for rounds in range(1, settings.max_dashboard_qa_rounds + 2):
        spec, rule_issues = dashboard_rules.check_and_fix(spec, results)
        _write_json(run_dir / "dashboard.json", spec.model_dump())
        open_issues = [i for i in rule_issues if not i.auto_fixed]
        all_issues = list(rule_issues)
        if quick and not open_issues:
            break  # repeat runs: screenshot review only if a rule fails
        dom_issues: list[DashboardIssue] = []
        vision: list[DashboardIssue] = []
        if settings.screenshots_enabled:
            ctx.stage(f"Checking dashboard layout (round {rounds})")
            paths, dom_issues = screenshot.capture(run_id, run_dir / "screenshots")
            shots = [str(p) for p in paths]
            if paths:
                vision = _cosmetic(ctx, "dashboard vision review", lambda: dashboard_qa.review(
                    llm, spec, [p.read_bytes() for p in paths], rule_issues + dom_issues, project_id), list)
        all_issues += dom_issues + vision
        # DOM checks measure the real page, so medium+ findings get a fix. The vision model produced false
        # positives in live runs, so only its `high` findings cost a composer round; the rest are warnings.
        open_issues += [i for i in dom_issues if i.severity in ("high", "medium")]
        open_issues += [i for i in vision if i.severity == "high"]
        if not open_issues or rounds > settings.max_dashboard_qa_rounds:
            break
        ctx.log(f"[dashboard] {len(open_issues)} issue(s); asking the composer to fix")
        fixed = _cosmetic(ctx, "composer fix", lambda: composer.compose(
            llm, results, plan, project_id, qa_issues=open_issues, previous=spec), lambda: None)
        if fixed is None:
            break  # keep the rule-checked spec we have
        spec = fixed
    worst = {i.severity for i in all_issues if not i.auto_fixed}
    status = "fail" if "high" in worst else "warn" if "medium" in worst else "pass"
    return spec, DashboardQAReport(status=status, issues=all_issues, rounds=rounds, screenshots=shots)


def _cosmetic(ctx: RunContext, what: str, call: Callable[[], Any], fallback: Callable[[], Any]) -> Any:
    """Dashboard and insights steps must never fail a run whose results are already checked (§13):
    on any error (incl. a spend cap) use the free, deterministic fallback."""
    try:
        return call()
    except Exception as e:  # noqa: BLE001
        log.warning("%s failed, using fallback: %s", what, e)
        ctx.log(f"[warn] {what} failed ({type(e).__name__}: {str(e)[:200]}); using fallback")
        return fallback()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _finish_run(run_id: int, **fields: Any) -> None:
    with _session() as s:
        run = s.get(Run, run_id)
        assert run is not None
        for k, v in fields.items():
            setattr(run, k, v)
        run.finished_at = utcnow()
        s.add(run)
        project = s.get(Project, run.project_id)
        if project:
            ok = run.status == RunStatus.COMPLETED
            # A failed re-run leaves the saved pipeline usable, so the project stays COMPLETED.
            project.status = ProjectStatus.COMPLETED if ok or _has_pipeline(s, project.id) else ProjectStatus.FAILED
            if ok and run.thumbnail_path:
                project.thumbnail_path = run.thumbnail_path
            s.add(project)
        s.commit()
    log_bus.close(run_id)


def _has_pipeline(s: Session, project_id: int) -> bool:
    return s.exec(select(Pipeline).where(Pipeline.project_id == project_id)).first() is not None


def _fail(run_id: int, ctx: RunContext, msg: str) -> None:
    ctx.log(f"::error:: {msg}")
    _finish_run(run_id, status=RunStatus.FAILED, error=msg, stage="Failed")


def _guarded(run_id: int, body: Callable[[int, RunContext], None]) -> None:
    """Run `body(run_id, ctx)` with LLM spend attributed to the run; any error fails the run once."""
    ctx = RunContext(run_id)
    try:
        with llm_run_scope(run_id):
            body(run_id, ctx)
    except LLMBudgetExceeded as e:  # a cap was hit: stop here, no retries, no further LLM calls
        log.warning("run %s stopped: %s", run_id, e)
        _fail(run_id, ctx, str(e))
    except Exception as e:
        log.exception("run %s failed", run_id)
        ctx.log(traceback.format_exc())
        _fail(run_id, ctx, f"{type(e).__name__}: {e}")


def execute_first_run(run_id: int) -> None:
    _guarded(run_id, _execute_first_run)


def _execute_first_run(run_id: int, ctx: RunContext) -> None:
    llm = get_llm()
    with _session() as s:
        run = s.get(Run, run_id)
        assert run is not None
        project = s.get(Project, run.project_id)
        assert project is not None
        pid = project.id
        plan_row = _latest(s, Plan, pid)
        plan = AnalysisPlan.model_validate(plan_row.plan_json)
        v = _latest(s, Validation, pid)
        report = ValidationReport.model_validate(v.gap_report_json)
        mapping = [ColumnMapping.model_validate(m) for m in v.column_mapping_json]
        datasets = _datasets(s, run.dataset_ids)
        spec = data_spec(s, pid)
        requirement = project.requirement_text
        run_dir = storage.run_dir(pid, run_id)
        run.logs_path = str(run_dir / "logs.txt")
        run.status = RunStatus.RUNNING
        run.started_at = utcnow()
        s.add(run)
        project.status = ProjectStatus.RUNNING
        s.add(project)
        s.commit()
    log_bus.attach_file(run_id, run_dir / "logs.txt")

    ctx.stage("Preparing input data", RunStatus.RUNNING)
    frames = [(d.original_name, _load_df(d)) for d in datasets]
    ids = [d.id for d in datasets]
    input_dir = run_dir / "input"
    prepare_inputs(frames, mapping, report.joins, input_dir, dataset_ids=ids, spec=spec)
    manifest, canon_profiles = _canonical_profiles(input_dir)
    input_rows = max((f.get("rows", 0) for f in manifest["files"]), default=0)
    date_range = _date_range(canon_profiles)

    output_dir = run_dir / "output"
    model_dir = run_dir / "model" if plan.path == "ml" else None
    if model_dir:
        model_dir.mkdir(parents=True, exist_ok=True)
    entry = "train" if plan.path == "ml" else "run"
    run_fn = _sandbox_runner(ctx, entry, input_dir, output_dir, model_dir, {})

    feedback: str | None = None
    code: str | None = None
    spot_code: str | None = None
    report_s: SanityReport | None = None
    results: Results | None = None
    # 1 initial generation + at most max_sanity_rounds fix rounds; each runs fix_loop (<= max_fix_attempts calls)
    for rnd in range(settings.max_sanity_rounds + 1):
        ctx.stage("Generating analysis code" if rnd == 0 else f"Fixing results (round {rnd})")
        code, res = coder.fix_loop(llm, plan, canon_profiles, manifest, pid, run_fn,
                                   on_log=ctx.log, feedback=feedback, previous_code=code)
        if not res.ok:
            return _fail(run_id, ctx, f"Code failed after {settings.max_fix_attempts} attempts: {res.error or res.stderr[-500:]}")
        results = Results.model_validate(res.results)

        ctx.stage("Checking results", RunStatus.CHECKING)
        if spot_code is None:
            try:
                spot_code = coder.generate_spot_check(llm, plan, results, manifest, pid)
            except LLMBudgetExceeded:
                raise
            except Exception as e:
                ctx.log(f"[sanity] could not generate spot-check: {e}")
                spot_code = ""
        code_issues, run_n, passed = _layer12(ctx, results, plan, input_rows, date_range, spot_code,
                                              input_dir, run_dir / "spot")
        llm_report = sanity.review(llm, requirement, plan, canon_profiles, results, code_issues, pid)
        report_s = _merge_report(code_issues, run_n, passed, llm_report)
        ctx.log(f"[sanity] {report_s.status}: {report_s.checks_passed}/{report_s.checks_run} checks passed")
        if report_s.status != "fail" or rnd == settings.max_sanity_rounds:
            break
        feedback = "The results failed sanity checks. Fix these issues:\n" + _format_issues(
            [i for i in report_s.issues if i.severity == "high"])
    assert results is not None and report_s is not None and code is not None

    # Save the pipeline (versioned) before the dashboard so the render page can read it.
    with _session() as s:
        prev = s.exec(select(Pipeline).where(Pipeline.project_id == pid).order_by(Pipeline.version.desc())).first()
        for p in s.exec(select(Pipeline).where(Pipeline.project_id == pid, Pipeline.active == True)).all():  # noqa: E712
            p.active = False
            s.add(p)
        version = (prev.version + 1) if prev else 1
        pdir = storage.pipeline_dir(pid, version)
        (pdir / "code.py").write_text(code, encoding="utf-8")
        if spot_code:
            (pdir / "spot_check.py").write_text(spot_code, encoding="utf-8")
        model_path = None
        if model_dir and any(model_dir.iterdir()):
            shutil.copytree(model_dir, pdir / "model", dirs_exist_ok=True)
            model_path = str(pdir / "model")
        contract = contract_svc.freeze_contract(frames, report, spec, dataset_ids=ids)
        _write_json(pdir / "contract.json", contract.model_dump())
        training_profile = None
        if plan.path == "ml":
            canon = [pd.read_parquet(input_dir / Path(f["path"]).name) for f in manifest["files"]]
            training_profile = drift_svc.training_profile(canon[0])
        pipe = Pipeline(project_id=pid, version=version, path=plan.path, code_path=str(pdir / "code.py"),
                        spot_check_path=str(pdir / "spot_check.py") if spot_code else None,
                        model_path=model_path, contract_json=contract.model_dump(),
                        training_profile_json=training_profile)
        s.add(pipe)
        s.commit()
        s.refresh(pipe)
        pipeline_id = pipe.id
        run = s.get(Run, run_id)
        run.pipeline_id = pipeline_id
        run.results_path = str(output_dir / "results.json")
        run.metrics_json = results.model.metrics if results.model else None
        run.sanity_json = report_s.model_dump()
        s.add(run)
        s.commit()

    ctx.stage("Composing dashboard", RunStatus.CHECKING)
    dash, qa = _compose_dashboard(ctx, run_id, run_dir, results, plan, pid)
    ctx.stage("Writing insights")
    md = _cosmetic(ctx, "insights", lambda: insights.write(llm, requirement, results, pid),
                   lambda: _quick_insights(results))
    with _session() as s:
        pipe = s.get(Pipeline, pipeline_id)
        pipe.dashboard_spec_json = dash.model_dump()
        _write_json(Path(pipe.code_path).parent / "dashboard.json", dash.model_dump())
        s.add(pipe)
        s.commit()
    _finish_run(run_id, status=RunStatus.COMPLETED, stage="Completed", dashboard_qa_json=qa.model_dump(),
                insights_md=md, thumbnail_path=qa.screenshots[0] if qa.screenshots else None)
    ctx.log("[done] pipeline saved")


# ---------------------------------------------------------------- stage 6: repeat runs

def rerun(session: Session, pipeline: Pipeline, dataset_ids: list[int], mode: str, data_mode: str,
          mapping_override: dict[str, str] | None = None) -> Run:
    """mode: predict | retrain | script. data_mode: replace | append."""
    ensure_no_active_run(session, pipeline.project_id)
    if pipeline.path == "script":
        mode = "script"
    elif mode not in ("predict", "retrain"):
        raise WorkflowError("For ML pipelines choose 'predict' or 'retrain'.")
    run = Run(project_id=pipeline.project_id, pipeline_id=pipeline.id, dataset_ids=dataset_ids,
              mode="train" if mode == "retrain" else mode, stage="Queued",
              contract_check_json={"data_mode": data_mode, "mapping_override": mapping_override or {}})
    session.add(run)
    project = session.get(Project, pipeline.project_id)
    project.status = ProjectStatus.RERUNNING
    session.add(project)
    session.commit()
    session.refresh(run)
    return run


def _previous_run(s: Session, run: Run) -> Run | None:
    return s.exec(select(Run).where(Run.project_id == run.project_id, Run.status == RunStatus.COMPLETED,
                                    Run.id < run.id).order_by(Run.id.desc())).first()


def suggest_mapping(session: Session, pipeline: Pipeline, dataset_ids: list[int]) -> dict[str, str]:
    contract = DataContract.model_validate(pipeline.contract_json)
    return automap.suggest_mapping(get_llm(), contract, _profiles(_datasets(session, dataset_ids)),
                                   pipeline.project_id)


def execute_rerun(run_id: int) -> None:
    _guarded(run_id, _execute_rerun)


def _execute_rerun(run_id: int, ctx: RunContext) -> None:
    with _session() as s:
        run = s.get(Run, run_id)
        pipe = s.get(Pipeline, run.pipeline_id)
        project = s.get(Project, run.project_id)
        pid = project.id
        requirement = project.requirement_text
        opts = run.contract_check_json or {}
        data_mode = opts.get("data_mode", "replace")
        override = opts.get("mapping_override") or None
        contract = DataContract.model_validate(pipe.contract_json)
        plan = AnalysisPlan.model_validate(_latest(s, Plan, pid).plan_json)
        new_ds = _datasets(s, run.dataset_ids)
        prev_run = _previous_run(s, run)
        # Append mode builds on the previous run's canonical inputs (which already hold earlier appends).
        prev_input = storage.run_dir(pid, prev_run.id) / "input" if prev_run and data_mode == "append" else None
        prev_results = (Results.model_validate_json(Path(prev_run.results_path).read_text(encoding="utf-8"))
                        if prev_run and prev_run.results_path and Path(prev_run.results_path).exists() else None)
        dash_spec = DashboardSpec.model_validate(pipe.dashboard_spec_json) if pipe.dashboard_spec_json else None
        run_dir = storage.run_dir(pid, run_id)
        run.logs_path = str(run_dir / "logs.txt")
        run.status = RunStatus.RUNNING
        run.started_at = utcnow()
        s.add(run)
        s.commit()
        pipe_snapshot = pipe.model_copy()
    log_bus.attach_file(run_id, run_dir / "logs.txt")

    ctx.stage("Checking data contract", RunStatus.RUNNING)
    frames = [(d.original_name, _load_df(d)) for d in new_ds]
    appending = prev_input is not None and (prev_input / "manifest.json").exists()
    # Appending: a small top-up file is fine; the minimum row count applies to the combined data below.
    check: ContractCheckResult = contract_svc.check_contract(contract, frames, override,
                                                             min_rows=0 if appending else None)
    check_json = check.model_dump() | {"data_mode": data_mode, "mapping_override": override or {}}
    with _session() as s:
        r = s.get(Run, run_id)
        r.contract_check_json = check_json
        s.add(r)
        s.commit()
    for i in check.issues:
        ctx.log(f"[contract] {i.severity}: {i.message}")
    if not check.ok:
        return _fail(run_id, ctx, "New data does not match the pipeline's data contract.")

    canon = contract_svc.apply_mapping(contract, frames, override)
    if appending:
        prev_manifest = json.loads((prev_input / "manifest.json").read_text(encoding="utf-8"))
        old = [pd.read_parquet(prev_input / f["path"]) for f in prev_manifest["files"]]
        canon = contract_svc.append_datasets(old, canon)
        ctx.log(f"[data] appended to previous data: {' + '.join(str(len(df)) for df in canon)} rows per file")
        if max(len(df) for df in canon) < contract.min_rows:
            return _fail(run_id, ctx, f"Combined data has fewer than {contract.min_rows} rows.")
    input_dir = run_dir / "input"
    prepare_inputs(list(zip(contract.files, canon)), None, contract.joins, input_dir, contract=contract)
    manifest, canon_profiles = _canonical_profiles(input_dir)
    input_rows = max((f.get("rows", 0) for f in manifest["files"]), default=0)

    if pipe_snapshot.path == "ml" and pipe_snapshot.training_profile_json:
        canon = pd.read_parquet(input_dir / Path(manifest["files"][0]["path"]).name)
        drift = drift_svc.check_drift(pipe_snapshot.training_profile_json, canon)
        with _session() as s:
            r = s.get(Run, run_id)
            r.drift_json = drift.model_dump()
            s.add(r)
            s.commit()
        if drift.drifted:
            ctx.log("[drift] data distribution has shifted: " + ", ".join(c.column for c in drift.columns if c.drifted))

    code = Path(pipe_snapshot.code_path).read_text(encoding="utf-8")
    output_dir = run_dir / "output"
    with _session() as s:
        mode = s.get(Run, run_id).mode
    if mode == "train":
        entry, model_dir = "train", run_dir / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
    elif mode == "predict":
        entry, model_dir = "predict", Path(pipe_snapshot.model_path) if pipe_snapshot.model_path else None
    else:
        entry, model_dir = "run", None
    ctx.stage("Running saved pipeline")
    res = _sandbox_runner(ctx, entry, input_dir, output_dir, model_dir, {})(code)
    if not res.ok:
        return _fail(run_id, ctx, f"Saved pipeline failed on the new data: {res.error or res.stderr[-500:]}")
    results = Results.model_validate(res.results)

    ctx.stage("Quick sanity check", RunStatus.CHECKING)
    spot_code = (Path(pipe_snapshot.spot_check_path).read_text(encoding="utf-8")
                 if pipe_snapshot.spot_check_path and Path(pipe_snapshot.spot_check_path).exists() else None)
    code_issues, run_n, passed = _layer12(ctx, results, plan, input_rows, _date_range(canon_profiles),
                                          spot_code, input_dir, run_dir / "spot")
    if prev_results:
        cmp = run_compare.compare(prev_results, results)
        code_issues += cmp
        run_n += 1
        passed += 0 if cmp else 1
    flagged = any(i.severity in ("high", "medium") for i in code_issues)
    llm_report = sanity.review(get_llm(), requirement, plan, canon_profiles, results, code_issues, pid) if flagged else None
    report_s = _merge_report(code_issues, run_n, passed, llm_report)
    ctx.log(f"[sanity] {report_s.status}: {report_s.checks_passed}/{report_s.checks_run} checks passed")

    pipeline_id = pipe_snapshot.id
    if mode == "train":  # retrain → new pipeline version with the same code and a fresh model
        with _session() as s:
            old = s.get(Pipeline, pipe_snapshot.id)
            old.active = False
            last = s.exec(select(Pipeline).where(Pipeline.project_id == pid).order_by(Pipeline.version.desc())).first()
            pdir = storage.pipeline_dir(pid, last.version + 1)
            for name in ("code.py", "spot_check.py", "contract.json"):
                src = Path(old.code_path).parent / name
                if src.exists():
                    shutil.copy2(src, pdir / name)
            shutil.copytree(model_dir, pdir / "model", dirs_exist_ok=True)
            canon = pd.read_parquet(input_dir / Path(manifest["files"][0]["path"]).name)
            new = Pipeline(project_id=pid, version=last.version + 1, path=old.path, code_path=str(pdir / "code.py"),
                           spot_check_path=str(pdir / "spot_check.py") if old.spot_check_path else None,
                           model_path=str(pdir / "model"), contract_json=old.contract_json,
                           dashboard_spec_json=old.dashboard_spec_json,
                           training_profile_json=drift_svc.training_profile(canon))
            s.add(old)
            s.add(new)
            s.commit()
            s.refresh(new)
            pipeline_id = new.id
            ctx.log(f"[pipeline] retrained → version {new.version}")

    with _session() as s:
        r = s.get(Run, run_id)
        r.pipeline_id = pipeline_id
        r.results_path = str(output_dir / "results.json")
        r.metrics_json = results.model.metrics if results.model else None
        r.sanity_json = report_s.model_dump()
        s.add(r)
        s.commit()

    ctx.stage("Refreshing dashboard", RunStatus.CHECKING)
    dash, qa = _compose_dashboard(ctx, run_id, run_dir, results, plan, pid, previous=dash_spec, quick=True)
    md = (_cosmetic(ctx, "insights", lambda: insights.write(get_llm(), requirement, results, pid),
                    lambda: _quick_insights(results)) if flagged or llm_report else _quick_insights(results))
    _finish_run(run_id, status=RunStatus.COMPLETED, stage="Completed", dashboard_qa_json=qa.model_dump(),
                insights_md=md, thumbnail_path=qa.screenshots[0] if qa.screenshots else None)
    ctx.log("[done] re-run complete")


def _quick_insights(results: Results) -> str:
    """Repeat runs use no LLM unless a check flags something: list the code's own insights."""
    lines = [f"- {s}" for s in results.insights_raw] or ["- No new insights reported."]
    return "## Key insights\n\n" + "\n".join(lines)


# ---------------------------------------------------------------- reads

def run_dashboard(session: Session, run: Run) -> dict[str, Any]:
    """Everything the dashboard page needs in one payload."""
    results = None
    if run.results_path and Path(run.results_path).exists():
        results = json.loads(Path(run.results_path).read_text(encoding="utf-8"))
    spec = None
    run_spec = storage.run_dir(run.project_id, run.id) / "dashboard.json"
    if run_spec.exists():
        spec = json.loads(run_spec.read_text(encoding="utf-8"))
    elif run.pipeline_id:
        pipe = session.get(Pipeline, run.pipeline_id)
        spec = pipe.dashboard_spec_json if pipe else None
    return {"run": run, "spec": spec, "results": results, "sanity": run.sanity_json,
            "dashboard_qa": run.dashboard_qa_json, "insights_md": run.insights_md,
            "contract_check": run.contract_check_json, "drift": run.drift_json}
