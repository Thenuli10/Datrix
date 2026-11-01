"""Shared helpers for agents: prompt loading, privacy-capped profiles, JSON rendering."""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.core.config import settings
from app.schemas.data import DatasetProfile

PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache
def load_prompt(name: str) -> str:
    """System prompt from prompts/<name>.md (the leading version comment is kept out)."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return re.sub(r"^\s*<!--.*?-->\s*", "", text, count=1, flags=re.S)


def prompt_version(name: str) -> str:
    m = re.search(r"<!--\s*version:\s*(\S+)\s*-->", (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"))
    return m.group(1) if m else "0"


def to_json(obj: Any, indent: int | None = 1) -> str:
    """JSON for prompts: Pydantic models, lists/dicts of them, anything else via str()."""
    def conv(o: Any) -> Any:
        if isinstance(o, BaseModel):
            return o.model_dump(mode="json")
        if isinstance(o, dict):
            return {str(k): conv(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [conv(v) for v in o]
        return o

    return json.dumps(conv(obj), indent=indent, default=str, ensure_ascii=False)


def llm_profile(p: DatasetProfile, sample_rows: int | None = None) -> dict[str, Any]:
    """Profile safe to send to the LLM: stats + at most `settings.llm_sample_rows` sample rows."""
    cap = settings.llm_sample_rows if sample_rows is None else min(sample_rows, settings.llm_sample_rows)
    d = p.model_dump(mode="json")
    d["sample_rows"] = d["sample_rows"][:cap]
    return d


def snake_case(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name.strip())
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    return s or "col"
