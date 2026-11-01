"""Dashboard QA rule checks + auto-fixes (PLAN.md §7b, §12 planted layout problems)."""
from itertools import combinations

from app.checks.dashboard_rules import check_and_fix, layout_problems
from app.schemas.checks import DashboardIssue
from app.schemas.dashboard import GRID_COLUMNS, Binding, DashboardSpec, Layout, Widget
from app.schemas.results import KPI, Results, Series, Summary, Table


def _w(wid: str, type_: str = "bar", source: str = "series", keys: list[str] | None = None,
       x: int = 0, y: int = 0, w: int = 6, h: int = 4, **kw) -> Widget:
    kw.setdefault("x_label", "X")
    kw.setdefault("y_label", "Y")
    return Widget(id=wid, type=type_, title=kw.pop("title", wid.title()),
                  binding=Binding(source=source, keys=keys if keys is not None else ["s"], **kw.pop("binding", {})),
                  layout=Layout(x=x, y=y, w=w, h=h), **kw)


def _results(**kw) -> Results:
    base = dict(summary=Summary(title="t", rows_processed=10),
                series=[Series(key="s", x=["a", "b", "c"], y=[1, 2, 3])])
    base.update(kw)
    return Results(**base)


def _spec(*widgets: Widget) -> DashboardSpec:
    return DashboardSpec(title="D", widgets=list(widgets))


def _rules(issues: list[DashboardIssue]) -> set[str]:
    return {i.rule for i in issues}


def assert_no_overlaps(spec: DashboardSpec) -> None:
    """Every widget within the grid and no two widgets on the same tab share a cell."""
    for w in spec.widgets:
        assert 0 <= w.layout.x and w.layout.x + w.layout.w <= GRID_COLUMNS, w.id
    for a, b in combinations(spec.widgets, 2):
        if a.tab != b.tab:
            continue
        A, B = a.layout, b.layout
        disjoint = A.x + A.w <= B.x or B.x + B.w <= A.x or A.y + A.h <= B.y or B.y + B.h <= A.y
        assert disjoint, f"{a.id} overlaps {b.id}"


def test_clean_spec_untouched():
    spec = _spec(_w("a", x=0), _w("b", x=6))
    fixed, issues = check_and_fix(spec, _results())
    assert issues == [] and fixed == spec


def test_overlaps_repacked_reading_order_and_widths():
    spec = _spec(_w("a", x=0, y=0, w=8), _w("b", x=4, y=1, w=6), _w("c", x=8, y=0, w=4), _w("d", x=2, y=2, w=12))
    fixed, issues = check_and_fix(spec, _results())
    assert "overlap" in _rules(issues) and all(i.auto_fixed for i in issues)
    assert_no_overlaps(fixed)
    assert [w.layout.w for w in fixed.widgets] == [8, 6, 4, 12]
    order = sorted(fixed.widgets, key=lambda w: (w.layout.y, w.layout.x))
    assert [w.id for w in order] == ["a", "c", "b", "d"]
    assert layout_problems(fixed.widgets) == []
    assert spec.widgets[1].layout.x == 4  # input not mutated


def test_gap_repacked():
    fixed, issues = check_and_fix(_spec(_w("a", y=0), _w("b", y=10)), _results())
    assert _rules(issues) == {"gap"}
    assert fixed.widgets[1].layout.y == 0 and fixed.widgets[1].layout.x == 6


def test_too_many_series_top_n():
    keys = [f"s{i}" for i in range(10)]
    r = _results(series=[Series(key=k, x=[1, 2], y=[1, 2]) for k in keys])
    fixed, issues = check_and_fix(_spec(_w("m", "line", keys=keys, w=12)), r)
    assert fixed.widgets[0].binding.top_n == 8
    assert [(i.rule, i.auto_fixed) for i in issues] == [("too_many_series", True)]


def test_twenty_slice_pie_becomes_bar():
    r = _results(series=[Series(key="s", x=[f"c{i}" for i in range(20)], y=list(range(20)))])
    fixed, issues = check_and_fix(_spec(_w("p", "pie", w=12)), r)
    assert fixed.widgets[0].type == "bar"
    assert "pie_slices" in _rules(issues)


