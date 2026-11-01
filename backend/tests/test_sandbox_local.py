"""Local (subprocess) sandbox backend: same runner.py, no isolation."""
import pandas as pd
import pytest

from app.sandbox.manager import run_in_sandbox, run_spot_check

GOOD = '''
import json, os
import pandas as pd

def run(input_dir, output_dir, params):
    df = pd.read_parquet(os.path.join(input_dir, "sales.parquet"))
    print("rows", len(df))
    results = {
        "summary": {"title": "Sales", "rows_processed": int(len(df))},
        "kpis": [{"key": "total", "label": "Total", "value": float(df["amount"].sum()), "format": "currency"}],
        "series": [{"key": "by_row", "x": list(range(len(df))), "y": df["amount"].tolist()}],
        "tables": [{"key": "head", "columns": ["amount"], "rows": [[v] for v in df["amount"].tolist()]}],
        "insights_raw": ["ok"],
    }
    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump(results, f)
'''

NAN = '''
import json, os

def run(input_dir, output_dir, params):
    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump({"summary": {"title": "t", "rows_processed": 1},
                   "kpis": [{"key": "k", "label": "K", "value": float("nan")}]}, f)
'''

RAISES = '''
def helper():
    raise ValueError("boom in helper")

def run(input_dir, output_dir, params):
    helper()
'''

SLOW = '''
import time

def run(input_dir, output_dir, params):
    print("starting", flush=True)
    time.sleep(30)
'''

ML = '''
import json, os, pickle

def train(input_dir, output_dir, params):
    with open(os.path.join(params["model_dir"], "model.pkl"), "wb") as f:
        pickle.dump({"mean": 2.0}, f)
    _write(output_dir, "train")

def predict(input_dir, model_path, output_dir, params):
    with open(os.path.join(model_path, "model.pkl"), "rb") as f:
        assert pickle.load(f)["mean"] == 2.0
    _write(output_dir, "predict")

def _write(output_dir, title):
    with open(os.path.join(output_dir, "results.json"), "w") as f:
        json.dump({"summary": {"title": title, "rows_processed": 3},
                   "model": {"type": "mean", "metrics": {"mae": 0.5}}}, f)
'''

SPOT = '''
import os
import pandas as pd

def spot_check(input_dir):
    df = pd.read_parquet(os.path.join(input_dir, "sales.parquet"))
    return [{"name": "total", "results_ref": "kpis.total", "expected": df["amount"].sum()}]
'''


@pytest.fixture
def input_dir(tmp_path):
    d = tmp_path / "input"
    d.mkdir()
    pd.DataFrame({"amount": [1.5, 2.5, 3.0]}).to_parquet(d / "sales.parquet")
    return d


def run(code, input_dir, out, **kw):
    lines: list[str] = []
    res = run_in_sandbox(code, kw.pop("entry", "run"), input_dir, out, {"p": 1}, on_log=lines.append,
                         backend="local", **kw)
    return res, lines


def test_good_script(input_dir, tmp_path):
    res, lines = run(GOOD, input_dir, tmp_path / "out")
    assert res.ok, res.error
    assert res.exit_code == 0 and res.results["kpis"][0]["value"] == 7.0
    assert "rows 3" in lines and res.duration_s > 0


def test_nan_fails_validation(input_dir, tmp_path):
    res, _ = run(NAN, input_dir, tmp_path / "out")
    assert not res.ok and res.exit_code == 1 and "NaN" in res.error and res.results is None


def test_exception_surfaces_traceback(input_dir, tmp_path):
    res, lines = run(RAISES, input_dir, tmp_path / "out")
    assert not res.ok and "ValueError: boom in helper" in res.error
    assert "Traceback" in res.stderr and "helper" in res.stderr
    assert any(line.startswith("::error::") for line in lines)


def test_timeout_kills(input_dir, tmp_path):
    res, _ = run(SLOW, input_dir, tmp_path / "out", timeout_s=3)
    assert not res.ok and res.error == "timeout" and res.duration_s < 20


def test_static_check_blocks_before_running(input_dir, tmp_path):
    res, _ = run("import subprocess\ndef run(i, o, p):\n    pass\n", input_dir, tmp_path / "out")
    assert not res.ok and res.exit_code is None and "static check" in res.error


def test_train_then_predict(input_dir, tmp_path):
    model = tmp_path / "model"
    res, _ = run(ML, input_dir, tmp_path / "out1", entry="train", model_dir=model)
    assert res.ok, res.error
    assert (model / "model.pkl").exists()
    res, _ = run(ML, input_dir, tmp_path / "out2", entry="predict", model_dir=model)
    assert res.ok and res.results["summary"]["title"] == "predict"


def test_spot_check(input_dir, tmp_path):
    out = run_spot_check(SPOT, input_dir, tmp_path / "spot", backend="local")
    assert out["ok"], out["error"]
    assert out["checks"] == [{"name": "total", "results_ref": "kpis.total", "expected": 7.0}]


def test_secrets_not_passed(input_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    code = GOOD.replace('print("rows", len(df))', 'print("key", os.environ.get("OPENAI_API_KEY"))')
    res, lines = run(code, input_dir, tmp_path / "out")
    assert res.ok and "key None" in lines


def _runner():
    import importlib.util

    from app.sandbox.manager import RUNNER_PATH

    spec = importlib.util.spec_from_file_location("sandbox_runner", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("bad", [
    [],
    {"kpis": []},
    {"summary": {"title": "t", "rows_processed": "3"}},
    {"summary": {"title": "t", "rows_processed": 3}, "kpis": {}},
    {"summary": {"title": "t", "rows_processed": 3}, "kpis": [{"label": "no key", "value": 1}]},
    {"summary": {"title": "t", "rows_processed": 3}, "series": [{"key": "s", "x": [1, 2], "y": [1]}]},
    {"summary": {"title": "t", "rows_processed": 3}, "tables": [{"key": "t", "columns": ["a"], "rows": [[1, 2]]}]},
    {"summary": {"title": "t", "rows_processed": 3}, "kpis": [{"key": "a", "label": "A", "value": 1},
                                                             {"key": "a", "label": "B", "value": 2}]},
])
def test_runner_rejects_bad_shapes(bad):
    runner = _runner()
    with pytest.raises(runner.ValidationError):
        runner.validate_results(bad)


def test_runner_strict_json(tmp_path):
    runner = _runner()
    p = tmp_path / "r.json"
    p.write_text('{"summary": {"title": "t", "rows_processed": 1}, "kpis": [{"key": "k", "label": "K", "value": Infinity}]}')
    with pytest.raises(runner.ValidationError):
        runner.load_strict_json(p)
