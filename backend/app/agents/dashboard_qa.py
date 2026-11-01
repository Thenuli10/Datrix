"""Dashboard QA, step 2 (PLAN §7b): vision review of rendered dashboard screenshots."""
from pydantic import BaseModel, Field

from app.agents._common import load_prompt, to_json
from app.core.config import settings
from app.llm.base import LLMClient
from app.schemas.checks import DashboardIssue
from app.schemas.dashboard import DashboardSpec

SCREENSHOT_ORDER = "desktop-light, desktop-dark, mobile-light, mobile-dark (as available)"


class QAIssues(BaseModel):
    """Structured-output wrapper (top level must be an object)."""
    issues: list[DashboardIssue] = Field(default_factory=list)


def review(llm: LLMClient, spec: DashboardSpec, screenshots: list[bytes], findings: list[DashboardIssue],
           pid: int | None) -> list[DashboardIssue]:
    screenshots = screenshots[:settings.llm_max_images]
    if not screenshots:
        return []
    widgets = [{"id": w.id, "type": w.type, "title": w.title, "layout": w.layout.model_dump(), "tab": w.tab}
               for w in spec.widgets]
    user = (f"## Dashboard spec (widget ids)\n{to_json({'title': spec.title, 'widgets': widgets})}\n\n"
            f"## Rule/DOM findings already known (do not repeat)\n{to_json(findings) if findings else '(none)'}\n\n"
            f"{len(screenshots)} screenshots attached, in order: {SCREENSHOT_ORDER}.")
    out = llm.structured(agent="dashboard_qa", system=load_prompt("dashboard_qa"), user=user, schema=QAIssues,
                         project_id=pid, model=settings.openai_vision_model, images=screenshots)
    ids = {w.id for w in spec.widgets}
    for i in out.issues:
        i.auto_fixed = False
        if i.widget_id not in ids:
            i.widget_id = None
        if not i.rule:
            i.rule = "vision"
    return out.issues
