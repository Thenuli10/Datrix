"""Comparison with the previous run (PLAN.md §7a repeat runs)."""
from app.checks.run_compare import compare
from app.schemas.results import KPI, ModelInfo, Results, Series, Summary


def _r(kpis: dict[str, float], metrics: dict[str, float] | None = None, series: tuple[str, ...] = ()) -> Results:
    return Results(summary=Summary(title="t", rows_processed=10),
                   kpis=[KPI(key=k, label=k, value=v) for k, v in kpis.items()],
                   series=[Series(key=s, x=[1], y=[1]) for s in series],
                   model=ModelInfo(type="x", metrics=metrics) if metrics is not None else None)


def test_no_change_no_issues():
    a = _r({"rev": 100.0}, {"auc": 0.8}, ("trend",))
    assert compare(a, a) == []


def test_kpi_jump():
    issues = compare(_r({"rev": 100.0, "orders": 50, "z": 0}), _r({"rev": 180.0, "orders": 60, "z": 3}))
    assert [(i.check, i.severity, i.layer) for i in issues] == [("kpi_jump", "medium", 4)] * 2
    assert "rev" in issues[0].message and "'z'" in issues[1].message


def test_metric_drop_direction_aware():
    prev = _r({}, {"accuracy": 0.90, "rmse": 10.0, "auc": 0.80})
    curr = _r({}, {"accuracy": 0.82, "rmse": 12.0, "auc": 0.79})
    issues = compare(prev, curr)
    assert {i.message.split()[1] for i in issues} == {"accuracy", "rmse"}
    assert all(i.check == "metric_drop" and i.severity == "high" and i.suggested_fix == "Retrain on new data"
               for i in issues)
    assert compare(curr, prev) == []  # improvements are fine


def test_missing_keys():
    issues = compare(_r({"rev": 1.0}, {"auc": 0.8, "f1": 0.5}, ("trend",)), _r({"rev": 1.0}, {"auc": 0.8}))
    assert len(issues) == 1 and issues[0].check == "structure_changed" and issues[0].severity == "high"
    assert "trend" in issues[0].message and "model.metrics.f1" in issues[0].message
    assert "model" in compare(_r({}, {"auc": 0.8}), _r({}))[0].message
