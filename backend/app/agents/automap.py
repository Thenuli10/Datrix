"""Auto-mapper for repeat runs: map contract source columns that are missing from new
uploads onto the new files' columns. Exact/normalized matches are resolved without the LLM."""
import re

from pydantic import BaseModel, Field

from app.agents._common import llm_profile, load_prompt, to_json
from app.core.config import settings
from app.llm.base import LLMClient
from app.schemas.data import DataContract, DatasetProfile


class MappingPair(BaseModel):
    source_column: str = Field(description="Column name from the data contract")
    new_column: str = Field(description="Matching column in the new upload")
    reason: str = ""


class MappingSuggestion(BaseModel):
    pairs: list[MappingPair] = Field(default_factory=list)


def _norm(name: str) -> str:
    return re.sub(r"[^0-9a-z]", "", name.lower())


def suggest_mapping(llm: LLMClient, contract: DataContract, profiles: list[DatasetProfile],
                    pid: int | None) -> dict[str, str]:
    """contract source column -> new column, only for columns that changed name."""
    def new_cols(idx: int) -> list[str]:
        return [c.name for c in profiles[idx].columns] if idx < len(profiles) else []

    mapping: dict[str, str] = {}
    missing = []
    for c in contract.columns:
        cols = new_cols(c.dataset_index)
        if c.source_column in cols:
            continue
        exact = [n for n in cols if _norm(n) == _norm(c.source_column)]
        if len(exact) == 1:
            mapping[c.source_column] = exact[0]
        else:
            missing.append(c)
    if not missing:
        return mapping

    user = (f"## Contract columns needing a match\n"
            f"{to_json([c.model_dump(mode='json') for c in missing])}\n\n"
            f"## New upload profiles (files in contract order)\n{to_json([llm_profile(p, 5) for p in profiles])}\n\n"
            f"## Already mapped\n{to_json(mapping)}")
    out = llm.structured(agent="automap", system=load_prompt("automap"), user=user, schema=MappingSuggestion,
                         project_id=pid, model=settings.openai_small_model)
    wanted = {c.source_column: c for c in missing}
    used = set(mapping.values())
    for p in out.pairs:
        c = wanted.get(p.source_column)
        if c and p.new_column in new_cols(c.dataset_index) and p.new_column not in used \
                and p.source_column not in mapping:
            mapping[p.source_column] = p.new_column
            used.add(p.new_column)
    return mapping
