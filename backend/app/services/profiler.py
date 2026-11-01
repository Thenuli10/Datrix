"""Dataset loading and profiling (PLAN.md §3 Stage 2). Only profiles + small samples reach the LLM."""
from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from app.core.config import settings
from app.schemas.data import ColumnProfile, DatasetProfile
from app.schemas.requirement import DataSpec

CATEGORY_MAX_UNIQUE = 20
DATE_SAMPLE = 500
_MONTHS = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
DATE_RE = re.compile(
    r"^(\d{4}[-/.]\d{1,2}([-/.]\d{1,2})?([ T]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?\s*(z|[+-]\d{2}:?\d{2})?)?"
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}( \d{1,2}:\d{2}(:\d{2})?)?"
    rf"|\d{{1,2}}[ -]{_MONTHS}[ -,]+\d{{2,4}}"
    rf"|{_MONTHS} \d{{1,2}},? \d{{4}})$",
    re.IGNORECASE,
)
TRUE_FALSE = {"true", "false", "yes", "no"}
NUMERIC_TYPES = ("integer", "float")


# ---------------------------------------------------------------- loading

def _normalize_type(file_type: str) -> str:
    t = file_type.lower().lstrip(".")
    return {"xls": "xlsx", "excel": "xlsx", "jsonl": "json", "ndjson": "json", "tsv": "csv", "pq": "parquet"}.get(t, t)


def _read_csv(path: Path) -> pd.DataFrame:
    head = path.open("rb").read(64 * 1024)
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = head.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if len(head) == 64 * 1024:  # drop a possibly truncated last line before sniffing
        text = text.rsplit("\n", 1)[0]
    try:
        sep = csv.Sniffer().sniff(text, delimiters=",;\t|").delimiter
    except csv.Error:
        sep = ","
    try:
        return pd.read_csv(path, sep=sep, encoding=encoding)
    except UnicodeDecodeError:  # bad bytes beyond the sniffed head
        return pd.read_csv(path, sep=sep, encoding="latin-1")


def _read_json(path: Path) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:  # JSON lines
        return pd.read_json(io.StringIO(text), lines=True)
    if isinstance(data, dict):  # {"data": [...]} or a column-oriented dict
        lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        data = lists[0] if len(lists) == 1 else data
    if isinstance(data, list):
        return pd.json_normalize(data, max_level=0) if data and isinstance(data[0], dict) else pd.DataFrame(data)
    return pd.DataFrame(data)


def load_dataframe(path: Path, file_type: str) -> pd.DataFrame:
    """Load csv / xlsx (first sheet) / parquet / json (records or lines); column names as stripped str."""
    path = Path(path)
    kind = _normalize_type(file_type)
    if kind == "csv":
        df = _read_csv(path)
    elif kind == "xlsx":
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl")
    elif kind == "parquet":
        df = pd.read_parquet(path)
    elif kind == "json":
        df = _read_json(path)
    else:
        raise ValueError(f"unsupported file type: {file_type}")
    df.columns = [str(c).strip() for c in df.columns]
    return df


# ---------------------------------------------------------------- type inference

