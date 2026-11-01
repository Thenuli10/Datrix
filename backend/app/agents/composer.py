"""Dashboard Composer (Stage 5): DashboardSpec bound to results.json keys on a 12-col grid."""
from typing import Any

from app.agents._common import load_prompt, to_json
from app.llm.base import LLMClient
from app.schemas.checks import DashboardIssue
from app.schemas.dashboard import GRID_COLUMNS, Binding, DashboardSpec, Layout, Widget
from app.schemas.plan import AnalysisPlan
from app.schemas.results import Results


def results_catalog(r: Results) -> dict[str, Any]:
    """What the composer may bind to: keys + shape metadata, no bulk data."""
    return {
        "summary": r.summary.model_dump(mode="json"),
        "kpis": [{"key": k.key, "label": k.label, "format": k.format, "value": k.value} for k in r.kpis],
        "series": [{"key": s.key, "label": s.label, "n_points": len(s.x), "x_label": s.x_label,
                    "y_label": s.y_label, "group": s.group, "kind": s.kind, "is_forecast": s.is_forecast,
                    "has_interval": s.y_lower is not None and s.y_upper is not None, "format": s.format,
                    "x_sample": s.x[:3]} for s in r.series],
        "tables": [{"key": t.key, "label": t.label, "columns": t.columns, "n_rows": len(t.rows),
                    "column_formats": t.column_formats, "first_row": t.rows[0] if t.rows else None}
                   for t in r.tables],
        "model": None if r.model is None else {
            "type": r.model.type, "metrics": r.model.metrics, "baseline_metrics": r.model.baseline_metrics,
            "has_feature_importance": bool(r.model.feature_importance),
            "has_confusion_matrix": r.model.confusion_matrix is not None, "class_labels": r.model.class_labels},
        "stat_tests": [{"key": s.key, "test": s.test, "p_value": s.p_value} for s in r.stat_tests],
        "insights_raw": r.insights_raw,
    }


def compose(llm: LLMClient, results: Results, plan: AnalysisPlan, pid: int | None,
            qa_issues: list[DashboardIssue] | None = None, previous: DashboardSpec | None = None) -> DashboardSpec:
    user = (f"## Plan\n{to_json({'title': plan.title, 'path': plan.path, 'rationale': plan.rationale})}\n\n"
            f"## results.json catalog (bind only to these keys)\n{to_json(results_catalog(results))}")
    if previous is not None:
        user += f"\n\n## Previous dashboard spec (edit it, keep widget ids stable)\n{to_json(previous)}"
    if qa_issues:
        user += f"\n\n## Dashboard QA issues to fix\n{to_json(qa_issues)}"
    spec = llm.structured(agent="composer", system=load_prompt("composer"), user=user, schema=DashboardSpec,
                          project_id=pid)
    spec = prune_spec(spec, results)
    return spec if spec.widgets else default_spec(results, plan.title)


def _valid_binding(w: Widget, r: Results) -> bool:
    """Filter binding keys to those present in results; False if the widget has nothing left to show."""
    b = w.binding
    if b.source == "model":
        if r.model is None:
            return False
        if w.type == "confusion_matrix":
            return r.model.confusion_matrix is not None
        if w.type == "feature_importance":
            return bool(r.model.feature_importance)
        return True
    if b.source == "insights":
        return bool(r.insights_raw or (w.text and w.text.strip()))
    present = {"kpis": {k.key for k in r.kpis}, "series": {s.key for s in r.series},
               "tables": {t.key for t in r.tables}, "stat_tests": {s.key for s in r.stat_tests}}[b.source]
    b.keys = [k for k in dict.fromkeys(b.keys) if k in present]
    if not b.keys:
        return False
    if b.source == "tables":
        cols = {c for t in r.tables if t.key in b.keys for c in t.columns}
        if b.x_column and b.x_column not in cols:
            return False
        b.y_columns = [c for c in b.y_columns if c in cols]
        w.hidden_columns = [c for c in w.hidden_columns if c in cols]
    if w.type == "forecast_with_interval" and not any(
            s.key in b.keys and s.y_lower is not None and s.y_upper is not None for s in r.series):
        w.type = "line"  # no interval data: degrade instead of drawing an empty band
    return True


