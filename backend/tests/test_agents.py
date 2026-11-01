"""Every agent end-to-end with FakeLLMClient (no network)."""
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from app.agents import analyst, automap, coder, composer, dashboard_qa, insights, planner, sanity, validator
from app.agents._common import PROMPTS_DIR, load_prompt, prompt_version
from app.core.config import settings
from app.llm.fake import FakeLLMClient, minimal_instance
from app.schemas import (
    AnalysisPlan, ColumnProfile, ContractColumn, DashboardIssue, DashboardSpec, DataContract, DataSpec,
    DatasetProfile, MLSpec, PlanStep, RequirementAnalysis, Results, SanityIssue, SpecColumn, ValidationReport,
)

AGENTS = ["analyst", "validator", "planner", "coder", "coder_spot_check", "sanity", "composer", "dashboard_qa",
          "insights", "automap"]


@pytest.fixture
def fake():
    return FakeLLMClient()


@pytest.fixture
def df():
    return pd.DataFrame({"CustID": [1, 2, 3, 4], "Amount": [10.0, 20.0, None, 40.0],
                         "Seg": ["a", "b", "a", "a"], "Day": ["2024-01-01", "2024-01-02", "x", "2024-01-04"]})


@pytest.fixture
def profile(df):
    cols = [ColumnProfile(name=c, inferred_type="string", null_pct=0, unique_count=4) for c in df.columns]
    return DatasetProfile(dataset_id=1, file_name="sales.csv", row_count=4, column_count=4, columns=cols,
                          sample_rows=[{"CustID": i} for i in range(50)])


@pytest.fixture
def spec():
    return DataSpec(granularity="one order", columns=[
        SpecColumn(name="customer_id", type="integer", description="id"),
        SpecColumn(name="revenue", type="float", description="amount"),
        SpecColumn(name="region", type="string", description="region", required=False)])


@pytest.fixture
def results():
    return Results.model_validate({
        "summary": {"title": "Sales", "rows_processed": 4},
        "kpis": [{"key": "total", "label": "Total", "value": 70.0, "format": "currency"}],
        "series": [{"key": "daily", "x": ["2024-01-01"], "y": [10.0]},
                   {"key": "fc", "x": ["2024-01-05"], "y": [12.0], "y_lower": [10.0], "y_upper": [14.0],
                    "is_forecast": True}],
        "tables": [{"key": "segs", "columns": ["seg", "revenue"], "rows": [["a", 50.0]]}],
        "model": {"type": "lgbm", "metrics": {"auc": 0.8}, "feature_importance": [{"feature": "f", "importance": 1}]},
        "insights_raw": ["Segment a leads"]})


@pytest.fixture
def plan():
    return AnalysisPlan(path="script", title="Sales", rationale="r", steps=[PlanStep(title="t", detail="d")],
                        expected_outputs=["kpis.total"])


def test_prompts_exist_and_versioned():
    for name in AGENTS:
        raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        assert raw.startswith("<!-- version: ")
        assert prompt_version(name).isdigit() and not load_prompt(name).startswith("<!--")


def test_analyst_normalizes(fake):
    ra = minimal_instance(RequirementAnalysis)
    ra.data_spec.columns = [SpecColumn(name="Order Date", type="date", description="d"),
                            SpecColumn(name="orderDate", type="date", description="d")]
    fake.register("analyst", ra)
    out = analyst.analyze(fake, "forecast sales", {"domain": "retail"}, [("user", "monthly")], 1)
    assert [c.name for c in out.data_spec.columns] == ["order_date"] and out.ready
    assert "forecast sales" in fake.calls[0]["user"] and "[user] monthly" in fake.calls[0]["user"]
    ra2 = minimal_instance(RequirementAnalysis).model_copy(update={"clarifying_questions": ["Horizon?"],
                                                                   "ready": True})
    fake.register("analyst", ra2)
    assert analyst.analyze(fake, "x", {}, [], 1).ready is False


def test_validator_tools(df, profile):
    tools = validator.build_tools([profile], {1: df, 2: pd.DataFrame({"cid": [1, 2, 9]})})
    assert set(tools) == {"get_profile", "get_sample", "column_stats", "value_counts", "check_join"}
    assert len(tools["get_sample"][1](dataset_id=1, n=10_000)) == len(df)
    big = {1: pd.DataFrame({"a": range(500)})}
    assert len(validator.build_tools([], big)["get_sample"][1](1, 500)) == settings.llm_sample_rows
    assert len(tools["get_profile"][1](1)["sample_rows"]) == settings.llm_sample_rows
    st = tools["column_stats"][1](1, "Amount")
    assert st["null_pct"] == 25.0 and st["mean"] == pytest.approx(70 / 3)
    assert tools["column_stats"][1](1, "Day")["date_parse_rate"] == 0.75
    assert tools["value_counts"][1](1, "Seg", top=500)[0] == {"value": "a", "count": 3}
    j = tools["check_join"][1](1, 2, "CustID", "cid")
    assert j["a_rows_matched_pct"] == 50.0 and j["b_rows_matched_pct"] == pytest.approx(66.67)
    with pytest.raises(ValueError):
        tools["column_stats"][1](1, "nope")
    assert tools["get_profile"][1]("sales.csv")["dataset_id"] == 1