def _parse_dates(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce", format="mixed")


def _date_kind(parsed: pd.Series) -> str:
    parsed = parsed.dropna()
    if parsed.dt.tz is not None:
        return "datetime"
    return "date" if (parsed == parsed.dt.normalize()).all() else "datetime"


def infer_type(s: pd.Series) -> str:
    """Map a column to integer|float|string|category|boolean|date|datetime."""
    non = s.dropna()
    if ptypes.is_bool_dtype(s):
        return "boolean"
    if ptypes.is_datetime64_any_dtype(s):
        return _date_kind(s) if len(non) else "datetime"
    if isinstance(s.dtype, pd.CategoricalDtype):
        return "category"
    if ptypes.is_integer_dtype(s):
        return "integer"
    if ptypes.is_float_dtype(s):
        # pandas turns int columns with nulls into float
        finite = non[np.isfinite(non)]
        integral = len(finite) == len(non) > 0 and (finite == finite.round()).all()
        return "integer" if integral and s.isna().any() else "float"
    if not len(non):
        return "string"
    if all(isinstance(v, bool) for v in non[:DATE_SAMPLE]):
        return "boolean"
    if all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in non[:DATE_SAMPLE]):
        return infer_type(pd.to_numeric(s, errors="coerce"))
    if all(isinstance(v, (datetime, date, pd.Timestamp)) for v in non[:DATE_SAMPLE]):
        return _date_kind(pd.to_datetime(non))

    vals = non.astype(str).str.strip()
    if set(vals.str.lower().unique()) <= TRUE_FALSE:
        return "boolean"
    sample = vals.iloc[:DATE_SAMPLE]
    if sample.map(lambda v: bool(DATE_RE.match(v))).mean() >= 0.9:
        parsed = _parse_dates(sample)
        if parsed.notna().mean() >= 0.9:
            return _date_kind(parsed)
    n_unique = vals.nunique()
    return "category" if n_unique <= CATEGORY_MAX_UNIQUE and n_unique / len(vals) < 0.5 else "string"


def coerce_series(s: pd.Series, kind: str) -> pd.Series:
    """Best-effort conversion of a column to its inferred/canonical type (dates, numbers, booleans)."""
    if kind in ("date", "datetime") and not ptypes.is_datetime64_any_dtype(s):
        parsed = _parse_dates(s)
        return parsed if parsed.notna().sum() >= 0.9 * s.notna().sum() else s
    if kind == "integer" and ptypes.is_float_dtype(s):
        return s.astype("Int64")
    if kind in NUMERIC_TYPES and not ptypes.is_numeric_dtype(s):
        num = pd.to_numeric(s, errors="coerce")
        return num if num.notna().sum() >= 0.9 * s.notna().sum() else s
    if kind == "boolean" and not ptypes.is_bool_dtype(s):
        low = s.astype("string").str.strip().str.lower()
        mapped = low.map({"true": True, "yes": True, "false": False, "no": False})
        return mapped.astype("boolean") if mapped.notna().sum() == s.notna().sum() else s
    return s


# ---------------------------------------------------------------- JSON safety

def json_safe(v: Any) -> Any:
    """Convert a scalar to something json.dumps accepts (no NaN/Infinity, dates as ISO)."""
    if v is None or v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, datetime):  # includes pd.Timestamp; midnight values render as dates
        midnight = (v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0) and v.tzinfo is None
        return v.date().isoformat() if midnight else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return str(v)


def sample_records(df: pd.DataFrame, n: int) -> list[dict[str, Any]]:
    """First `n` rows as JSON-safe dicts."""
    return [{str(k): json_safe(v) for k, v in row.items()} for row in df.head(n).to_dict(orient="records")]


# ---------------------------------------------------------------- stats

def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _stats_duckdb(df: pd.DataFrame, kinds: dict[str, str]) -> dict[str, dict[str, Any]]:
    parts: list[str] = []
    for i, col in enumerate(df.columns):
        q = _quote(col)
        parts += [f"count({q}) AS n{i}", f"count(DISTINCT {q}) AS u{i}"]
        numeric = kinds[col] in NUMERIC_TYPES and ptypes.is_numeric_dtype(df[col])
        if numeric or ptypes.is_datetime64_any_dtype(df[col]):
            parts += [f"min({q}) AS lo{i}", f"max({q}) AS hi{i}"]
        if numeric:
            parts += [f"avg({q}::DOUBLE) AS m{i}", f"stddev_samp({q}::DOUBLE) AS s{i}"]
    con = duckdb.connect()
    try:
        con.register("t", df)
        cur = con.execute(f"SELECT {', '.join(parts)} FROM t")
        row = dict(zip([d[0] for d in cur.description], cur.fetchone()))
    finally:
        con.close()
    return {col: {"non_null": row[f"n{i}"], "unique": row[f"u{i}"], "min": row.get(f"lo{i}"),
                  "max": row.get(f"hi{i}"), "mean": row.get(f"m{i}"), "std": row.get(f"s{i}")}
            for i, col in enumerate(df.columns)}


