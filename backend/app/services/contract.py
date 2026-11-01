"""Data contract (PLAN.md §2.5, §3 Stage 6): freeze the schema after the first run, check re-run uploads.

Deterministic, no LLM. Datasets are `(file_name, df)` pairs in upload order. Inside a contract,
`ContractColumn.dataset_index` and the `JoinSpec` dataset ids are positions in that list.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from app.schemas.data import (
    ColumnMapping, ContractCheckResult, ContractColumn, ContractIssue, DataContract, ValidationReport,
)
from app.schemas.requirement import DataSpec
from app.services.profiler import coerce_series, infer_type

Datasets = Sequence[tuple[str, pd.DataFrame]]

MAX_CATEGORIES = 50
NULL_SPIKE_POINTS = 20.0
OUT_OF_RANGE_FRACTION = 0.5
NUMERIC = ("integer", "float")
TEXT = ("string", "category")
# (frozen type, new type) pairs that are accepted besides identical types
COMPATIBLE = {
    ("float", "integer"),  # integer data where float was frozen is fine; the reverse is not
    ("string", "category"), ("category", "string"),
    ("date", "datetime"), ("datetime", "date"),
    ("string", "integer"), ("category", "integer"), ("category", "boolean"), ("string", "boolean"),
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def resolve_dataset_index(m: ColumnMapping, datasets: Datasets, dataset_ids: Sequence[int] | None,
                          all_ids: Sequence[int]) -> int:
    """Position in `datasets` of the file a mapping (by DB dataset_id) refers to.

    Uses explicit `dataset_ids` when given; otherwise assumes ascending ids follow upload order,
    falling back to the first file that has the source column.
    """
    if dataset_ids is not None and m.dataset_id in dataset_ids:
        return list(dataset_ids).index(m.dataset_id)
    if len(datasets) == 1:
        return 0
    ordered = sorted(set(all_ids))
    if len(ordered) == len(datasets):
        idx = ordered.index(m.dataset_id)
        if m.source_column in datasets[idx][1].columns:
            return idx
    for i, (_, df) in enumerate(datasets):
        if m.source_column in df.columns:
            return i
    return min(max(m.dataset_id, 0), len(datasets) - 1)


def _numeric(s: pd.Series) -> pd.Series:
    s = coerce_series(s, "float")
    return s.astype("float64") if ptypes.is_numeric_dtype(s) and not ptypes.is_bool_dtype(s) else pd.Series(dtype=float)


def freeze_contract(datasets: Datasets, report: ValidationReport, spec: DataSpec,
                    dataset_ids: Sequence[int] | None = None) -> DataContract:
    """Freeze type, null %, numeric range and categories (<= 50 uniques) of every mapped column."""
    all_ids = [m.dataset_id for m in report.mapping] + \
              [i for j in report.joins for i in (j.left_dataset_id, j.right_dataset_id)]
    columns: list[ContractColumn] = []
    for m in report.mapping:
        idx = resolve_dataset_index(m, datasets, dataset_ids, all_ids)
        df = datasets[idx][1]
        if m.source_column not in df.columns:
            continue
        s = df[m.source_column]
        kind = infer_type(s)
        col = ContractColumn(name=m.spec_column, source_column=m.source_column, dataset_index=idx, type=kind,
                             nullable_pct=round(100.0 * s.isna().mean(), 2) if len(s) else 0.0)
        if kind in NUMERIC:
            num = _numeric(s).replace([np.inf, -np.inf], np.nan).dropna()
            if len(num):
                col.min, col.max = float(num.min()), float(num.max())
        elif kind in TEXT + ("boolean",):
            uniques = s.dropna().astype(str).unique()
            if len(uniques) <= MAX_CATEGORIES:
                col.categories = sorted(uniques.tolist())
        columns.append(col)

    joins = []
    for j in report.joins:
        lm = ColumnMapping(spec_column="", dataset_id=j.left_dataset_id, source_column=j.left_key)
        rm = ColumnMapping(spec_column="", dataset_id=j.right_dataset_id, source_column=j.right_key)
        li = resolve_dataset_index(lm, datasets, dataset_ids, all_ids)
        ri = resolve_dataset_index(rm, datasets, dataset_ids, all_ids)
        joins.append(j.model_copy(update={"left_dataset_id": li, "right_dataset_id": ri}))
        for idx, key in ((li, j.left_key), (ri, j.right_key)):  # join keys must survive apply_mapping
            df = datasets[idx][1]
            if key in df.columns and not any(c.dataset_index == idx and c.source_column == key for c in columns):
                columns.append(ContractColumn(name=key, source_column=key, dataset_index=idx,
                                              type=infer_type(df[key]),
                                              nullable_pct=round(100.0 * df[key].isna().mean(), 2)))
    return DataContract(files=[name for name, _ in datasets], columns=columns, joins=joins,
                        min_rows=spec.min_rows)


def _match_files(contract: DataContract, datasets: Datasets) -> list[int | None]:
    """For each contract file, the index of the new dataset (by name if all names match, else by order)."""
    names = [n for n, _ in datasets]
    if all(f in names for f in contract.files):
        return [names.index(f) for f in contract.files]
    return [i if i < len(datasets) else None for i in range(len(contract.files))]


def _source(col: ContractColumn, override: dict[str, str]) -> str:
    return override.get(col.source_column) or override.get(col.name) or col.source_column


def _suggest(missing: str, available: Sequence[str], taken: set[str]) -> str | None:
    target = _norm(missing)
    for c in available:
        if c not in taken and _norm(c) == target:
            return c
    return None


def check_contract(contract: DataContract, datasets: Datasets,
                   mapping_override: dict[str, str] | None = None, min_rows: int | None = None) -> ContractCheckResult:
    """Check new uploads against the frozen contract.

    `mapping_override` maps a contract source column (or canonical name) to the column name in the new file.
    """
    override = mapping_override or {}
    issues: list[ContractIssue] = []
    suggested: dict[str, str] = {}
    if len(datasets) != len(contract.files):
        issues.append(ContractIssue(severity="error", kind="file_count",
                                    message=f"Expected {len(contract.files)} file(s) "
                                            f"({', '.join(contract.files)}), got {len(datasets)}."))
    order = _match_files(contract, datasets)

    # `min_rows` overrides the contract's minimum, e.g. 0 in append mode where the combined data is checked later.
    need = contract.min_rows if min_rows is None else min_rows
    rows = [len(datasets[i][1]) for i in order if i is not None]
    if rows and max(rows) < need:
        issues.append(ContractIssue(severity="error", kind="too_few_rows",
                                    message=f"Only {max(rows)} rows; at least {need} are needed."))

    for col in contract.columns:
        pos = order[col.dataset_index] if col.dataset_index < len(order) else None
        if pos is None:
            continue  # already reported as file_count
        df = datasets[pos][1]
        src = _source(col, override)
        if src not in df.columns:
            taken = {_source(c, override) for c in contract.columns if c.dataset_index == col.dataset_index}
            if hint := _suggest(col.source_column, list(df.columns), taken):
                suggested[col.source_column] = hint
            issues.append(ContractIssue(severity="error", column=col.name, kind="missing_column",
                                        message=f"Column '{src}' (for '{col.name}') is missing"
                                                + (f"; did you mean '{hint}'?" if hint else ".")))
            continue
        issues += _check_column(col, src, df[src])

    return ContractCheckResult(ok=not any(i.severity == "error" for i in issues), issues=issues,
                               suggested_mapping=suggested)


def _check_column(col: ContractColumn, src: str, s: pd.Series) -> list[ContractIssue]:
    out: list[ContractIssue] = []
    null_pct = 100.0 * s.isna().mean() if len(s) else 0.0
    if len(s) and null_pct >= 100.0:
        return [ContractIssue(severity="error", column=col.name, kind="null_spike",
                              message=f"Column '{src}' is entirely empty.")]
    if null_pct > col.nullable_pct + NULL_SPIKE_POINTS:
        out.append(ContractIssue(severity="warning", column=col.name, kind="null_spike",
                                 message=f"'{src}' is {null_pct:.0f}% empty (was {col.nullable_pct:.0f}%)."))

    kind = infer_type(s)
    if kind != col.type and (col.type, kind) not in COMPATIBLE:
        out.append(ContractIssue(severity="error", column=col.name, kind="type_mismatch",
                                 message=f"'{src}' looks like {kind}, expected {col.type}."))
        return out

    if col.categories is not None and kind in TEXT + ("boolean",):
        new = sorted(set(s.dropna().astype(str).unique()) - set(col.categories))
        if new:
            shown = ", ".join(new[:5]) + (f" (+{len(new) - 5} more)" if len(new) > 5 else "")
            out.append(ContractIssue(severity="warning", column=col.name, kind="new_categories",
                                     message=f"'{src}' has new values: {shown}."))
    if col.min is not None and col.max is not None and col.type in NUMERIC:
        num = _numeric(s).dropna()
        if len(num):
            outside = float(((num < col.min) | (num > col.max)).mean())
            if outside > OUT_OF_RANGE_FRACTION:
                out.append(ContractIssue(severity="warning", column=col.name, kind="out_of_range",
                                         message=f"{outside:.0%} of '{src}' is outside the earlier range "
                                                 f"[{col.min:g}, {col.max:g}]."))
    return out


def apply_mapping(contract: DataContract, datasets: Datasets,
                  mapping_override: dict[str, str] | None = None) -> list[pd.DataFrame]:
    """One frame per contract file holding only its mapped columns, renamed to canonical names."""
    override = mapping_override or {}
    order = _match_files(contract, datasets)
    out: list[pd.DataFrame] = []
    for idx, pos in enumerate(order):
        cols = [c for c in contract.columns if c.dataset_index == idx]
        if pos is None:
            out.append(pd.DataFrame(columns=[c.name for c in cols]))
            continue
        df = datasets[pos][1]
        present = [c for c in cols if _source(c, override) in df.columns]
        frame = pd.DataFrame({c.name: df[_source(c, override)] for c in present}, index=df.index)
        out.append(frame.reset_index(drop=True))
    return out


def append_datasets(old_dfs: Sequence[pd.DataFrame], new_dfs: Sequence[pd.DataFrame]) -> list[pd.DataFrame]:
    """Re-run "append" mode: old rows plus the new rows not already in the old data.

    Only overlap with the old data is dropped (e.g. re-uploading a period that is already there), counted per
    occurrence. Identical rows that are genuinely repeated (two equal order lines) are kept: deduplicating the
    whole frame silently lost rows in a live run.
    """
    out: list[pd.DataFrame] = []
    for i in range(max(len(old_dfs), len(new_dfs))):
        old = old_dfs[i] if i < len(old_dfs) else None
        new = new_dfs[i] if i < len(new_dfs) else None
        if old is None or not len(old.columns):
            out.append(new.reset_index(drop=True) if new is not None else pd.DataFrame())
            continue
        if new is None or not len(new.columns):
            out.append(old.reset_index(drop=True))
            continue
        new = new.reindex(columns=old.columns)
        old_counts = _row_keys(old).value_counts()
        keys = _row_keys(new)
        occurrence = keys.groupby(keys).cumcount()
        fresh = new.loc[(occurrence >= keys.map(old_counts).fillna(0)).to_numpy()]
        out.append(pd.concat([old, fresh], ignore_index=True))
    return out


def _row_keys(df: pd.DataFrame) -> pd.Series:
    """One comparable string per row (works for unhashable JSON cells and mixed dtypes)."""
    return df.astype(str).agg("\x1f".join, axis=1)
