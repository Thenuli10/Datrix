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


LLM_TABLE_ROWS = 20
LLM_SERIES_POINTS = 60
LLM_LIST_ITEMS = 30


def _series_stats(x: list[Any], y: list[Any]) -> dict[str, Any]:
    """min/max (with their x), mean, first, last over the full series: a sampled series would otherwise
    hide its real peak (a live run reported the max of 60 sampled points as the peak day)."""
    pts = [(xi, yi) for xi, yi in zip(x, y) if isinstance(yi, (int, float)) and yi == yi]
    if not pts:
        return {}
    lo, hi = min(pts, key=lambda p: p[1]), max(pts, key=lambda p: p[1])
    return {"min": {"x": lo[0], "y": lo[1]}, "max": {"x": hi[0], "y": hi[1]},
            "mean": round(sum(p[1] for p in pts) / len(pts), 4), "first": {"x": pts[0][0], "y": pts[0][1]},
            "last": {"x": pts[-1][0], "y": pts[-1][1]}}


def llm_results(r: BaseModel) -> dict[str, Any]:
    """results.json capped for prompts: long tables/series are trimmed (with their true sizes),
    so a big output (e.g. a 10k-row predictions table) can never blow up a prompt."""
    d = r.model_dump(mode="json")
    for t in d.get("tables") or []:
        t["n_rows"] = len(t["rows"])
        t["rows"] = t["rows"][:LLM_TABLE_ROWS]
    for s in d.get("series") or []:
        n = len(s["x"])
        s["n_points"] = n
        s["stats"] = _series_stats(s["x"], s["y"])  # exact, from the full series, before any sampling
        if n > LLM_SERIES_POINTS:  # evenly spaced, first and last kept
            s["sampled"] = True
            idx = sorted({round(i * (n - 1) / (LLM_SERIES_POINTS - 1)) for i in range(LLM_SERIES_POINTS)})
            for k in ("x", "y", "y_lower", "y_upper"):
                if isinstance(s.get(k), list) and len(s[k]) == n:
                    s[k] = [s[k][i] for i in idx]
    model = d.get("model") or {}
    if isinstance(model.get("feature_importance"), list):
        model["feature_importance"] = model["feature_importance"][:LLM_LIST_ITEMS]
    for k in ("kpis", "stat_tests", "insights_raw"):
        if isinstance(d.get(k), list):
            d[k] = d[k][:LLM_LIST_ITEMS]
    return d
