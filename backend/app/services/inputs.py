"""Build the sandbox /input dir: canonical, mapped parquet files plus manifest.json.

manifest.json = {
  "files":   [{"name", "path", "rows", "columns"}],   # path is relative to the input dir
  "joins":   [{"left", "right", "left_key", "right_key", "how"}],  # canonical file/column names
  "columns": {canonical_column: {"type", "description"}},
}
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from app.schemas.data import ColumnMapping, DataContract, JoinSpec
from app.schemas.requirement import DataSpec
from app.services.contract import resolve_dataset_index
from app.services.profiler import coerce_series, infer_type

MANIFEST = "manifest.json"
DatasetItem = tuple[str, pd.DataFrame] | pd.DataFrame


def canonical_name(file_name: str) -> str:
    """Sanitised file stem usable as a file / identifier name: 'Sales Q1.csv' -> 'sales_q1'."""
    stem = Path(file_name).stem.lower()
    name = re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "data"
    return f"d_{name}" if name[0].isdigit() else name


def _unique_names(names: Sequence[str]) -> list[str]:
    out: list[str] = []
    for n in names:
        base, k = canonical_name(n), 2
        cand = base
        while cand in out:
            cand, k = f"{base}_{k}", k + 1
        out.append(cand)
    return out


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    try:
        df.to_parquet(path, index=False)
    except (TypeError, ValueError, ArithmeticError):  # mixed-type object columns
        fixed = df.copy()
        for c in fixed.columns:
            if fixed[c].dtype == object:
                fixed[c] = fixed[c].map(lambda v: None if pd.isna(v) else str(v))
        fixed.to_parquet(path, index=False)


def prepare_inputs(datasets: Sequence[DatasetItem], mapping: Sequence[ColumnMapping] | None,
                   joins: Sequence[JoinSpec], out_dir: Path, *, dataset_ids: Sequence[int] | None = None,
                   spec: DataSpec | None = None, contract: DataContract | None = None) -> Path:
    """Write `<name>.parquet` per dataset and manifest.json into `out_dir`; returns `out_dir`.

    First run: `datasets` are raw `(file_name, df)` and `mapping` is the validation mapping
    (dataset ids resolved via `dataset_ids` or upload order); only mapped columns and join keys are
    kept, renamed to canonical names. Re-run: pass `mapping=None`, frames already canonical (from
    `contract.apply_mapping` / `append_datasets`) and the `contract`, whose file names and
    index-based joins are used so names stay stable across runs.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs = [(d if isinstance(d, tuple) else (f"data_{i}", d)) for i, d in enumerate(datasets)]
    names = _unique_names(contract.files if contract and len(contract.files) == len(pairs) else [n for n, _ in pairs])

    # (dataset position, source column) -> canonical column
    renames: dict[tuple[int, str], str] = {}
    join_ids = [i for j in joins for i in (j.left_dataset_id, j.right_dataset_id)]
    if mapping is not None:
        all_ids = [m.dataset_id for m in mapping] + join_ids
        for m in mapping:
            renames[(resolve_dataset_index(m, pairs, dataset_ids, all_ids), m.source_column)] = m.spec_column

        def pos(ds_id: int, col: str) -> int:
            m = ColumnMapping(spec_column="", dataset_id=ds_id, source_column=col)
            return resolve_dataset_index(m, pairs, dataset_ids, all_ids)
    else:
        if contract is not None:
            renames = {(c.dataset_index, c.source_column): c.name for c in contract.columns}

        def pos(ds_id: int, col: str) -> int:
            return ds_id

    manifest_joins: list[dict[str, Any]] = []
    for j in joins:
        li, ri = pos(j.left_dataset_id, j.left_key), pos(j.right_dataset_id, j.right_key)
        lk, rk = renames.get((li, j.left_key), j.left_key), renames.get((ri, j.right_key), j.right_key)
        if mapping is not None:  # unmapped join keys are kept under their own name
            renames.setdefault((li, j.left_key), lk)
            renames.setdefault((ri, j.right_key), rk)
        if li < len(names) and ri < len(names):
            manifest_joins.append({"left": names[li], "right": names[ri], "left_key": lk, "right_key": rk,
                                   "how": j.how})

    spec_cols = {c.name: c for c in spec.columns} if spec else {}
    contract_types = {c.name: c.type for c in contract.columns} if contract else {}
    files: list[dict[str, Any]] = []
    columns: dict[str, dict[str, str]] = {}
    for i, ((_, df), name) in enumerate(zip(pairs, names)):
        if mapping is not None:
            cols = {src: canon for (p, src), canon in renames.items() if p == i and src in df.columns}
            frame = pd.DataFrame({canon: df[src] for src, canon in cols.items()}, index=df.index)
        else:
            frame = df.copy()
        frame = frame.reset_index(drop=True)
        for col in frame.columns:
            kind = spec_cols[col].type if col in spec_cols else contract_types.get(col) or infer_type(frame[col])
            frame[col] = coerce_series(frame[col], kind)
            columns.setdefault(col, {"type": kind,
                                     "description": spec_cols[col].description if col in spec_cols else ""})
        _write_parquet(frame, out_dir / f"{name}.parquet")
        files.append({"name": name, "path": f"{name}.parquet", "rows": len(frame),
                      "columns": [str(c) for c in frame.columns]})

    manifest = {"files": files, "joins": manifest_joins, "columns": columns}
    (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out_dir
