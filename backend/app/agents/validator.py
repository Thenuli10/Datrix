"""Data Validator (Stage 2): tool-calling agent mapping spec columns to uploaded data.

The tools run locally on the DataFrames; only aggregates and <= settings.llm_sample_rows
rows ever reach the LLM."""
import json
from typing import Any

import numpy as np
import pandas as pd

from app.agents._common import llm_profile, load_prompt, snake_case, to_json
from app.core.config import settings
from app.llm.base import LLMClient, Tool
from app.schemas.data import DatasetProfile, Gap, ValidationReport
from app.schemas.requirement import DataSpec

TOP_VALUES = 20


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(df.to_json(orient="records", date_format="iso", default_handler=str))


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) or np.isinf(f) else f


def build_tools(profiles: list[DatasetProfile], dfs: dict[int, pd.DataFrame]) -> dict[str, Tool]:
    """Tools over the uploaded DataFrames, keyed by dataset_id."""
    by_id = {p.dataset_id: p for p in profiles}
    by_name = {p.file_name: p.dataset_id for p in profiles}

    def ds(dataset_id: int | str) -> tuple[int, pd.DataFrame]:
        did = by_name.get(dataset_id) if isinstance(dataset_id, str) and not dataset_id.isdigit() else int(dataset_id)
        if did not in dfs:
            raise ValueError(f"unknown dataset {dataset_id!r}; known ids: {sorted(dfs)}")
        return did, dfs[did]

    def col(df: pd.DataFrame, column: str) -> pd.Series:
        if column not in df.columns:
            raise ValueError(f"unknown column {column!r}; columns: {list(df.columns)}")
        return df[column]

    def get_profile(dataset_id: int) -> dict[str, Any]:
        did, df = ds(dataset_id)
        if did in by_id:
            return llm_profile(by_id[did])
        return {"dataset_id": did, "row_count": len(df), "columns": [str(c) for c in df.columns]}

    def get_sample(dataset_id: int, n: int = 10) -> list[dict[str, Any]]:
        _, df = ds(dataset_id)
        return _records(df.head(max(0, min(int(n), settings.llm_sample_rows))))

    def column_stats(dataset_id: int, column: str) -> dict[str, Any]:
        _, df = ds(dataset_id)
        s = col(df, column)
        out: dict[str, Any] = {"column": column, "dtype": str(s.dtype), "rows": len(s),
                               "null_pct": round(float(s.isna().mean() * 100), 2) if len(s) else 0.0,
                               "unique": int(s.nunique(dropna=True))}
        nonnull = s.dropna()
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            q = nonnull.quantile([0, 0.05, 0.25, 0.5, 0.75, 0.95, 1]) if len(nonnull) else pd.Series(dtype=float)
            out.update(mean=_num(nonnull.mean()), std=_num(nonnull.std()),
                       quantiles={str(k): _num(v) for k, v in q.items()},
                       negative_count=int((nonnull < 0).sum()), zero_count=int((nonnull == 0).sum()))
        elif pd.api.types.is_datetime64_any_dtype(s):
            out.update(min=str(nonnull.min()) if len(nonnull) else None,
                       max=str(nonnull.max()) if len(nonnull) else None)
        else:
            txt = nonnull.astype(str)
            sample = txt.head(1000)
            out.update(min_len=int(txt.str.len().min()) if len(txt) else 0,
                       max_len=int(txt.str.len().max()) if len(txt) else 0,
                       numeric_parse_rate=round(float(pd.to_numeric(sample, errors="coerce").notna().mean()), 3)
                       if len(sample) else 0.0,
                       date_parse_rate=round(float(pd.to_datetime(sample, errors="coerce", format="mixed")
                                                   .notna().mean()), 3) if len(sample) else 0.0)
        return out

    def value_counts(dataset_id: int, column: str, top: int = TOP_VALUES) -> list[dict[str, Any]]:
        _, df = ds(dataset_id)
        vc = col(df, column).value_counts(dropna=False).head(max(1, min(int(top), TOP_VALUES)))
        return [{"value": None if pd.isna(k) else str(k), "count": int(v)} for k, v in vc.items()]

    def check_join(file_a: int, file_b: int, key_a: str, key_b: str) -> dict[str, Any]:
        _, a = ds(file_a)
        _, b = ds(file_b)
        ka, kb = col(a, key_a).dropna().astype(str), col(b, key_b).dropna().astype(str)
        set_a, set_b = set(ka), set(kb)
        return {"a_rows_matched_pct": round(float(ka.isin(set_b).mean() * 100), 2) if len(ka) else 0.0,
                "b_rows_matched_pct": round(float(kb.isin(set_a).mean() * 100), 2) if len(kb) else 0.0,
                "a_key_unique": bool(ka.is_unique), "b_key_unique": bool(kb.is_unique),
                "a_distinct": len(set_a), "b_distinct": len(set_b), "common_distinct": len(set_a & set_b)}

    ds_param = {"dataset_id": {"type": "integer", "description": "dataset_id from the profiles"}}
    col_param = {"column": {"type": "string", "description": "exact column name in that dataset"}}

    def obj(desc: str, props: dict[str, Any], req: list[str]) -> dict[str, Any]:
        return {"description": desc, "type": "object", "properties": props, "required": req}

    return {
        "get_profile": (obj("Full profile (types, nulls, stats, small sample) of one dataset.", ds_param,
                            ["dataset_id"]), get_profile),
        "get_sample": (obj(f"First n rows (max {settings.llm_sample_rows}).",
                           {**ds_param, "n": {"type": "integer"}}, ["dataset_id"]), get_sample),
        "column_stats": (obj("Detailed stats for one column, incl. numeric/date parse rates for text columns.",
                             {**ds_param, **col_param}, ["dataset_id", "column"]), column_stats),
        "value_counts": (obj(f"Most frequent values (top {TOP_VALUES}) incl. nulls.",
                             {**ds_param, **col_param, "top": {"type": "integer"}}, ["dataset_id", "column"]),
                         value_counts),
        "check_join": (obj("Key match rates between two datasets (for multi-file joins).", {
            "file_a": {"type": "integer", "description": "left dataset_id"},
            "file_b": {"type": "integer", "description": "right dataset_id"},
            "key_a": {"type": "string"}, "key_b": {"type": "string"}},
            ["file_a", "file_b", "key_a", "key_b"]), check_join),
    }


