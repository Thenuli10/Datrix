"""Several source columns mapped to one spec column (seen live: Melbourne pedestrian data has `sensing_date` +
`hourday`, both mapped to `timestamp`). Before the fix the last source silently overwrote the first, so
`timestamp` held hour numbers (0-23) parsed as 1970 dates."""
import json

import pandas as pd

from app.schemas import ColumnMapping, DataSpec, SpecColumn, ValidationReport
from app.services.contract import apply_mapping, check_contract, combine_sources, freeze_contract
from app.services.inputs import prepare_inputs

RAW = pd.DataFrame({
    "sensing_date": ["2026-08-30", "2026-08-30", "2026-08-31"],
    "hourday": [0, 13, 23],
    "sensor_name": ["A", "B", None],
    "pedestriancount": [5, 120, 40],
    "direction_1": [2, 60, 20],
})
MAPPING = [
    ColumnMapping(spec_column="timestamp", dataset_id=1, source_column="sensing_date"),
    ColumnMapping(spec_column="timestamp", dataset_id=1, source_column="hourday"),
    ColumnMapping(spec_column="sensor_id", dataset_id=1, source_column="sensor_name"),
    ColumnMapping(spec_column="pedestrian_count", dataset_id=1, source_column="pedestriancount"),
]
SPEC = DataSpec(granularity="sensor-hour", min_rows=1, columns=[
    SpecColumn(name="timestamp", type="datetime", description="hour"),
    SpecColumn(name="sensor_id", type="string", description="sensor"),
    SpecColumn(name="pedestrian_count", type="integer", description="count"),
])
EXPECTED = ["2026-08-30 00:00:00", "2026-08-30 13:00:00", "2026-08-31 23:00:00"]


def test_combine_date_and_hour():
    out = combine_sources([RAW["sensing_date"], RAW["hourday"]])
    assert out.astype(str).tolist() == EXPECTED
    # order of the sources does not matter
    assert combine_sources([RAW["hourday"], RAW["sensing_date"]]).astype(str).tolist() == EXPECTED


def test_prepare_inputs_combines_and_passes_extras_through(tmp_path):
    prepare_inputs([("ped.csv", RAW)], MAPPING, [], tmp_path, dataset_ids=[1], spec=SPEC)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    df = pd.read_parquet(tmp_path / manifest["files"][0]["path"])
    assert df["timestamp"].astype(str).tolist() == EXPECTED
    assert df["pedestrian_count"].tolist() == [5, 120, 40]
    assert "direction_1" in df.columns  # unmapped extra kept for the analysis
    assert "hourday" not in df.columns and "sensing_date" not in df.columns  # consumed by timestamp


def test_contract_rerun_uses_same_combination_and_extras_are_optional():
    report = ValidationReport(status="ready", mapping=MAPPING)
    contract = freeze_contract([("ped.csv", RAW)], report, SPEC, dataset_ids=[1])
    assert any(c.name == "direction_1" and not c.required for c in contract.columns)
    (canon,) = apply_mapping(contract, [("ped.csv", RAW)])
    assert canon["timestamp"].astype(str).tolist() == EXPECTED and "direction_1" in canon.columns

    without_extra = RAW.drop(columns=["direction_1"])
    check = check_contract(contract, [("ped.csv", without_extra)])
    assert check.ok and any(i.kind == "missing_column" and i.severity == "warning" for i in check.issues)
    without_hour = RAW.drop(columns=["hourday"])
    assert not check_contract(contract, [("ped.csv", without_hour)]).ok


def test_rerun_inputs_keep_combined_timestamp_as_datetime(tmp_path):
    """Live re-run failure: prepare_inputs coerced the combined `timestamp` to the LAST source's contract type
    (integer), so the saved code saw epoch integers instead of datetimes."""
    report = ValidationReport(status="ready", mapping=MAPPING)
    contract = freeze_contract([("ped.csv", RAW)], report, SPEC, dataset_ids=[1])
    canon = apply_mapping(contract, [("ped.csv", RAW)])
    prepare_inputs(list(zip(contract.files, canon)), None, [], tmp_path, contract=contract)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    df = pd.read_parquet(tmp_path / manifest["files"][0]["path"])
    assert str(df["timestamp"].dtype).startswith("datetime64"), df["timestamp"].dtype
    assert df["timestamp"].astype(str).tolist() == EXPECTED
