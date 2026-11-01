"""End-to-end through the HTTP API: requirement → upload → validate → plan → first run →
dashboard → re-runs (append, contract failure). Fake LLM, local sandbox, no screenshots."""
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.llm import set_llm
from app.llm.fake import FakeLLMClient
from app.models import Dataset
from app.schemas import (
    AnalysisPlan, ColumnMapping, DataSpec, PlanStep, RequirementAnalysis, SanityReport, SpecColumn,
    ValidationReport,
)

CSV = "order_date,Region,Amount\n" + "\n".join(
    f"2026-0{1 + i % 6}-1{i % 9},{'North' if i % 3 else 'South'},{10 + i}" for i in range(40))
CSV2 = "order_date,Region,Amount\n" + "\n".join(
    f"2026-07-1{i % 9},{'North' if i % 2 else 'South'},{12 + i}" for i in range(20))
CSV_BAD = "order_date,Area,Amount\n" + "\n".join(f"2026-08-1{i},North,{20 + i}" for i in range(8))

CODE = '''import json, os
import pandas as pd


def run(input_dir, output_dir, params):
    manifest = json.load(open(os.path.join(input_dir, "manifest.json")))
    df = pd.read_parquet(os.path.join(input_dir, manifest["files"][0]["path"]))
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    monthly = df.groupby(df["date"].dt.to_period("M"))["revenue"].sum()
    by_region = df.groupby("region")["revenue"].sum().sort_values(ascending=False)
    results = {
        "summary": {"title": "Sales overview", "rows_processed": int(len(df)),
                    "input_date_min": str(df["date"].min().date()), "input_date_max": str(df["date"].max().date())},
        "kpis": [{"key": "total_revenue", "label": "Total revenue", "value": float(df["revenue"].sum()),
                  "format": "currency"}],
        "series": [{"key": "monthly_revenue", "x": [str(p) for p in monthly.index], "y": [float(v) for v in monthly],
                    "x_label": "Month", "y_label": "Revenue"}],
        "tables": [{"key": "by_region", "columns": ["region", "revenue"],
                    "rows": [[r, float(v)] for r, v in by_region.items()]}],
        "insights_raw": [f"{by_region.index[0]} has the most revenue"],
    }
    json.dump(results, open(os.path.join(output_dir, "results.json"), "w"))
'''

SPOT = '''import json, os
import pandas as pd


def spot_check(input_dir):
    manifest = json.load(open(os.path.join(input_dir, "manifest.json")))
    df = pd.read_parquet(os.path.join(input_dir, manifest["files"][0]["path"]))
    return [{"name": "total", "results_ref": "kpis.total_revenue", "expected": float(df["revenue"].sum()),
             "tolerance": 0.001}]
'''


def _latest_dataset_id() -> int:
    with Session(engine) as s:
        return s.exec(select(Dataset).order_by(Dataset.id.desc())).first().id


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_backend", "local")
    monkeypatch.setattr(settings, "screenshots_enabled", False)
    fake = FakeLLMClient()
    spec = DataSpec(granularity="one order", min_rows=5, columns=[
        SpecColumn(name="date", type="date", description="Order date"),
        SpecColumn(name="region", type="category", description="Sales region"),
        SpecColumn(name="revenue", type="float", description="Order amount"),
    ])
    fake.register("analyst", RequirementAnalysis(
        task_type="descriptive", summary="Revenue by month and region", data_spec=spec,
        success_criteria=["Monthly revenue trend"], ready=True))
    fake.register("validator", lambda system, user, schema: ValidationReport(status="ready", mapping=[
        ColumnMapping(spec_column=c, dataset_id=_latest_dataset_id(), source_column=src)
        for c, src in [("date", "order_date"), ("region", "Region"), ("revenue", "Amount")]]))
    fake.register("planner", AnalysisPlan(
        path="script", title="Sales overview", rationale="Descriptive question",
        steps=[PlanStep(title="Aggregate", detail="Sum revenue by month and region")],
        expected_outputs=["total_revenue", "monthly_revenue"]))
    fake.register("coder", CODE)
    fake.register("coder_spot_check", SPOT)
    fake.register("sanity", SanityReport(status="pass"))
    set_llm(fake)
    from app.main import app
    with TestClient(app) as c:
        yield c
    set_llm(None)


