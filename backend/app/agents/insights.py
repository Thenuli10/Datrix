"""Insight Writer: markdown "Key insights" grounded only in results.json."""
from app.agents._common import llm_results, load_prompt, to_json
from app.core.config import settings
from app.llm.base import LLMClient
from app.schemas.results import Results

HEADING = "## Key insights"


def write(llm: LLMClient, requirement: str, results: Results, pid: int | None) -> str:
    user = f"## User's question\n{requirement}\n\n## results.json (long tables/series trimmed)\n{to_json(llm_results(results))}"
    md = llm.text(agent="insights", system=load_prompt("insights"), user=user, project_id=pid,
                  model=settings.openai_small_model).strip()
    if md.startswith("```"):
        md = md.strip("`").removeprefix("markdown").strip()
    if not md:
        md = "\n".join(f"- {s}" for s in results.insights_raw) or "- No insights were produced."
    return md if md.lstrip("# ").lower().startswith("key insights") else f"{HEADING}\n\n{md}"
