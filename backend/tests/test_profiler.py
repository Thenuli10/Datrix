import json

import numpy as np
import pandas as pd
import pytest

from app.schemas.requirement import DataSpec, SpecColumn
from app.services.profiler import infer_type, load_dataframe, profile_file, template_csv


@pytest.fixture
def frame() -> pd.DataFrame:
    n = 60
    return pd.DataFrame({
        "id": range(n),
        "amount": np.linspace(1.5, 90.0, n),
        "segment": ["A", "B", "C"] * (n // 3),
        "day": [f"2024-02-{i % 28 + 1:02d}" for i in range(n)],
        "ts": [f"2024-02-01 {i % 24:02d}:15:00" for i in range(n)],
        "flag": ["yes", "no"] * (n // 2),
        "qty": [1, None, 3] * (n // 3),
        "name": [f"customer {i}" for i in range(n)],
    })


EXPECTED = {"id": "integer", "amount": "float", "segment": "category", "day": "date", "ts": "datetime",
            "flag": "boolean", "qty": "integer", "name": "string"}


def _write(df: pd.DataFrame, tmp_path, kind: str):
    path = tmp_path / f"data.{kind}"
    if kind == "csv":
        df.to_csv(path, index=False, sep=";", encoding="latin-1")
    elif kind == "xlsx":
        df.to_excel(path, index=False)
    elif kind == "parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_json(path, orient="records")
    return path


@pytest.mark.parametrize("kind", ["csv", "xlsx", "parquet", "json"])
def test_profile_formats(frame, tmp_path, kind):
    path = _write(frame, tmp_path, kind)
    prof = profile_file(path, kind, 7, path.name, sample_rows=5)
    assert prof.row_count == 60 and prof.column_count == 8 and prof.dataset_id == 7
    cols = {c.name: c for c in prof.columns}
    assert {n: c.inferred_type for n, c in cols.items()} == EXPECTED
    assert cols["qty"].null_pct == pytest.approx(33.33, abs=0.01)
    assert cols["amount"].min == pytest.approx(1.5) and cols["amount"].max == pytest.approx(90.0)
    assert cols["segment"].top_values[0][1] == 20 and cols["segment"].unique_count == 3
    assert cols["day"].min == "2024-02-01"
    assert len(prof.sample_rows) == 5
    json.dumps(prof.model_dump(), allow_nan=False)  # JSON-safe: no NaN, no Timestamps


def test_sample_rows_capped_by_settings(frame, tmp_path):
    path = _write(frame, tmp_path, "parquet")
    assert len(profile_file(path, "parquet", 1, "x", sample_rows=1000).sample_rows) == 20


def test_csv_encoding_and_json_lines(tmp_path):
    p = tmp_path / "latin.csv"
    p.write_bytes("city,val\nZürich,1\nSão Paulo,2\n".encode("latin-1"))
    assert load_dataframe(p, "csv")["city"].tolist() == ["Zürich", "São Paulo"]
    jl = tmp_path / "x.jsonl"
    jl.write_text('{"a": 1, "b": "x"}\n{"a": 2, "b": "y"}\n')
    assert load_dataframe(jl, "json").shape == (2, 2)


def test_infer_type_edge_cases():
    assert infer_type(pd.Series([None, None])) == "string"
    assert infer_type(pd.Series([1.5, np.inf, 2.0])) == "float"
    assert infer_type(pd.Series([True, False])) == "boolean"
    assert infer_type(pd.Series(["12/31/2023", "01/15/2024", "02/01/2024"])) == "date"
    assert infer_type(pd.Series(["x"] * 3 + ["y"] * 3)) == "category"


def test_template_csv():
    spec = DataSpec(granularity="one order", columns=[
        SpecColumn(name="order_id", type="integer", description="id", example_values=["101", "102"]),
        SpecColumn(name="order_date", type="date", description="when"),
        SpecColumn(name="note", type="string", description="free text", example_values=["a, b"]),
    ])
    lines = template_csv(spec).strip().splitlines()
    assert lines[0] == "order_id,order_date,note"
    assert len(lines) == 4
    assert lines[1] == '101,2024-01-01,"a, b"' and lines[3].startswith("101,")
