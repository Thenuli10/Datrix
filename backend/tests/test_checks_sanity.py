"""Layer 1 + Layer 2 sanity rules (PLAN.md §7a, §12 planted problems)."""
import math

from app.checks.sanity_rules import compare_spot_checks, run_layer1, summarize
from app.schemas.checks import SanityIssue, SpotCheck
from app.schemas.plan import AnalysisPlan, MLSpec, PlanStep
from app.schemas.results import KPI, ModelInfo, Results, Series, StatTest, Summary, Table


def _plan(ml: bool = False, expected: list[str] | None = None) -> AnalysisPlan:
    spec = MLSpec(problem="classification", target="churn", model_family="lightgbm",
                  validation="random 80/20", metrics=["auc"], baseline="majority class") if ml else None
    return AnalysisPlan(path="ml" if ml else "script", title="t", rationale="r",
                        steps=[PlanStep(title="s", detail="d")], ml=spec, expected_outputs=expected or [])


def _results(**kw) -> Results:
    base = dict(summary=Summary(title="t", rows_processed=1000))
    base.update(kw)
    return Results(**base)


def _checks(issues: list[SanityIssue]) -> set[str]:
    return {i.check for i in issues}


def _run(r: Results, rows: int = 1000, rng=None, plan: AnalysisPlan | None = None):
    return run_layer1(r, rows, rng, plan or _plan())


def test_clean_results_pass():
    r = _results(kpis=[KPI(key="churn_rate", label="Churn rate", value=0.12, format="percent")],
                 series=[Series(key="rev", x=["2024-01-01", "2024-02-01"], y=[1.0, 2.0])])
    issues, run, passed = _run(r, rng=("2024-01-01", "2024-12-31"))
    assert issues == []
    assert run == passed == 8
    assert summarize(issues, run, passed).status == "pass"


def test_half_rows_silently_dropped():
    issues, run, passed = _run(_results(summary=Summary(title="t", rows_processed=500)))
    assert any(i.check == "row_accounting" and i.severity == "high" for i in issues)
    assert passed == run - 1
    assert summarize(issues, run, passed).status == "fail"


def test_documented_drop_ok_and_extra_rows_flagged():
    ok = _results(summary=Summary(title="t", rows_processed=500, rows_dropped=500, drop_reasons=["null target"]))
    assert _run(ok)[0] == []
    issues, *_ = _run(_results(summary=Summary(title="t", rows_processed=1200)))
    assert [i.severity for i in issues] == ["medium"]


def test_bad_numbers():
    r = _results(kpis=[KPI(key="a", label="A", value=None), KPI(key="b", label="B", value=math.inf)],
                 series=[Series(key="s", x=[1, 2, 3, 4], y=[1.0, None, None, None])],
                 tables=[Table(key="t", columns=["v"], rows=[[math.nan]])])
    issues, *_ = _run(r)
    bad = [i for i in issues if i.check == "bad_numbers"]
    assert len(bad) == 4
    assert {i.severity for i in bad} == {"high", "medium"}


def test_series_few_nones_is_low():
    issues, *_ = _run(_results(series=[Series(key="s", x=[1, 2, 3], y=[1.0, None, 2.0])]))
    assert [i.severity for i in issues] == ["low"]


def test_range_rules():
    r = _results(
        kpis=[KPI(key="conv", label="Conversion", value=0.4, format="percent"),
              KPI(key="ret", label="Retention", value=1.5, format="percent")],  # 0-100 convention: fine
        series=[Series(key="market_share", x=["a", "b"], y=[0.3, 0.3]),
                Series(key="order_count", x=["a", "b"], y=[5, -1]),
                Series(key="churn_prob", x=["a"], y=[1.2])])
    issues, *_ = _run(r)
    msgs = " ".join(i.message for i in issues if i.check == "range")
    assert "market_share" in msgs and "order_count" in msgs and "churn_prob" in msgs
    assert "ret" not in msgs

    out = _run(_results(kpis=[KPI(key="a", label="A", value=0.4, format="percent"),
                              KPI(key="b", label="B", value=140, format="percent")]))[0]
    assert any("'b'" in i.message for i in out)


def test_date_coverage():
    rng = ("2024-01-01", "2024-06-30")
    r = _results(series=[Series(key="hist", x=["2023-12-01", "2024-02-01"], y=[1, 2]),
                         Series(key="fc", x=["2024-06-01", "2024-07-01"], y=[1, 2], is_forecast=True)])
    issues, *_ = _run(r, rng=rng)
    sev = {i.message.split("'")[1]: i.severity for i in issues}
    assert sev == {"hist": "medium", "fc": "high"}
    ok = _results(series=[Series(key="fc", x=["2024-07-01"], y=[1], is_forecast=True)])
    assert _run(ok, rng=rng)[0] == []