def prune_spec(spec: DashboardSpec, results: Results) -> DashboardSpec:
    """Drop widgets bound to missing keys, dedupe ids, clamp layout to the grid, register tabs."""
    seen: set[str] = set()
    widgets = []
    for w in spec.widgets:
        if w.id in seen or not _valid_binding(w, results):
            continue
        seen.add(w.id)
        w.layout.w = min(w.layout.w, GRID_COLUMNS)
        w.layout.x = min(w.layout.x, GRID_COLUMNS - w.layout.w)
        widgets.append(w)
    spec.widgets = widgets
    spec.tabs = list(dict.fromkeys([*spec.tabs, *(w.tab for w in widgets)])) or ["Overview"]
    spec.filters = [f for f in spec.filters if any(t.key == f.table_key and f.column in t.columns
                                                   for t in results.tables)]
    return spec


def default_spec(r: Results, title: str | None = None) -> DashboardSpec:
    """Deterministic layout used when the LLM spec is empty (also the offline/fake default)."""
    widgets: list[Widget] = []
    y = 0
    add = widgets.append
    kpis = r.kpis[:8]
    for i, k in enumerate(kpis):
        per_row = min(4, len(kpis))
        width = GRID_COLUMNS // per_row
        add(Widget(id=f"kpi_{k.key}", type="kpi", title=k.label, binding=Binding(source="kpis", keys=[k.key]),
                   layout=Layout(x=(i % per_row) * width, y=y + (i // per_row) * 2, w=width, h=2), format=k.format))
    y += 2 * -(-len(kpis) // 4) if kpis else 0
    for s in r.series:
        is_fc = s.y_lower is not None and s.y_upper is not None
        add(Widget(id=f"series_{s.key}", type="forecast_with_interval" if is_fc else "line",
                   title=s.label or s.key.replace("_", " ").capitalize(), binding=Binding(source="series",
                   keys=[s.key]), layout=Layout(x=0, y=y, w=12, h=4), x_label=s.x_label, y_label=s.y_label,
                   format=s.format))
        y += 4
    if r.model and r.model.feature_importance:
        add(Widget(id="feature_importance", type="feature_importance", title="Feature importance",
                   binding=Binding(source="model", keys=["feature_importance"]), layout=Layout(x=0, y=y, w=6, h=4),
                   orientation="horizontal"))
    if r.model and r.model.confusion_matrix is not None:
        add(Widget(id="confusion_matrix", type="confusion_matrix", title="Confusion matrix",
                   binding=Binding(source="model", keys=["confusion_matrix"]), layout=Layout(x=6, y=y, w=6, h=4)))
    if r.model and (r.model.feature_importance or r.model.confusion_matrix is not None):
        y += 4
    for t in r.tables:
        add(Widget(id=f"table_{t.key}", type="table", title=t.label or t.key.replace("_", " ").capitalize(),
                   binding=Binding(source="tables", keys=[t.key]), layout=Layout(x=0, y=y, w=12, h=4),
                   hidden_columns=t.columns[8:]))
        y += 4
    if r.stat_tests:
        add(Widget(id="stat_tests", type="table", title="Statistical tests",
                   binding=Binding(source="stat_tests", keys=[s.key for s in r.stat_tests]),
                   layout=Layout(x=0, y=y, w=12, h=3)))
        y += 3
    if r.insights_raw:
        add(Widget(id="insights", type="text_insight", title="Key insights", binding=Binding(source="insights"),
                   layout=Layout(x=0, y=y, w=12, h=3), text="\n".join(f"- {s}" for s in r.insights_raw)))
    return DashboardSpec(title=title or r.summary.title, widgets=widgets)