def validate(llm: LLMClient, spec: DataSpec, profiles: list[DatasetProfile], dfs: dict[int, pd.DataFrame],
             pid: int | None) -> ValidationReport:
    tools = build_tools(profiles, dfs)
    overview = [{"dataset_id": p.dataset_id, "file_name": p.file_name, "row_count": p.row_count,
                 "columns": [{"name": c.name, "type": c.inferred_type, "null_pct": c.null_pct,
                              "unique": c.unique_count} for c in p.columns]} for p in profiles]
    user = f"## Data spec\n{to_json(spec)}\n\n## Uploaded datasets (overview)\n{to_json(overview)}"
    report = llm.tool_loop(agent="validator", system=load_prompt("validator"), user=user, tools=tools,
                           schema=ValidationReport, project_id=pid)
    return _postprocess(report, spec, dfs, tools)


def _postprocess(report: ValidationReport, spec: DataSpec, dfs: dict[int, pd.DataFrame],
                 tools: dict[str, Tool]) -> ValidationReport:
    """Deterministic guards: drop impossible mappings, flag unmapped required columns, measure joins."""
    report.mapping = [m for m in report.mapping
                      if m.dataset_id in dfs and m.source_column in dfs[m.dataset_id].columns]
    for m in report.mapping:
        m.spec_column = snake_case(m.spec_column)
    mapped = {m.spec_column for m in report.mapping}
    flagged = {g.column for g in report.gaps if g.kind == "missing_column"}
    for c in spec.columns:
        if c.required and c.name not in mapped and c.name not in flagged:
            report.gaps.append(Gap(severity="blocker", kind="missing_column", column=c.name,
                                   message=f"Required column '{c.name}' was not found in the uploaded data.",
                                   suggestion=f"Add a column with: {c.description}"))
    joins = []
    for j in report.joins:
        try:
            r = tools["check_join"][1](j.left_dataset_id, j.right_dataset_id, j.left_key, j.right_key)
        except ValueError as e:
            report.gaps.append(Gap(severity="warning", kind="join_issue", message=f"Invalid join dropped: {e}"))
            continue
        j.match_rate = r["a_rows_matched_pct"] / 100
        joins.append(j)
    report.joins = joins
    if any(g.severity == "blocker" for g in report.gaps):
        report.status = "needs_more_data"
    elif report.status == "ready" and any(g.severity == "warning" for g in report.gaps):
        report.status = "ready_with_warnings"
    return report
