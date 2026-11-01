"""End-to-end ML path: train → save model → predict re-run → drift warning → retrain (new pipeline version)."""
import random

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.llm import set_llm
from app.llm.fake import FakeLLMClient
from app.schemas import (
    AnalysisPlan, ColumnMapping, DataSpec, MLSpec, PlanStep, RequirementAnalysis, SanityReport, SpecColumn,
    ValidationReport,
)
from tests.test_e2e_api import _latest_dataset_id, _wait


def _csv(n: int, seed: int, spend_shift: float = 0.0) -> str:
    rng = random.Random(seed)
    rows = ["CustTenure,MonthlySpend,Plan,Churned"]
    for _ in range(n):
        tenure = rng.randint(1, 60)
        spend = round(rng.uniform(10, 100) + spend_shift, 2)
        plan = rng.choice(["basic", "pro", "team"])
        p = 0.7 if tenure < 12 else 0.2
        rows.append(f"{tenure},{spend},{plan},{int(rng.random() < p)}")
    return "\n".join(rows)


CODE = '''import json, os
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

FEATURES = ["tenure", "spend", "plan"]


def _load(input_dir):
    m = json.load(open(os.path.join(input_dir, "manifest.json")))
    return pd.read_parquet(os.path.join(input_dir, m["files"][0]["path"]))


def _write(output_dir, results):
    json.dump(results, open(os.path.join(output_dir, "results.json"), "w"))


def train(input_dir, output_dir, params):
    df = _load(input_dir)
    X, y = df[FEATURES], df["churned"].astype(int)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=42, stratify=y)
    model = Pipeline([("prep", ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore"), ["plan"])],
                                                 remainder="passthrough")),
                      ("clf", LogisticRegression(max_iter=500))]).fit(Xtr, ytr)
    proba = model.predict_proba(Xte)[:, 1]
    metrics = {"auc": float(roc_auc_score(yte, proba)), "accuracy": float(accuracy_score(yte, proba > 0.5))}
    base = {"auc": 0.5, "accuracy": float(max(yte.mean(), 1 - yte.mean()))}
    joblib.dump({"model": model, "metrics": metrics, "baseline": base}, os.path.join(params["model_dir"], "model.joblib"))
    _write(output_dir, {
        "summary": {"title": "Churn model", "rows_processed": int(len(df))},
        "kpis": [{"key": "churn_rate", "label": "Churn rate", "value": float(y.mean()), "format": "percent"}],
        "model": {"type": "logistic_regression", "metrics": metrics, "baseline_metrics": base, "target": "churned"},
        "insights_raw": ["Short-tenure customers churn more"],
    })


def predict(input_dir, model_path, output_dir, params):
    saved = joblib.load(os.path.join(model_path, "model.joblib"))
    df = _load(input_dir)
    proba = saved["model"].predict_proba(df[FEATURES])[:, 1]
    _write(output_dir, {
        "summary": {"title": "Churn model", "rows_processed": int(len(df))},
        "kpis": [{"key": "churn_rate", "label": "Predicted churn rate", "value": float((proba > 0.5).mean()),
                  "format": "percent"}],
        "model": {"type": "logistic_regression", "metrics": saved["metrics"], "baseline_metrics": saved["baseline"],
                  "target": "churned"},
        "insights_raw": [f"{int((proba > 0.5).sum())} customers likely to churn"],
    })
'''


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_backend", "local")
    monkeypatch.setattr(settings, "screenshots_enabled", False)
    fake = FakeLLMClient()
    spec = DataSpec(granularity="one customer", min_rows=20, columns=[
        SpecColumn(name="tenure", type="integer", description="Months as customer"),
        SpecColumn(name="spend", type="float", description="Monthly spend"),
        SpecColumn(name="plan", type="category", description="Plan"),
        SpecColumn(name="churned", type="integer", description="1 if churned"),
    ])
    fake.register("analyst", RequirementAnalysis(task_type="classification", summary="Predict churn",
                                                 data_spec=spec, success_criteria=["AUC"], ready=True))
    fake.register("validator", lambda system, user, schema: ValidationReport(status="ready", mapping=[
        ColumnMapping(spec_column=c, dataset_id=_latest_dataset_id(), source_column=s) for c, s in
        [("tenure", "CustTenure"), ("spend", "MonthlySpend"), ("plan", "Plan"), ("churned", "Churned")]]))
    fake.register("planner", AnalysisPlan(
        path="ml", title="Churn model", rationale="Binary target",
        steps=[PlanStep(title="Fit", detail="Logistic regression")], expected_outputs=["churn_rate"],
        ml=MLSpec(problem="classification", target="churned", features=["tenure", "spend", "plan"],
                  model_family="logistic_regression", validation="stratified 70/30 split",
                  metrics=["auc", "accuracy"], baseline="majority class")))
    fake.register("coder", CODE)
    fake.register("sanity", SanityReport(status="pass"))
    set_llm(fake)
    from app.main import app
    with TestClient(app) as c:
        yield c
    set_llm(None)


def test_ml_flow(client: TestClient):
    pid = client.post("/projects", json={"requirement": "Predict which customers will churn"}).json()["id"]
    client.post(f"/projects/{pid}/datasets", files=[("files", ("customers.csv", _csv(400, 1), "text/csv"))])
    assert client.post(f"/projects/{pid}/validate").json()["status"] == "ready"
    assert client.post(f"/projects/{pid}/plan").json()["path"] == "ml"
    run = _wait(client, client.post(f"/projects/{pid}/plan/approve", json={}).json()["id"], timeout=180)
    assert run["status"] == "COMPLETED", run.get("error")
    assert run["mode"] == "train" and 0.5 < run["metrics_json"]["auc"] < 0.98
    pipe = client.get(f"/pipelines/{client.get(f'/projects/{pid}').json()['pipeline_id']}").json()
    assert pipe["model_path"] and pipe["version"] == 1

    # Predict with the saved model on new, shifted data → drift reported.
    r2 = client.post(f"/pipelines/{pipe['id']}/runs", data={"mode": "predict", "data_mode": "replace"},
                     files=[("files", ("customers_new.csv", _csv(200, 2, spend_shift=80), "text/csv"))]).json()
    r2 = _wait(client, r2["id"], timeout=180)
    assert r2["status"] == "COMPLETED", r2.get("error")
    assert r2["mode"] == "predict" and r2["drift_json"]["drifted"]
    assert any(c["column"] == "spend" and c["drifted"] for c in r2["drift_json"]["columns"])

    # Retrain → new active pipeline version.
    r3 = client.post(f"/pipelines/{pipe['id']}/runs", data={"mode": "retrain", "data_mode": "append"},
                     files=[("files", ("customers_more.csv", _csv(200, 3), "text/csv"))]).json()
    r3 = _wait(client, r3["id"], timeout=180)
    assert r3["status"] == "COMPLETED", r3.get("error")
    assert client.get(f"/runs/{r3['id']}/results").json()["summary"]["rows_processed"] == 400
    project = client.get(f"/projects/{pid}").json()
    new_pipe = client.get(f"/pipelines/{project['pipeline_id']}").json()
    assert new_pipe["version"] == 2 and new_pipe["id"] != pipe["id"] and new_pipe["active"]