def test_validator_end_to_end(fake, df, profile, spec):
    def agent(system, user, schema, tools):
        assert tools["value_counts"][1](1, "Seg")
        return {"status": "ready", "mapping": [
            {"spec_column": "customer_id", "dataset_id": 1, "source_column": "CustID"},
            {"spec_column": "revenue", "dataset_id": 1, "source_column": "Invented"}],
            "joins": [{"left_dataset_id": 1, "right_dataset_id": 1, "left_key": "CustID", "right_key": "CustID"}]}

    fake.register("validator", agent)
    rep = validator.validate(fake, spec, [profile], {1: df}, 1)
    assert [m.source_column for m in rep.mapping] == ["CustID"]
    assert rep.status == "needs_more_data"
    assert any(g.column == "revenue" and g.severity == "blocker" for g in rep.gaps)
    assert not any(g.column == "region" for g in rep.gaps)
    assert rep.joins[0].match_rate == 1.0


def test_planner_enforces_rules(fake, profile):
    p = AnalysisPlan(path="ml", title="t", rationale="r", steps=[], expected_outputs=[],
                     ml=MLSpec(problem="classification", target="churn", features=["churn", "age", "cust_id"],
                               excluded_columns=["cust_id"], model_family="lightgbm", validation="v",
                               metrics=["auc"], baseline=""))
    fake.register("planner", p)
    out = planner.plan(fake, "req", minimal_instance(RequirementAnalysis), minimal_instance(ValidationReport),
                       [profile], 1)
    assert out.ml.features == ["age"] and out.ml.baseline == "majority class"
    assert planner.plan(FakeLLMClient(), "r", minimal_instance(RequirementAnalysis),
                        minimal_instance(ValidationReport), [profile], 1).path == "script"


def test_coder_prompt_and_fences(fake, plan, profile):
    sys = coder.system_prompt()
    assert "{{" not in sys and "rows_processed" in sys and "y_lower" in sys and "sklearn" in sys
    fake.register("coder", "Here you go:\n```python\ndef run(input_dir, output_dir, params):\n    pass\n```\nDone")
    code = coder.generate(fake, plan, [profile], {"files": ["sales"]}, 1)
    assert code == "def run(input_dir, output_dir, params):\n    pass\n"
    assert "PATH: script" in fake.calls[0]["user"]
    assert coder.strip_code_fences("x = 1") == "x = 1\n"


def test_fix_loop_retries_then_succeeds(fake, plan, profile, monkeypatch):
    monkeypatch.setattr(coder, "_static_violations", lambda c: ["banned import socket"] if "socket" in c else [])
    fake.register("coder", ["import socket", "```python\nbad()\n```", "```python\ngood()\n```"])
    runs, logs = [], []

    def run_fn(code):
        runs.append(code)
        ok = "good" in code
        return NS(ok=ok, error=None if ok else "NameError: bad", stderr="Traceback...", stdout="")

    code, res = coder.fix_loop(fake, plan, [profile], {}, 1, run_fn, on_log=logs.append)
    assert code == "good()\n" and res.ok
    assert runs == ["bad()\n", "good()\n"]  # static-rejected code is never run
    assert "Static safety check" in fake.calls[1]["user"] and "NameError: bad" in fake.calls[2]["user"]
    assert logs


def test_fix_loop_gives_up(fake, plan, profile, monkeypatch):
    monkeypatch.setattr(settings, "max_fix_attempts", 2)
    fake.register("coder", "x()")
    code, res = coder.fix_loop(fake, plan, [profile], {}, 1, lambda c: NS(ok=False, error="boom", stderr="",
                                                                            stdout=""))
    assert code == "x()\n" and not res.ok and len(fake.calls) == 2


def test_spot_check(fake, plan, results):
    src = coder.generate_spot_check(fake, plan, results, {"files": []}, 1)
    assert "def spot_check" in src and "kpis" in fake.calls[0]["user"]


def test_sanity(fake, plan, profile, results):
    fake.register("sanity", {"status": "pass", "issues": [
        {"severity": "high", "check": "target_leakage", "message": "AUC too high"}]})
    rep = sanity.review(fake, "req", plan, [profile], results,
                        [SanityIssue(severity="low", check="range", message="m")], 1)
    assert rep.status == "fail" and rep.issues[0].layer == 3 and rep.checks_run == 4 and rep.checks_passed == 3
    clean = sanity.review(FakeLLMClient(), "req", plan, [profile], results, [], 1)
    assert clean.status == "pass"