def _wait(client: TestClient, run_id: int, timeout: float = 90) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        run = client.get(f"/runs/{run_id}").json()
        if run["status"] in ("COMPLETED", "FAILED"):
            return run
        time.sleep(0.3)
    raise AssertionError(f"run {run_id} did not finish: {run}")


def test_full_flow(client: TestClient):
    p = client.post("/projects", json={"requirement": "Show revenue by month and region"}).json()
    pid = p["id"]
    assert p["status"] == "REQUIREMENTS_READY" and p["analysis"]["ready"]
    assert "date,region,revenue" in client.get(f"/projects/{pid}/data-spec/template.csv").text

    up = client.post(f"/projects/{pid}/datasets", files=[("files", ("sales.csv", CSV, "text/csv"))])
    assert up.status_code == 200, up.text
    v = client.post(f"/projects/{pid}/validate").json()
    assert v["status"] == "ready", v

    plan = client.post(f"/projects/{pid}/plan").json()
    assert plan["path"] == "script"
    run = client.post(f"/projects/{pid}/plan/approve", json={}).json()
    run = _wait(client, run["id"])
    assert run["status"] == "COMPLETED", run.get("error")
    assert run["sanity_json"]["status"] == "pass", run["sanity_json"]

    dash = client.get(f"/runs/{run['id']}/dashboard").json()
    assert dash["results"]["kpis"][0]["value"] == sum(10 + i for i in range(40))
    assert dash["spec"]["widgets"], "composer produced no widgets"
    assert "Key insights" in dash["insights_md"]
    assert client.get(f"/runs/{run['id']}/logs/stream").status_code == 200

    project = client.get(f"/projects/{pid}").json()
    assert project["status"] == "COMPLETED" and project["pipeline_id"]
    pipe_id = project["pipeline_id"]
    assert client.get(f"/pipelines/{pipe_id}").json()["contract_json"]["columns"]

    # Re-run, append mode: same shape → completes on old + new rows, no LLM needed for sanity.
    r2 = client.post(f"/pipelines/{pipe_id}/runs", data={"mode": "script", "data_mode": "append"},
                     files=[("files", ("sales_july.csv", CSV2, "text/csv"))]).json()
    r2 = _wait(client, r2["id"])
    assert r2["status"] == "COMPLETED", r2.get("error")
    res2 = client.get(f"/runs/{r2['id']}/results").json()
    assert res2["summary"]["rows_processed"] == 60
    # Validation-uploaded datasets exclude re-run uploads.
    assert [d["original_name"] for d in client.get(f"/projects/{pid}/datasets").json()] == ["sales.csv"]

    # Re-run with a renamed column → contract check fails, run FAILED with an explanation…
    r3 = client.post(f"/pipelines/{pipe_id}/runs", data={"mode": "script", "data_mode": "replace"},
                     files=[("files", ("bad.csv", CSV_BAD, "text/csv"))]).json()
    r3 = _wait(client, r3["id"])
    assert r3["status"] == "FAILED" and r3["contract_check_json"]["ok"] is False
    assert any(i["kind"] == "missing_column" for i in r3["contract_check_json"]["issues"])
    # …and retrying with a mapping override fixes it.
    r4 = client.post(f"/pipelines/{pipe_id}/runs/{r3['id']}/retry",
                     json={"mapping_override": {"Region": "Area"}}).json()
    r4 = _wait(client, r4["id"])
    assert r4["status"] == "COMPLETED", r4["contract_check_json"]

    history = client.get(f"/pipelines/{pipe_id}/runs").json()
    assert len(history) == 4 and history[0]["kpis"]
    assert client.get(f"/projects/{pid}").json()["status"] == "COMPLETED"
