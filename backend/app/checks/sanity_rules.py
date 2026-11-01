"""Layer 1 (code rules) and Layer 2 (spot-check comparison) of the Results Sanity
Checker (PLAN.md §7a). Pure functions: no LLM, no I/O."""
import math
import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from app.core.config import settings
from app.schemas.checks import SanityIssue, SanityReport, SpotCheck
from app.schemas.plan import AnalysisPlan
from app.schemas.results import Results

DateLike = str | date | datetime
DateRange = tuple[DateLike, DateLike]

HIGHER_BETTER = {"auc", "roc_auc", "accuracy", "f1", "r2", "precision", "recall"}
LOWER_BETTER = {"rmse", "mae", "mape", "mse", "log_loss", "logloss"}
_SHARE_HINT = re.compile(r"share|percent|pct|proportion|fraction|distribution|mix", re.I)
_COUNT_HINT = re.compile(r"\bcount\b|number of|\bnum_|_count\b|^count|\bn_", re.I)
_PROB_HINT = re.compile(r"prob", re.I)
_IDENT = re.compile(r"^[A-Za-z_][\w.]*$")


def _issue(severity: str, check: str, message: str, fix: str = "", layer: int = 1) -> SanityIssue:
    return SanityIssue(severity=severity, check=check, message=message, suggested_fix=fix, layer=layer)


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_bad(v: Any) -> bool:
    """None, NaN or +/-Inf."""
    return v is None or (isinstance(v, float) and not math.isfinite(v))


def _text(*parts: str | None) -> str:
    return " ".join(p for p in parts if p)


def metric_direction(name: str) -> int:
    """+1 higher-is-better, -1 lower-is-better, 0 unknown."""
    n = name.lower()
    if n in HIGHER_BETTER:
        return 1
    if n in LOWER_BETTER:
        return -1
    return 0