def test_composer_drops_missing_keys(fake, plan, results):
    fake.register("composer", {"title": "D", "widgets": [
        {"id": "k", "type": "kpi", "title": "Total", "binding": {"source": "kpis", "keys": ["total", "ghost"]},
         "layout": {"x": 0, "y": 0, "w": 3, "h": 2}},
        {"id": "gone", "type": "line", "title": "G", "binding": {"source": "series", "keys": ["nope"]},
         "layout": {"x": 0, "y": 2, "w": 12, "h": 4}},
        {"id": "cm", "type": "confusion_matrix", "title": "CM", "binding": {"source": "model"},
         "layout": {"x": 0, "y": 6, "w": 6, "h": 4}},
        {"id": "fc", "type": "forecast_with_interval", "title": "F", "binding": {"source": "series",
         "keys": ["daily"]}, "layout": {"x": 9, "y": 6, "w": 6, "h": 4}, "tab": "Details"},
        {"id": "t", "type": "bar", "title": "T", "binding": {"source": "tables", "keys": ["segs"],
         "x_column": "missing"}, "layout": {"x": 0, "y": 10, "w": 6, "h": 4}}]})
    spec = composer.compose(fake, results, plan, 1)
    assert [w.id for w in spec.widgets] == ["k", "fc"]
    assert spec.widgets[0].binding.keys == ["total"]
    assert spec.widgets[1].type == "line" and spec.widgets[1].layout.x + spec.widgets[1].layout.w <= 12
    assert "Details" in spec.tabs


def test_composer_fallback_and_revision(fake, plan, results):
    spec = composer.compose(FakeLLMClient(), results, plan, 1)
    types = {w.type for w in spec.widgets}
    assert {"kpi", "forecast_with_interval", "line", "feature_importance", "table", "text_insight"} <= types
    assert "confusion_matrix" not in types
    issue = DashboardIssue(severity="medium", widget_id="kpi_total", rule="vision", message="fix it")
    fake.register("composer", spec)
    composer.compose(fake, results, plan, 1, qa_issues=[issue], previous=spec)
    assert "fix it" in fake.calls[0]["user"] and "Previous dashboard spec" in fake.calls[0]["user"]


def test_dashboard_qa(fake, results):
    spec = composer.default_spec(results)
    fake.register("dashboard_qa", {"issues": [
        {"severity": "high", "widget_id": "kpi_total", "rule": "overlap", "message": "m", "auto_fixed": True},
        {"severity": "low", "widget_id": "unknown", "rule": "vision", "message": "m2"}]})
    issues = dashboard_qa.review(fake, spec, [b"png1", b"png2"], [], 1)
    assert issues[0].widget_id == "kpi_total" and not issues[0].auto_fixed and issues[1].widget_id is None
    assert fake.calls[0]["images"] == 2 and fake.calls[0]["model"] == settings.openai_vision_model
    assert dashboard_qa.review(fake, spec, [], [], 1) == []


def test_insights(fake, results):
    assert insights.write(FakeLLMClient(), "q", results, 1).startswith("## Key insights")
    fake.register("insights", "- Revenue is 70")
    assert insights.write(fake, "q", results, 1) == "## Key insights\n\n- Revenue is 70"


def test_automap(fake, profile):
    contract = DataContract(files=["sales.csv"], columns=[
        ContractColumn(name="customer_id", source_column="cust_id", dataset_index=0, type="integer",
                       nullable_pct=0),
        ContractColumn(name="revenue", source_column="Revenue USD", dataset_index=0, type="float", nullable_pct=0),
        ContractColumn(name="seg", source_column="Seg", dataset_index=0, type="string", nullable_pct=0)])
    fake.register("automap", {"pairs": [{"source_column": "Revenue USD", "new_column": "Amount"},
                                        {"source_column": "Seg", "new_column": "Bogus"}]})
    m = automap.suggest_mapping(fake, contract, [profile], 1)
    assert m == {"cust_id": "CustID", "Revenue USD": "Amount"}
    assert "Revenue USD" in fake.calls[0]["user"]


def test_all_agents_run_with_unregistered_fake(df, profile, spec, plan, results):
    f = FakeLLMClient()
    assert isinstance(analyst.analyze(f, "r", {}, [], None), RequirementAnalysis)
    assert isinstance(validator.validate(f, spec, [profile], {1: df}, None), ValidationReport)
    assert isinstance(planner.plan(f, "r", minimal_instance(RequirementAnalysis),
                                   minimal_instance(ValidationReport), [profile], None), AnalysisPlan)
    assert "def run" in coder.generate(f, plan, [profile], {}, None)
    assert isinstance(composer.compose(f, results, plan, None), DashboardSpec)
    assert dashboard_qa.review(f, composer.default_spec(results), [b"x"], [], None) == []
