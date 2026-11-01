"""Results Sanity Checker, Layer 3 (PLAN §7a): LLM review of results vs requirement and plan.
Gets profiles and results only, never raw data."""
from app.agents._common import llm_profile, load_prompt, to_json
from app.llm.base import LLMClient
from app.schemas.checks import SanityIssue, SanityReport
from app.schemas.data import DatasetProfile
from app.schemas.plan import AnalysisPlan
from app.schemas.results import Results

QUESTIONS = 4  # answers the question / follows the plan / insights backed / plausible
_RANK = {"pass": 0, "warn": 1, "fail": 2}


def review(llm: LLMClient, requirement: str, plan: AnalysisPlan, profiles: list[DatasetProfile],
           results: Results, findings: list[SanityIssue], pid: int | None) -> SanityReport:
    user = (f"## Requirement\n{requirement}\n\n## Approved plan\n{to_json(plan)}\n\n"
            f"## Input data profiles\n{to_json([llm_profile(p, 5) for p in profiles])}\n\n"
            f"## results.json\n{to_json(results)}\n\n"
            f"## Layer 1-2 findings (code checks / recalculation)\n{to_json(findings) if findings else '(none)'}")
    rep = llm.structured(agent="sanity", system=load_prompt("sanity"), user=user, schema=SanityReport,
                         project_id=pid)
    for i in rep.issues:
        i.layer = 3
    derived = "fail" if any(i.severity == "high" for i in rep.issues) else "warn" if rep.issues else "pass"
    # the model may escalate, but status can never be milder than its own high-severity issues imply
    rep.status = max(rep.status, derived, key=_RANK.__getitem__) if rep.issues else "pass"
    rep.checks_run = QUESTIONS
    rep.checks_passed = QUESTIONS - min(QUESTIONS, len({i.check for i in rep.issues}))
    return rep