def test_long_labels_horizontal_bar():
    labels = ["x" * 60, "y" * 60]
    fixed, issues = check_and_fix(_spec(_w("b", "bar", w=12)), _results(series=[Series(key="s", x=labels, y=[1, 2])]))
    assert fixed.widgets[0].orientation == "horizontal"
    assert any(i.rule == "long_labels" and i.auto_fixed for i in issues)


def test_long_labels_line_flagged_low():
    r = _results(series=[Series(key="s", x=["z" * 30], y=[1])])
    fixed, issues = check_and_fix(_spec(_w("l", "line", w=12)), r)
    assert fixed.widgets[0].orientation == "vertical"
    assert [(i.rule, i.severity, i.auto_fixed) for i in issues] == [("long_labels", "low", True)]


def test_missing_title_and_axis_not_fixed():
    fixed, issues = check_and_fix(_spec(_w("a", title="", x_label=None, w=12)), _results())
    assert {(i.rule, i.auto_fixed) for i in issues} == {("missing_title", False), ("missing_axis", False)}
    # axis labels on the series itself are enough
    r = _results(series=[Series(key="s", x=[1], y=[1], x_label="Month", y_label="Rev")])
    assert check_and_fix(_spec(_w("b", x_label=None, y_label=None, w=12)), r)[1] == []


def test_unformatted_kpi():
    r = _results(kpis=[KPI(key="conv_rate", label="Conversion rate", value=0.123456),
                       KPI(key="rev", label="Revenue", value=12345.6789)])
    spec = _spec(_w("k1", "kpi", "kpis", ["conv_rate"], w=6, h=2), _w("k2", "kpi", "kpis", ["rev"], x=6, w=6, h=2))
    fixed, issues = check_and_fix(spec, r)
    assert [w.format for w in fixed.widgets] == ["percent", "compact"]
    assert _rules(issues) == {"unformatted"}


def test_empty_widget_removed():
    spec = _spec(_w("ok"), _w("gone", keys=["missing"], x=6), _w("k", "kpi", "kpis", ["none"], y=4))
    fixed, issues = check_and_fix(spec, _results())
    assert [w.id for w in fixed.widgets] == ["ok"]
    assert [(i.widget_id, i.rule) for i in issues if i.rule == "empty"] == [("gone", "empty"), ("k", "empty")]
    assert_no_overlaps(fixed)


def test_wide_table_hidden_columns():
    cols = [f"c{i}" for i in range(11)]
    r = _results(tables=[Table(key="t", columns=cols, rows=[list(range(11))])])
    fixed, issues = check_and_fix(_spec(_w("t", "table", "tables", ["t"], w=12)), r)
    assert fixed.widgets[0].hidden_columns == ["c8", "c9", "c10"]
    assert _rules(issues) == {"wide_table"}


def test_above_fold_moves_tables_then_scatter_to_details():
    r = _results(tables=[Table(key="t", columns=["a"], rows=[[1]])],
                 kpis=[KPI(key=f"k{i}", label=f"K{i}", value=i) for i in range(8)])
    widgets = [_w(f"k{i}", "kpi", "kpis", [f"k{i}"], x=(i % 4) * 3, y=(i // 4) * 2, w=3, h=2) for i in range(8)]
    widgets += [_w("sc", "scatter", x=0, y=4, w=6), _w("tb", "table", "tables", ["t"], x=6, y=4, w=6)]
    fixed, issues = check_and_fix(_spec(*widgets), r)
    moved = [i.widget_id for i in issues if i.rule == "above_fold"]
    assert moved == ["tb", "sc"]
    assert "Details" in fixed.tabs
    assert {w.id for w in fixed.widgets if w.tab == "Details"} == {"tb", "sc"}
    assert len([w for w in fixed.widgets if w.tab == "Overview" and w.layout.y < 8]) <= 8
    assert_no_overlaps(fixed)
    assert layout_problems([w for w in fixed.widgets if w.tab == "Details"]) == []
