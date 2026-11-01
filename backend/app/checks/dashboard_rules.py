"""Dashboard QA Step 1: rule checks + auto-fixes on the dashboard spec (PLAN.md §7b).
Pure functions: no LLM, no I/O. Inputs are never mutated."""
import re
from typing import Any

from app.schemas.checks import DashboardIssue
from app.schemas.dashboard import GRID_COLUMNS, DashboardSpec, Widget
from app.schemas.results import Results

MAX_SERIES = 8
MAX_PIE_SLICES = 6
MAX_LABEL_CHARS = 20
MAX_TABLE_COLUMNS = 8
FOLD_ROWS = 8
MAX_ABOVE_FOLD = 8
OVERVIEW = "Overview"
DETAILS = "Details"

AXIS_TYPES = {"line", "bar", "scatter", "histogram", "forecast_with_interval"}
SERIES_CHART_TYPES = {"line", "bar", "scatter", "forecast_with_interval"}
# Higher = moved off the Overview first.
MOVE_PRIORITY = {"table": 9, "scatter": 8, "heatmap": 8, "histogram": 7, "confusion_matrix": 6,
                 "feature_importance": 5, "text_insight": 4, "pie": 3, "bar": 2, "line": 1,
                 "forecast_with_interval": 1, "kpi": 0}
_RATE_HINT = re.compile(r"rate|ratio|pct|percent|share|proportion|%", re.I)


def _issue(w: Widget | None, rule: str, severity: str, message: str, fixed: bool) -> DashboardIssue:
    return DashboardIssue(severity=severity, widget_id=w.id if w else None, rule=rule,
                          message=message, auto_fixed=fixed)


# ---------------------------------------------------------------- data lookups

def _categories(w: Widget, r: Results) -> list[Any]:
    """Category labels / slices the widget will draw."""
    b = w.binding
    if b.source == "series":
        series = [s for s in r.series if s.key in b.keys]
        return series[0].x if series else []
    if b.source == "tables":
        t = next((t for t in r.tables if t.key in b.keys), None)
        if t is None:
            return []
        ci = t.columns.index(b.x_column) if b.x_column in t.columns else 0
        return [row[ci] for row in t.rows if ci < len(row)]
    if b.source == "kpis":
        return [k.label for k in r.kpis if k.key in b.keys]
    return []


def _n_series(w: Widget) -> int:
    b = w.binding
    return len(b.y_columns) if b.source == "tables" else len(b.keys)


def _has_data(w: Widget, r: Results) -> bool:
    b, keys = w.binding, set(w.binding.keys)
    if w.type == "text_insight":
        return bool(w.text) or bool(r.insights_raw)
    match b.source:
        case "kpis":
            return any(k.key in keys and k.value is not None for k in r.kpis)
        case "series":
            return any(s.key in keys and s.y for s in r.series)
        case "tables":
            return any(t.key in keys and t.rows for t in r.tables)
        case "stat_tests":
            return any(not keys or s.key in keys for s in r.stat_tests)
        case "insights":
            return bool(r.insights_raw)
        case "model":
            m = r.model
            if m is None:
                return False
            if w.type == "feature_importance":
                return bool(m.feature_importance)
            if w.type == "confusion_matrix":
                return bool(m.confusion_matrix)
            return bool(m.metrics)
    return False


# ---------------------------------------------------------------- layout

def _cells(w: Widget) -> set[tuple[int, int]]:
    L = w.layout
    return {(x, y) for x in range(L.x, L.x + L.w) for y in range(L.y, L.y + L.h)}


def layout_problems(widgets: list[Widget]) -> list[DashboardIssue]:
    """Overlaps / off-grid widgets, and gaps (widgets that could float up)."""
    out: list[DashboardIssue] = []
    occupied: dict[tuple[int, int], str] = {}
    for w in sorted(widgets, key=lambda w: (w.layout.y, w.layout.x)):
        if w.layout.x + w.layout.w > GRID_COLUMNS:
            out.append(_issue(w, "overlap", "medium", "Widget extends past the 12-column grid", True))
        hit = next((occupied[c] for c in _cells(w) if c in occupied), None)
        if hit:
            out.append(_issue(w, "overlap", "medium", f"Widget overlaps '{hit}'", True))
        for c in _cells(w):
            occupied.setdefault(c, w.id)
    for w in widgets:
        L = w.layout
        if L.y > 0 and all((x, L.y - 1) not in occupied for x in range(L.x, min(L.x + L.w, GRID_COLUMNS))):
            out.append(_issue(w, "gap", "low", "Empty space above widget", True))
    return out


def repack(widgets: list[Widget]) -> None:
    """Deterministic shelf packing in (y, x) reading order, keeping widths and heights.

    x advances along a shelf and wraps at 12 columns; y drops to the skyline under the
    widget's columns, so there are no overlaps and no widget can float up.
    """
    heights = [0] * GRID_COLUMNS
    cursor = 0
    for w in sorted(widgets, key=lambda w: (w.layout.y, w.layout.x)):
        width = min(w.layout.w, GRID_COLUMNS)
        if cursor + width > GRID_COLUMNS:
            cursor = 0
        y = max(heights[cursor:cursor + width])
        w.layout.x, w.layout.y, w.layout.w = cursor, y, width
        for c in range(cursor, cursor + width):
            heights[c] = y + w.layout.h
        cursor += width


