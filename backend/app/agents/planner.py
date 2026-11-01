"""Strategy Planner (Stage 3): ML vs script path and the analysis plan."""
from app.agents._common import llm_profile, load_prompt, to_json
from app.llm.base import LLMClient
from app.schemas.data import DatasetProfile, ValidationReport
from app.schemas.plan import AnalysisPlan
from app.schemas.requirement import RequirementAnalysis

PLAN_SAMPLE_ROWS = 5


def plan(llm: LLMClient, requirement: str, analysis: RequirementAnalysis, report: ValidationReport,
         profiles: list[DatasetProfile], pid: int | None) -> AnalysisPlan:
    user = (f"## Requirement\n{requirement}\n\n## Requirement analysis\n{to_json(analysis)}\n\n"
            f"## Validation report (column mapping: spec_column <- source_column)\n{to_json(report)}\n\n"
            f"## Dataset profiles (source column names)\n"
            f"{to_json([llm_profile(p, PLAN_SAMPLE_ROWS) for p in profiles])}")
    out = llm.structured(agent="planner", system=load_prompt("planner"), user=user,
                         schema=AnalysisPlan, project_id=pid)
    return enforce_rules(out)


def enforce_rules(p: AnalysisPlan) -> AnalysisPlan:
    """Never let the target (or explicitly excluded columns) leak into the features."""
    if p.ml is None:
        if p.path == "ml":
            p.path = "script"
            p.assumptions.append("No ML spec was given, so this runs as a script analysis.")
        return p
    banned = set(p.ml.excluded_columns)
    if p.ml.target:
        banned.add(p.ml.target)
        if p.ml.target not in p.ml.excluded_columns and p.ml.target in p.ml.features:
            p.assumptions.append(f"Removed target '{p.ml.target}' from features.")
    p.ml.features = [f for f in dict.fromkeys(p.ml.features) if f not in banned]
    if not p.ml.baseline.strip():
        p.ml.baseline = {"classification": "majority class", "regression": "mean of target",
                         "forecasting": "last value (naive)", "clustering": "single cluster"}[p.ml.problem]
    return p