def _parse_date(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if isinstance(v, str) and v.strip():
        s = v.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s).replace(tzinfo=None)
        except ValueError:
            pass
        for fmt in ("%Y-%m", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%Y"):
            try:
                return datetime.strptime(v.strip(), fmt)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------- rule families

def _row_accounting(r: Results, input_rows: int) -> list[SanityIssue]:
    s = r.summary
    out: list[SanityIssue] = []
    if input_rows <= 0:
        return out
    if s.rows_processed > input_rows:
        out.append(_issue("medium", "row_accounting",
                          f"rows_processed ({s.rows_processed}) exceeds input rows ({input_rows})",
                          "Check joins/explodes that duplicate rows"))
    missing = input_rows - s.rows_processed
    undocumented = missing if not s.drop_reasons else missing - s.rows_dropped
    if not s.drop_reasons and missing / input_rows > settings.sanity_max_silent_drop:
        out.append(_issue("high", "row_accounting",
                          f"{missing} of {input_rows} rows ({missing / input_rows:.0%}) dropped without a documented reason",
                          "Report rows_dropped and drop_reasons, or avoid dropping rows"))
    elif s.drop_reasons and undocumented / input_rows > settings.sanity_max_silent_drop:
        out.append(_issue("medium", "row_accounting",
                          f"{undocumented} rows unaccounted for (processed {s.rows_processed} + dropped "
                          f"{s.rows_dropped} vs {input_rows} input)",
                          "Make rows_processed + rows_dropped match the input row count"))
    return out


def _bad_numbers(r: Results) -> list[SanityIssue]:
    out: list[SanityIssue] = []
    for k in r.kpis:
        if is_bad(k.value):
            out.append(_issue("high" if k.value is not None else "medium", "bad_numbers",
                              f"KPI '{k.key}' has an invalid value ({k.value!r})",
                              "Guard against empty groups / division by zero"))
    for s in r.series:
        if not s.y:
            continue
        nonfin = sum(1 for v in s.y if v is not None and is_bad(v))
        nones = sum(1 for v in s.y if v is None)
        if nonfin:
            out.append(_issue("high", "bad_numbers", f"Series '{s.key}' has {nonfin} NaN/Infinity values",
                              "Fill or drop non-finite values before output"))
        if nones:
            frac = nones / len(s.y)
            out.append(_issue("medium" if frac > 0.5 else "low", "bad_numbers",
                              f"Series '{s.key}' has {nones}/{len(s.y)} empty y values"))
        if len(s.x) != len(s.y):
            out.append(_issue("medium", "bad_numbers",
                              f"Series '{s.key}' x/y length mismatch ({len(s.x)} vs {len(s.y)})"))
    for t in r.tables:
        bad = sum(1 for row in t.rows for v in row if isinstance(v, float) and not math.isfinite(v))
        if bad:
            out.append(_issue("medium", "bad_numbers", f"Table '{t.key}' has {bad} NaN/Infinity cells"))
    return out


def _percent_bounds(values: list[float]) -> tuple[float, float]:
    """Detect 0-1 vs 0-100 convention: if everything fits 0..1, use it; else 0..100."""
    return (0.0, 1.0) if all(-1e-9 <= v <= 1 + 1e-9 for v in values) else (0.0, 100.0)


def _range_rules(r: Results) -> list[SanityIssue]:
    out: list[SanityIssue] = []
    pct_kpis = [k for k in r.kpis if k.format == "percent" and is_number(k.value) and not is_bad(k.value)]
    if pct_kpis:
        lo, hi = _percent_bounds([float(k.value) for k in pct_kpis])
        for k in pct_kpis:
            if not lo - 1e-9 <= float(k.value) <= hi + 1e-9:
                out.append(_issue("high", "range", f"Percent KPI '{k.key}' = {k.value} outside {lo:g}-{hi:g}"))
    for k in r.kpis:
        if not is_number(k.value) or is_bad(k.value):
            continue
        name = _text(k.key, k.label)
        if _PROB_HINT.search(name) and not 0 <= k.value <= 1:
            out.append(_issue("high", "range", f"Probability KPI '{k.key}' = {k.value} outside 0-1"))
        if _COUNT_HINT.search(name) and k.value < 0:
            out.append(_issue("high", "range", f"Count KPI '{k.key}' is negative ({k.value})"))
    for s in r.series:
        ys = [float(v) for v in s.y if is_number(v) and not is_bad(v)]
        if not ys:
            continue
        name = _text(s.key, s.label, s.y_label)
        if s.format == "percent":
            lo, hi = _percent_bounds(ys)
            n_out = sum(1 for v in ys if not lo - 1e-9 <= v <= hi + 1e-9)
            if n_out:
                out.append(_issue("high", "range", f"Percent series '{s.key}' has {n_out} values outside {lo:g}-{hi:g}"))
        if _SHARE_HINT.search(name) and all(v >= 0 for v in ys):
            total = sum(ys)
            if not (abs(total - 1) <= 0.05 or abs(total - 100) <= 5):
                out.append(_issue("medium", "range", f"Shares in series '{s.key}' sum to {total:g}, not ~100%",
                                  "Normalise shares or include an 'Other' bucket"))
        if _PROB_HINT.search(name) and any(not 0 <= v <= 1 for v in ys):
            out.append(_issue("high", "range", f"Probability series '{s.key}' has values outside 0-1"))
        if _COUNT_HINT.search(name) and any(v < 0 for v in ys):
            out.append(_issue("high", "range", f"Count series '{s.key}' has negative values"))
    for t in r.tables:
        for ci, col in enumerate(t.columns):
            vals = [row[ci] for row in t.rows if ci < len(row) and is_number(row[ci]) and not is_bad(row[ci])]
            if _COUNT_HINT.search(col) and any(v < 0 for v in vals):
                out.append(_issue("high", "range", f"Count column '{col}' in table '{t.key}' has negative values"))
            if _PROB_HINT.search(col) and any(not 0 <= v <= 1 for v in vals):
                out.append(_issue("high", "range", f"Probability column '{col}' in table '{t.key}' outside 0-1"))
    return out


def _period_trunc(dates: list[datetime]) -> Any:
    """Truncation matching the axis grain: yearly / monthly when every point is a period start."""
    if len(dates) > 1 and all(d.month == 1 and d.day == 1 for d in dates):
        return lambda d: datetime(d.year, 1, 1)
    if len(dates) > 1 and all(d.day == 1 for d in dates):
        return lambda d: datetime(d.year, d.month, 1)
    return lambda d: d


def _date_coverage(r: Results, rng: DateRange | None) -> list[SanityIssue]:
    if rng is None:
        rng = (r.summary.input_date_min, r.summary.input_date_max)  # type: ignore[assignment]
    lo, hi = _parse_date(rng[0]), _parse_date(rng[1])
    if lo is None or hi is None:
        return []
    out: list[SanityIssue] = []
    for s in r.series:
        dates = [d for d in (_parse_date(x) for x in s.x) if d is not None]
        if not dates or len(dates) < len(s.x) / 2:
            continue  # x is not a date axis
        # Aggregated axes ("2026-01", month/year starts) label a whole period: compare at that grain.
        trunc = _period_trunc(dates)
        dates, lo, hi = [trunc(d) for d in dates], trunc(lo), trunc(hi)
        if s.is_forecast:
            if min(dates) <= hi:
                out.append(_issue("high", "date_coverage",
                                  f"Forecast '{s.key}' starts {min(dates).date()} on/before last input date {hi.date()}",
                                  "Start the forecast after the last observed date"))
        else:
            n_out = sum(1 for d in dates if d < lo or d > hi)
            if n_out:
                out.append(_issue("medium", "date_coverage",
                                  f"Series '{s.key}' has {n_out} dates outside input range {lo.date()}..{hi.date()}"))
    return out


def _ml_too_good(r: Results) -> list[SanityIssue]:
    if r.model is None:
        return []
    out: list[SanityIssue] = []
    limits = {"auc": settings.sanity_leak_auc, "roc_auc": settings.sanity_leak_auc,
              "r2": settings.sanity_leak_r2, "accuracy": 0.99}
    for name, val in r.model.metrics.items():
        lim = limits.get(name.lower())
        if lim is not None and val > lim:
            out.append(_issue("high", "target_leakage",
                              f"{name} {val:.3f} > {lim} - possible target leakage",
                              "Check features derived from or recorded after the target and drop them"))
    return out


def _ml_too_bad(r: Results, plan: AnalysisPlan) -> list[SanityIssue]:
    m = r.model
    if m is None:
        if plan.ml is not None and plan.ml.problem != "clustering":
            return [_issue("high", "plan_mismatch", "Plan requires an ML model but results have no 'model'")]
        return []
    if not m.baseline_metrics:
        if plan.ml is not None and plan.ml.problem != "clustering":
            return [_issue("medium", "below_baseline", "No baseline_metrics reported; cannot verify the model beats a baseline",
                           f"Compute baseline metrics ({plan.ml.baseline})")]
        return []
    out: list[SanityIssue] = []
    for name, val in m.metrics.items():
        base = m.baseline_metrics.get(name)
        d = metric_direction(name)
        if base is None or d == 0:
            continue
        if (val - base) * d <= 0:
            out.append(_issue("high", "below_baseline", f"Model {name} {val:.4g} is no better than baseline {base:.4g}",
                              "Revisit features/model or report the baseline as the result"))
    return out


def _stat_tests(r: Results) -> list[SanityIssue]:
    out: list[SanityIssue] = []
    for t in r.stat_tests:
        if t.n < 30:
            out.append(_issue("medium", "stat_test", f"Test '{t.key}' uses a small sample (n={t.n})"))
        if not t.test.strip() or t.p_value is None:
            out.append(_issue("medium", "stat_test", f"Test '{t.key}' must report both the test name and p-value"))
        elif is_bad(t.p_value) or not 0 <= t.p_value <= 1:
            out.append(_issue("high", "stat_test", f"Test '{t.key}' p-value {t.p_value} outside 0-1"))
    return out


def _plan_conformance(r: Results, plan: AnalysisPlan) -> list[SanityIssue]:
    keys = r.keys() | {"summary", "model", "kpis", "series", "tables", "stat_tests", "insights_raw"}
    if r.model is not None:
        keys |= {f"model.metrics.{n}" for n in r.model.metrics}
    out: list[SanityIssue] = []
    for exp in plan.expected_outputs:
        e = exp.strip()
        if not _IDENT.match(e):
            continue  # free text, left to the LLM review
        last = e.split(".")[-1]
        if e not in keys and last not in keys:
            out.append(_issue("low", "plan_mismatch", f"Expected output '{e}' missing from results"))
    return out


def run_layer1(results: Results, input_rows: int, input_date_range: DateRange | None,
               plan: AnalysisPlan) -> tuple[list[SanityIssue], int, int]:
    """Run all Layer-1 rule families; each family counts as one check."""
    families: list[Callable[[], list[SanityIssue]]] = [
        lambda: _row_accounting(results, input_rows),
        lambda: _bad_numbers(results),
        lambda: _range_rules(results),
        lambda: _date_coverage(results, input_date_range),
        lambda: _ml_too_good(results),
        lambda: _ml_too_bad(results, plan),
        lambda: _stat_tests(results),
        lambda: _plan_conformance(results, plan),
    ]
    issues: list[SanityIssue] = []
    passed = 0
    for fam in families:
        found = fam()
        issues += found
        passed += not found
    return issues, len(families), passed


# ---------------------------------------------------------------- Layer 2

def resolve_ref(results: Results, ref: str) -> float | None:
    """Resolve 'summary.x', 'kpis.<key>', 'tables.<key>.<row>.<col>', 'model.metrics.<name>'."""
    parts = ref.split(".")
    head, rest = parts[0], parts[1:]
    val: Any = None
    if head == "summary" and len(rest) == 1:
        val = getattr(results.summary, rest[0], None)
        if val is None and results.summary.model_extra:
            val = results.summary.model_extra.get(rest[0])
    elif head == "kpis" and len(rest) == 1:
        val = next((k.value for k in results.kpis if k.key == rest[0]), None)
    elif head == "model" and len(rest) == 2 and results.model is not None:
        src = {"metrics": results.model.metrics, "baseline_metrics": results.model.baseline_metrics}.get(rest[0], {})
        val = src.get(rest[1])
    elif head == "tables" and len(rest) == 3:
        t = next((t for t in results.tables if t.key == rest[0]), None)
        row = None
        if t is not None:
            # Row by first-column label (what the spot-check prompt asks for), else by index.
            row = next((r for r in t.rows if r and str(r[0]) == rest[1]), None)
            if row is None and rest[1].isdigit() and int(rest[1]) < len(t.rows):
                row = t.rows[int(rest[1])]
        if row is not None:
            ci = int(rest[2]) if rest[2].isdigit() else (t.columns.index(rest[2]) if rest[2] in t.columns else -1)
            val = row[ci] if 0 <= ci < len(row) else None
    if isinstance(val, str):
        try:
            val = float(val)
        except ValueError:
            return None
    return float(val) if is_number(val) and not is_bad(val) else None


def compare_spot_checks(spot: list[SpotCheck], results: Results) -> list[SanityIssue]:
    """Compare recomputed numbers with results.json (relative tolerance)."""
    out: list[SanityIssue] = []
    for sc in spot:
        actual = resolve_ref(results, sc.results_ref)
        if actual is None:
            actual = sc.actual
        if actual is None:
            out.append(_issue("low", "spot_check", f"Spot check '{sc.name}': cannot resolve '{sc.results_ref}'", layer=2))
            continue
        denom = max(abs(sc.expected), 1e-12)
        diff = abs(actual - sc.expected) / denom
        if diff > sc.tolerance:
            out.append(_issue("high", "spot_check",
                              f"Spot check '{sc.name}': results.json {sc.results_ref}={actual:g} but raw data gives "
                              f"{sc.expected:g} ({diff:.1%} off)",
                              "Recheck the aggregation/filters used for this number", layer=2))
    return out


def summarize(issues: list[SanityIssue], run: int, passed: int) -> SanityReport:
    """Any high -> fail, any medium -> warn, else pass."""
    sev = {i.severity for i in issues}
    status = "fail" if "high" in sev else "warn" if "medium" in sev else "pass"
    return SanityReport(status=status, issues=issues, checks_run=run, checks_passed=passed)