def _fold_count(widgets: list[Widget]) -> list[Widget]:
    return [w for w in widgets if w.tab == OVERVIEW and w.layout.y < FOLD_ROWS]


# ---------------------------------------------------------------- per-widget rules

def _content_rules(w: Widget, r: Results) -> list[DashboardIssue]:
    out: list[DashboardIssue] = []
    if not w.title.strip():
        out.append(_issue(w, "missing_title", "medium", "Widget has no title", False))

    if w.type in AXIS_TYPES:
        series = [s for s in r.series if s.key in w.binding.keys] if w.binding.source == "series" else []
        has_x = bool(w.x_label) or any(s.x_label for s in series)
        has_y = bool(w.y_label) or any(s.y_label for s in series)
        if not (has_x and has_y):
            miss = " and ".join(a for a, ok in (("x", has_x), ("y", has_y)) if not ok)
            out.append(_issue(w, "missing_axis", "low", f"Missing {miss} axis label", False))

    if w.type in SERIES_CHART_TYPES and _n_series(w) > MAX_SERIES and (w.binding.top_n or 99) > MAX_SERIES:
        w.binding.top_n = MAX_SERIES
        out.append(_issue(w, "too_many_series", "medium",
                          f"{_n_series(w)} series; keeping top {MAX_SERIES}, rest grouped as 'Other'", True))

    if w.type == "pie":
        n = len(_categories(w, r))
        if n > MAX_PIE_SLICES:
            w.type = "bar"
            out.append(_issue(w, "pie_slices", "medium", f"Pie with {n} slices switched to bar chart", True))

    cats = _categories(w, r)
    longest = max((len(str(c)) for c in cats), default=0)
    if longest > MAX_LABEL_CHARS:
        if w.type in {"bar", "histogram"}:
            if w.orientation != "horizontal":
                w.orientation = "horizontal"
                out.append(_issue(w, "long_labels", "low",
                                  f"Category labels up to {longest} chars; using horizontal bars", True))
        elif w.type in {"line", "scatter", "pie"}:
            out.append(_issue(w, "long_labels", "low",
                              f"Category labels up to {longest} chars; truncated with full text on hover", True))

    if w.type == "kpi" and w.binding.source == "kpis" and w.format in (None, "number"):
        for k in r.kpis:
            v = k.value
            if k.key in w.binding.keys and isinstance(v, float) and k.format == "number" and round(v, 3) != v:
                hint = _RATE_HINT.search(f"{k.key} {k.label}")
                w.format = "percent" if hint and 0 <= v <= 1 else "compact"
                out.append(_issue(w, "unformatted", "low", f"KPI '{k.key}' = {v} unformatted; using {w.format}", True))
                break

    if w.type == "table" and w.binding.source == "tables":
        t = next((t for t in r.tables if t.key in w.binding.keys), None)
        if t and len(t.columns) - len(set(w.hidden_columns) & set(t.columns)) > MAX_TABLE_COLUMNS:
            visible = [c for c in t.columns if c not in w.hidden_columns]
            w.hidden_columns = [*w.hidden_columns, *visible[MAX_TABLE_COLUMNS:]]
            out.append(_issue(w, "wide_table", "low",
                              f"Table has {len(t.columns)} columns; extra ones behind the column picker", True))
    return out


# ---------------------------------------------------------------- entry point

def check_and_fix(spec: DashboardSpec, results: Results) -> tuple[DashboardSpec, list[DashboardIssue]]:
    """Apply §7b rule checks; return a fixed copy of the spec and all issues found."""
    fixed = spec.model_copy(deep=True)
    issues: list[DashboardIssue] = []

    kept: list[Widget] = []
    for w in fixed.widgets:
        if _has_data(w, results):
            kept.append(w)
        else:
            issues.append(_issue(w, "empty", "medium", "Widget has no data in results; removed", True))
    fixed.widgets = kept

    for w in kept:
        issues += _content_rules(w, results)

    for tab in dict.fromkeys(w.tab for w in kept):
        on_tab = [w for w in kept if w.tab == tab]
        found = layout_problems(on_tab)
        if found:
            issues += found
            repack(on_tab)

    overview = [w for w in kept if w.tab == OVERVIEW]
    moved: list[Widget] = []
    while len(fold := _fold_count(overview)) > MAX_ABOVE_FOLD:
        victim = max(fold, key=lambda w: (MOVE_PRIORITY.get(w.type, 5), w.layout.y, w.layout.x))
        overview.remove(victim)
        victim.tab = DETAILS
        victim.layout.y += 10_000 + len(moved)  # after existing Details widgets
        moved.append(victim)
        repack(overview)
    if moved:
        repack([w for w in kept if w.tab == DETAILS])
        issues += [_issue(w, "above_fold", "low", f"Too many widgets above the fold; moved to '{DETAILS}' tab", True)
                   for w in moved]

    for tab in dict.fromkeys(w.tab for w in kept):
        if tab not in fixed.tabs:
            fixed.tabs.append(tab)
    return fixed, issues
