"""Comparison with the previous run on repeat runs (PLAN.md §7a, layer 4). Pure code."""
from app.checks.sanity_rules import is_bad, is_number, metric_direction
from app.core.config import settings
from app.schemas.checks import SanityIssue
from app.schemas.results import Results


def _issue(severity: str, check: str, message: str, fix: str = "") -> SanityIssue:
    return SanityIssue(severity=severity, check=check, message=message, suggested_fix=fix, layer=4)


def _kpi_jumps(prev: Results, curr: Results) -> list[SanityIssue]:
    before = {k.key: k.value for k in prev.kpis if is_number(k.value) and not is_bad(k.value)}
    out: list[SanityIssue] = []
    for k in curr.kpis:
        old, new = before.get(k.key), k.value
        if old is None or not is_number(new) or is_bad(new):
            continue
        if old == 0:
            if new != 0:
                out.append(_issue("medium", "kpi_jump", f"KPI '{k.key}' went from 0 to {new:g}"))
            continue
        change = (new - old) / abs(old)
        if abs(change) > settings.compare_kpi_jump:
            out.append(_issue("medium", "kpi_jump", f"KPI '{k.key}' changed {change:+.0%} ({old:g} -> {new:g})",
                              "Confirm the new data is complete and correctly mapped"))
    return out


def _metric_drops(prev: Results, curr: Results) -> list[SanityIssue]:
    """Higher-better metrics: absolute drop; lower-better (error) metrics: relative increase."""
    if prev.model is None or curr.model is None:
        return []
    out: list[SanityIssue] = []
    for name, old in prev.model.metrics.items():
        new = curr.model.metrics.get(name)
        d = metric_direction(name)
        if new is None or d == 0:
            continue
        worse = old - new if d > 0 else (new - old) / max(abs(old), 1e-12)
        if worse > settings.compare_metric_drop:
            shown = f"{worse:.3f}" if d > 0 else f"{worse:.0%}"
            out.append(_issue("high", "metric_drop", f"Model {name} worsened by {shown} ({old:.4g} -> {new:.4g})",
                              "Retrain on new data"))
    return out


def _structure(prev: Results, curr: Results) -> list[SanityIssue]:
    missing = sorted(prev.keys() - curr.keys())
    if prev.model is not None:
        if curr.model is None:
            missing.append("model")
        else:
            missing += [f"model.metrics.{m}" for m in sorted(set(prev.model.metrics) - set(curr.model.metrics))]
    if not missing:
        return []
    return [_issue("high", "structure_changed", f"Keys from the previous run are missing: {', '.join(missing)}",
                   "Check the pipeline still produces every output on the new data")]


def compare(prev: Results, curr: Results) -> list[SanityIssue]:
    """KPI jumps, ML metric drops and missing keys versus the previous run."""
    return [*_kpi_jumps(prev, curr), *_metric_drops(prev, curr), *_structure(prev, curr)]