def test_date_range_from_summary():
    r = _results(summary=Summary(title="t", rows_processed=1000, input_date_max="2024-06-30",
                                 input_date_min="2024-01-01"),
                 series=[Series(key="fc", x=["2024-05-01"], y=[1], is_forecast=True)])
    assert "date_coverage" in _checks(_run(r)[0])


def test_target_leakage_auc():
    r = _results(model=ModelInfo(type="lgbm", metrics={"auc": 0.995}, baseline_metrics={"auc": 0.5}))
    issues, *_ = _run(r, plan=_plan(ml=True))
    leak = [i for i in issues if i.check == "target_leakage"]
    assert len(leak) == 1 and leak[0].severity == "high"
    assert summarize(issues, 8, 7).status == "fail"


def test_leakage_r2_and_accuracy():
    r = _results(model=ModelInfo(type="x", metrics={"r2": 0.995, "accuracy": 0.999},
                                 baseline_metrics={"r2": 0.0, "accuracy": 0.6}))
    assert len([i for i in _run(r)[0] if i.check == "target_leakage"]) == 2


def test_below_baseline_direction_aware():
    r = _results(model=ModelInfo(type="x", metrics={"auc": 0.6, "rmse": 12.0, "mae": 3.0},
                                 baseline_metrics={"auc": 0.7, "rmse": 10.0, "mae": 4.0}))
    bad = [i for i in _run(r)[0] if i.check == "below_baseline"]
    assert {i.message.split()[1] for i in bad} == {"auc", "rmse"}


def test_missing_baseline_when_ml_planned():
    r = _results(model=ModelInfo(type="x", metrics={"auc": 0.8}))
    issues, *_ = _run(r, plan=_plan(ml=True))
    assert [(i.check, i.severity) for i in issues] == [("below_baseline", "medium")]
    assert summarize(issues, 8, 7).status == "warn"


def test_stat_tests():
    r = _results(stat_tests=[
        StatTest(key="small", test="t-test", statistic=1.0, p_value=0.04, n=10, conclusion=""),
        StatTest(key="nop", test="", statistic=None, p_value=None, n=100, conclusion=""),
        StatTest(key="badp", test="chi2", statistic=2.0, p_value=1.7, n=100, conclusion="")])
    issues = [i for i in _run(r)[0] if i.check == "stat_test"]
    assert [(i.message.split("'")[1], i.severity) for i in issues] == [
        ("small", "medium"), ("nop", "medium"), ("badp", "high")]


def test_plan_expected_outputs():
    r = _results(kpis=[KPI(key="churn_rate", label="Churn", value=0.1)])
    issues, *_ = _run(r, plan=_plan(expected=["churn_rate", "kpis.total_revenue", "a chart of revenue by month"]))
    assert [(i.check, i.severity) for i in issues] == [("plan_mismatch", "low")]
    assert "total_revenue" in issues[0].message


def test_spot_check_wrong_total():
    r = _results(kpis=[KPI(key="total_revenue", label="Revenue", value=90_000.0)],
                 tables=[Table(key="seg", columns=["name", "revenue"], rows=[["a", 10.0]])],
                 model=ModelInfo(type="x", metrics={"auc": 0.8}))
    spots = [SpotCheck(name="total", results_ref="kpis.total_revenue", expected=100_000.0),
             SpotCheck(name="rows", results_ref="summary.rows_processed", expected=1000),
             SpotCheck(name="cell", results_ref="tables.seg.0.revenue", expected=10.0),
             SpotCheck(name="auc", results_ref="model.metrics.auc", expected=0.8),
             SpotCheck(name="gone", results_ref="kpis.nope", expected=1.0)]
    issues = compare_spot_checks(spots, r)
    assert [(i.severity, i.message.split("'")[1]) for i in issues] == [("high", "total"), ("low", "gone")]
    assert all(i.layer == 2 and i.check == "spot_check" for i in issues)
    assert summarize(issues, 5, 3).status == "fail"


def test_summarize_low_only_passes():
    rep = summarize([SanityIssue(severity="low", check="x", message="m")], 3, 2)
    assert rep.status == "pass" and rep.checks_run == 3 and rep.checks_passed == 2


def test_resolve_series_refs():
    """Spot-checks may point at a series point; month labels match month-start dates (seen in a live run)."""
    from app.checks.sanity_rules import resolve_ref
    r = Results.model_validate({"summary": {"title": "t", "rows_processed": 1}, "series": [
        {"key": "monthly_revenue", "x": ["2026-01", "2026-02"], "y": [10.0, 20.0]}]})
    assert resolve_ref(r, "series.monthly_revenue.2026-02") == 20.0
    assert resolve_ref(r, "series.monthly_revenue[2026-01-01]") == 10.0
    assert resolve_ref(r, "series.monthly_revenue.2026-03") is None
    assert resolve_ref(r, "series.missing.2026-01") is None
