"""LLM spend caps (settings.llm_*), summed from the `llm_calls` table.

`check_budget` runs before every OpenAI request (inside OpenAIClient, so no agent can
bypass it). Concurrent requests may each pass the check, so a cap can be overshot by
at most one call per in-flight request (bounded by the output-token caps)."""
from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import settings
from app.llm.base import LLMBudgetExceeded
from app.models.tables import LLMCall


def _today_start() -> datetime:
    return datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)


def _totals(s: Session, *where: Any) -> tuple[float, int]:
    cost, calls = s.exec(select(func.coalesce(func.sum(LLMCall.cost), 0.0), func.count(LLMCall.id))
                         .where(*where)).one()
    return float(cost), int(calls)


def _exceeded(cap: str, spent: str, limit: str, env: str) -> LLMBudgetExceeded:
    return LLMBudgetExceeded(
        f"OpenAI budget cap reached: {cap} ({spent} of {limit}). No request was sent. "
        f"Raise {env} in backend/.env and restart the backend to continue.")


def check_budget(project_id: int | None, run_id: int | None) -> None:
    """Raise LLMBudgetExceeded if any cap is reached (or spend cannot be read: fail closed)."""
    from app.core.db import engine

    try:
        with Session(engine) as s:
            today, _ = _totals(s, LLMCall.created_at >= _today_start())
            project = _totals(s, LLMCall.project_id == project_id) if project_id is not None else (0.0, 0)
            run, _ = _totals(s, LLMCall.run_id == run_id) if run_id is not None else (0.0, 0)
    except Exception as e:  # noqa: BLE001 - never spend money we cannot account for
        raise LLMBudgetExceeded(f"Could not read LLM spend from the database ({e}); no request was sent.") from e
    if today >= settings.llm_daily_budget_usd:
        raise _exceeded("daily budget", f"${today:.4f}", f"${settings.llm_daily_budget_usd:.2f}",
                        "LLM_DAILY_BUDGET_USD")
    if project[0] >= settings.llm_max_cost_per_project_usd:
        raise _exceeded(f"per-project cost for project {project_id}", f"${project[0]:.4f}",
                        f"${settings.llm_max_cost_per_project_usd:.2f}", "LLM_MAX_COST_PER_PROJECT_USD")
    if project[1] >= settings.llm_max_calls_per_project:
        raise _exceeded(f"calls for project {project_id}", f"{project[1]} calls",
                        f"{settings.llm_max_calls_per_project}", "LLM_MAX_CALLS_PER_PROJECT")
    if run >= settings.llm_max_cost_per_run_usd:
        raise _exceeded(f"per-run cost for run {run_id}", f"${run:.4f}", f"${settings.llm_max_cost_per_run_usd:.2f}",
                        "LLM_MAX_COST_PER_RUN_USD")


def usage_summary(s: Session) -> dict[str, Any]:
    """Today's spend, per-project totals and the configured limits (GET /usage)."""
    today_cost, today_calls = _totals(s, LLMCall.created_at >= _today_start())
    rows = s.exec(select(LLMCall.project_id, func.sum(LLMCall.cost), func.count(LLMCall.id))
                  .group_by(LLMCall.project_id)).all()
    return {
        "fake": settings.llm_fake or not settings.openai_api_key,
        "today": {"cost_usd": round(today_cost, 6), "calls": today_calls},
        "projects": [{"project_id": pid, "cost_usd": round(float(c or 0), 6), "calls": int(n)} for pid, c, n in rows],
        "limits": {
            "daily_budget_usd": settings.llm_daily_budget_usd,
            "max_cost_per_project_usd": settings.llm_max_cost_per_project_usd,
            "max_cost_per_run_usd": settings.llm_max_cost_per_run_usd,
            "max_calls_per_project": settings.llm_max_calls_per_project,
        },
    }
