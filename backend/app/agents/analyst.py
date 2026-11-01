"""Requirement Analyst (Stage 1): task type, clarifying questions, DataSpec."""
from typing import Any

from app.agents._common import load_prompt, snake_case, to_json
from app.llm.base import LLMClient
from app.schemas.requirement import RequirementAnalysis


def analyze(llm: LLMClient, requirement: str, context: dict[str, Any], messages: list[tuple[str, str]],
            pid: int | None) -> RequirementAnalysis:
    chat = "\n".join(f"[{role}] {text}" for role, text in messages) or "(none yet)"
    user = (f"## Requirement\n{requirement}\n\n## Context\n{to_json(context or {})}\n\n"
            f"## Clarification chat so far\n{chat}")
    out = llm.structured(agent="analyst", system=load_prompt("analyst"), user=user,
                         schema=RequirementAnalysis, project_id=pid)
    return _normalize(out)


def _normalize(a: RequirementAnalysis) -> RequirementAnalysis:
    """snake_case + dedupe spec columns; `ready` is true exactly when no questions remain."""
    seen: set[str] = set()
    cols = []
    for c in a.data_spec.columns:
        c.name = snake_case(c.name)
        if c.name not in seen:
            seen.add(c.name)
            cols.append(c)
    a.data_spec.columns = cols
    a.clarifying_questions = [q.strip() for q in a.clarifying_questions if q.strip()]
    a.ready = not a.clarifying_questions
    return a
