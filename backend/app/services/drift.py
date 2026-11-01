"""Drift check for the ML path (PLAN.md §3 Stage 6): new data vs the training data.

Numeric columns: PSI on 10 training-quantile bins plus a two-sample KS test against a stored
sample. Categorical columns: PSI on category frequencies. Drifted if PSI > 0.2 or KS p < 0.01.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.schemas.data import DriftColumn, DriftReport
from app.services.profiler import coerce_series, infer_type

N_BINS = 10
SAMPLE_SIZE = 2000
MAX_CATEGORIES = 50
PSI_THRESHOLD = 0.2
KS_P_THRESHOLD = 0.01
EPS = 1e-4


def _numeric_values(s: pd.Series) -> np.ndarray:
    v = pd.to_numeric(coerce_series(s, "float"), errors="coerce").astype("float64").to_numpy()
    return v[np.isfinite(v)]


def _bin_props(values: np.ndarray, edges: list[float]) -> list[float]:
    """Share of values in each bin; the outer bins are open-ended."""
    inner = np.asarray(edges[1:-1], dtype=float)
    counts = np.bincount(np.searchsorted(inner, values, side="right"), minlength=len(edges) - 1)
    return (counts / max(len(values), 1)).tolist()


def _psi(expected: list[float], actual: list[float]) -> float:
    e = np.clip(np.asarray(expected, dtype=float), EPS, None)
    a = np.clip(np.asarray(actual, dtype=float), EPS, None)
    return float(np.sum((a - e) * np.log(a / e)))


def training_profile(df: pd.DataFrame, seed: int = 0) -> dict[str, Any]:
    """Distribution snapshot of the training data (JSON-serialisable, stored on the Pipeline)."""
    rng = np.random.default_rng(seed)
    numeric: dict[str, Any] = {}
    categorical: dict[str, Any] = {}
    for col in df.columns:
        s = df[col]
        kind = infer_type(s)
        if kind in ("integer", "float"):
            values = _numeric_values(s)
            if not len(values):
                continue
            edges = np.unique(np.quantile(values, np.linspace(0, 1, N_BINS + 1))).tolist()
            if len(edges) < 2:
                edges = [edges[0], edges[0]]
            sample = values if len(values) <= SAMPLE_SIZE else rng.choice(values, SAMPLE_SIZE, replace=False)
            numeric[col] = {"edges": edges, "props": _bin_props(values, edges), "sample": sample.tolist()}
        elif kind in ("category", "boolean", "string"):
            freqs = s.dropna().astype(str).value_counts(normalize=True)
            if 0 < len(freqs) <= MAX_CATEGORIES:
                categorical[col] = {"freqs": {str(k): float(v) for k, v in freqs.items()}}
    return {"rows": len(df), "numeric": numeric, "categorical": categorical}


def check_drift(training_profile: dict[str, Any], df: pd.DataFrame) -> DriftReport:
    """Compare `df` with a stored training profile. Columns missing from `df` are skipped.

    Numeric columns report method="psi" with the KS p-value in `p_value`.
    """
    columns: list[DriftColumn] = []
    for col, ref in training_profile.get("numeric", {}).items():
        if col not in df.columns:
            continue
        values = _numeric_values(df[col])
        if not len(values):
            continue
        psi = _psi(ref["props"], _bin_props(values, ref["edges"]))
        sample = values if len(values) <= SAMPLE_SIZE else np.random.default_rng(0).choice(values, SAMPLE_SIZE, replace=False)
        p_value = float(stats.ks_2samp(np.asarray(ref["sample"]), sample).pvalue) if ref["sample"] else None
        drifted = psi > PSI_THRESHOLD or (p_value is not None and p_value < KS_P_THRESHOLD)
        columns.append(DriftColumn(column=col, method="psi", statistic=round(psi, 6), p_value=p_value,
                                   drifted=drifted))
    for col, ref in training_profile.get("categorical", {}).items():
        if col not in df.columns:
            continue
        counts = df[col].dropna().astype(str).value_counts(normalize=True)
        if not len(counts):
            continue
        cats = list(ref["freqs"])
        expected = [ref["freqs"][c] for c in cats] + [0.0]
        actual = [float(counts.get(c, 0.0)) for c in cats]
        actual.append(max(0.0, 1.0 - sum(actual)))  # unseen categories
        psi = _psi(expected, actual)
        columns.append(DriftColumn(column=col, method="psi", statistic=round(psi, 6), drifted=psi > PSI_THRESHOLD))
    return DriftReport(drifted=any(c.drifted for c in columns), columns=columns)