def _stats_pandas(df: pd.DataFrame, kinds: dict[str, str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for col in df.columns:
        s = df[col]
        st: dict[str, Any] = {"non_null": int(s.notna().sum()), "unique": int(s.astype(str)[s.notna()].nunique())}
        numeric = kinds[col] in NUMERIC_TYPES and ptypes.is_numeric_dtype(s)
        if numeric or ptypes.is_datetime64_any_dtype(s):
            st["min"], st["max"] = s.min(), s.max()
        if numeric:
            st["mean"], st["std"] = s.mean(), s.std()
        out[col] = st
    return out


def _num(v: Any) -> float | None:
    v = json_safe(v)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def profile_dataframe(df: pd.DataFrame, dataset_id: int, file_name: str,
                      sample_rows: int | None = None) -> DatasetProfile:
    """Profile an in-memory frame (DuckDB aggregates, pandas fallback)."""
    n_rows = len(df)
    kinds = {col: infer_type(df[col]) for col in df.columns}
    typed = pd.DataFrame({col: coerce_series(df[col], kinds[col]) for col in df.columns}, index=df.index)
    try:
        stats = _stats_duckdb(typed, kinds)
    except Exception:  # noqa: BLE001 - odd object columns; pandas handles anything
        stats = _stats_pandas(typed, kinds)

    columns: list[ColumnProfile] = []
    for col in df.columns:
        s, st, kind = typed[col], stats[col], kinds[col]
        non = s.dropna()
        top: list[tuple[str, int]] = []
        if kind != "float" or st["unique"] <= 50:
            top = [(str(json_safe(k)), int(c)) for k, c in non.value_counts().head(10).items()]
        columns.append(ColumnProfile(
            name=col, inferred_type=kind,
            null_pct=round(100.0 * (1 - st["non_null"] / n_rows), 2) if n_rows else 0.0,
            unique_count=int(st["unique"]),
            min=json_safe(st.get("min")), max=json_safe(st.get("max")),
            mean=_num(st.get("mean")), std=_num(st.get("std")),
            top_values=top,
            sample_values=[str(json_safe(v)) for v in non.drop_duplicates().head(5)],
        ))
    n_sample = min(sample_rows if sample_rows is not None else settings.llm_sample_rows, settings.llm_sample_rows)
    return DatasetProfile(dataset_id=dataset_id, file_name=file_name, row_count=n_rows,
                          column_count=len(df.columns), columns=columns,
                          sample_rows=sample_records(typed, n_sample))


def profile_file(path: Path, file_type: str, dataset_id: int, file_name: str,
                 sample_rows: int | None = None) -> DatasetProfile:
    """Load and profile a file. `sample_rows` defaults to (and is capped at) settings.llm_sample_rows."""
    return profile_dataframe(load_dataframe(path, file_type), dataset_id, file_name, sample_rows)


# ---------------------------------------------------------------- template

_EXAMPLES: dict[str, list[str]] = {
    "integer": ["1", "2", "3"], "float": ["10.5", "20.25", "7.0"], "string": ["example a", "example b", "example c"],
    "category": ["A", "B", "A"], "boolean": ["true", "false", "true"],
    "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
    "datetime": ["2024-01-01T09:00:00", "2024-01-01T10:30:00", "2024-01-02T08:15:00"],
}


def template_csv(spec: DataSpec, n_rows: int = 3) -> str:
    """Header + example rows built from the spec's example_values (type-based fallbacks)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([c.name for c in spec.columns])
    for i in range(n_rows):
        row = []
        for c in spec.columns:
            pool = c.example_values or _EXAMPLES.get(c.type, _EXAMPLES["string"])
            row.append(pool[i % len(pool)])
        writer.writerow(row)
    return buf.getvalue()
