import json

import numpy as np
import pandas as pd
import pytest

from app.schemas.data import ColumnMapping, JoinSpec, ValidationReport
from app.schemas.requirement import DataSpec, SpecColumn
from app.services.contract import append_datasets, apply_mapping, check_contract, freeze_contract
from app.services.inputs import canonical_name, prepare_inputs

SPEC = DataSpec(granularity="one order", min_rows=10, columns=[
    SpecColumn(name="order_id", type="integer", description="Order id"),
    SpecColumn(name="amount", type="float", description="Order value"),
    SpecColumn(name="region", type="category", description="Sales region"),
    SpecColumn(name="order_date", type="date", description="Order date"),
])
REPORT = ValidationReport(status="ready", mapping=[
    ColumnMapping(spec_column="order_id", dataset_id=11, source_column="OrderID"),
    ColumnMapping(spec_column="amount", dataset_id=11, source_column="Amt"),
    ColumnMapping(spec_column="region", dataset_id=11, source_column="Region"),
    ColumnMapping(spec_column="order_date", dataset_id=11, source_column="Date"),
])


def orders(n: int = 40, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "OrderID": np.arange(n),
        "Amt": rng.uniform(10, 100, n).round(2),
        "Region": ["north", "south", "east", "west"] * (n // 4),
        "Date": [f"2024-03-{i % 28 + 1:02d}" for i in range(n)],
        "Extra": "x",
    })


@pytest.fixture
def contract():
    return freeze_contract([("orders.csv", orders())], REPORT, SPEC)


def kinds(result):
    return {(i.kind, i.severity) for i in result.issues}


def test_freeze(contract):
    cols = {c.name: c for c in contract.columns}
    assert contract.files == ["orders.csv"] and contract.min_rows == 10
    assert cols["order_id"].type == "integer" and cols["order_date"].type == "date"
    assert cols["region"].categories == ["east", "north", "south", "west"]
    assert 10 <= cols["amount"].min < cols["amount"].max <= 100
    assert all(c.dataset_index == 0 for c in contract.columns)


def test_same_shape_passes(contract):
    res = check_contract(contract, [("orders_april.csv", orders(seed=1))])
    assert res.ok and res.issues == []


def test_missing_column_suggestion_and_override(contract):
    df = orders().rename(columns={"Amt": "AMT"})
    res = check_contract(contract, [("o.csv", df)])
    assert not res.ok and ("missing_column", "error") in kinds(res)
    assert res.suggested_mapping == {"Amt": "AMT"}
    # the user (or auto-map) remaps the contract source column to the new name
    assert check_contract(contract, [("o.csv", df)], {"Amt": "AMT"}).ok
    mapped = apply_mapping(contract, [("o.csv", df)], {"Amt": "AMT"})[0]
    assert list(mapped.columns) == ["order_id", "amount", "region", "order_date", "extra"]  # unmapped extra passes through


def test_type_mismatch_and_int_to_float_ok(contract):
    df = orders()
    df["Amt"] = df["Amt"].round().astype(int)  # integers where float was frozen: fine
    assert check_contract(contract, [("o.csv", df)]).ok
    df["OrderID"] = [f"id-{i}" for i in range(len(df))]  # strings where integer was frozen
    res = check_contract(contract, [("o.csv", df)])
    assert ("type_mismatch", "error") in kinds(res) and not res.ok


def test_new_categories_warning(contract):
    df = orders()
    df.loc[0, "Region"] = "central"
    res = check_contract(contract, [("o.csv", df)])
    assert res.ok and kinds(res) == {("new_categories", "warning")}


def test_null_spike_warning_and_all_null_error(contract):
    df = orders()
    df.loc[:19, "Amt"] = None  # 50% null vs 0% frozen
    res = check_contract(contract, [("o.csv", df)])
    assert res.ok and ("null_spike", "warning") in kinds(res)
    df["Amt"] = np.nan
    res = check_contract(contract, [("o.csv", df)])
    assert not res.ok and ("null_spike", "error") in kinds(res)


def test_out_of_range_warning(contract):
    df = orders()
    df["Amt"] = df["Amt"] * 10
    res = check_contract(contract, [("o.csv", df)])
    assert res.ok and ("out_of_range", "warning") in kinds(res)


def test_too_few_rows_and_file_count(contract):
    assert ("too_few_rows", "error") in kinds(check_contract(contract, [("o.csv", orders(8))]))
    res = check_contract(contract, [("a.csv", orders()), ("b.csv", orders())])
    assert ("file_count", "error") in kinds(res) and not res.ok


def test_append_datasets_dedupes():
    a = pd.DataFrame({"k": [1, 2, 3], "v": ["a", "b", "c"]})
    b = pd.DataFrame({"k": [3, 4], "v": ["c", "d"]})
    (merged,) = append_datasets([a], [b])
    assert merged["k"].tolist() == [1, 2, 3, 4]


def test_prepare_inputs_first_run_and_rerun(tmp_path):
    customers = pd.DataFrame({"CustID": [1, 2], "Tier": ["gold", "silver"]})
    df = orders().assign(CustID=[1, 2] * 20)
    report = REPORT.model_copy(update={
        "mapping": REPORT.mapping + [ColumnMapping(spec_column="tier", dataset_id=12, source_column="Tier")],
        "joins": [JoinSpec(left_dataset_id=11, right_dataset_id=12, left_key="CustID", right_key="CustID")]})
    datasets = [("Orders 2024.csv", df), ("customers.xlsx", customers)]
    out = prepare_inputs(datasets, report.mapping, report.joins, tmp_path / "in1", dataset_ids=[11, 12], spec=SPEC)
    manifest = json.loads((out / "manifest.json").read_text())
    assert [f["name"] for f in manifest["files"]] == ["orders_2024", "customers"]
    assert manifest["files"][0]["columns"] == ["order_id", "amount", "region", "order_date", "CustID", "extra"]
    assert manifest["joins"] == [{"left": "orders_2024", "right": "customers", "left_key": "CustID",
                                  "right_key": "CustID", "how": "left"}]
    assert manifest["columns"]["order_date"] == {"type": "date", "description": "Order date"}
    written = pd.read_parquet(out / "orders_2024.parquet")
    assert pd.api.types.is_datetime64_any_dtype(written["order_date"]) and len(written) == 40

    # re-run: names come from the frozen contract, frames are already canonical
    frozen = freeze_contract(datasets, report, SPEC, dataset_ids=[11, 12])
    assert (frozen.joins[0].left_dataset_id, frozen.joins[0].right_dataset_id) == (0, 1)
    new = [("orders_may.csv", df), ("cust_v2.xlsx", customers)]
    assert check_contract(frozen, new).ok
    out2 = prepare_inputs(apply_mapping(frozen, new), None, frozen.joins, tmp_path / "in2", contract=frozen)
    m2 = json.loads((out2 / "manifest.json").read_text())
    assert [f["name"] for f in m2["files"]] == ["orders_2024", "customers"]
    assert m2["joins"] == manifest["joins"] and m2["files"][1]["columns"] == ["tier", "CustID"]


def test_canonical_name():
    assert canonical_name("Sales Q1 (final).CSV") == "sales_q1_final"
    assert canonical_name("2024.csv") == "d_2024"


def test_append_keeps_genuine_repeats_and_drops_only_overlap():
    """A live run lost 5 legitimate identical order lines when append deduplicated old + new together."""
    import pandas as pd

    from app.services.contract import append_datasets
    old = pd.DataFrame({"order_id": ["A", "A", "B"], "revenue": [10.0, 10.0, 5.0]})  # A is repeated on purpose
    new = pd.DataFrame({"order_id": ["B", "C", "C"], "revenue": [5.0, 7.0, 7.0]})   # B overlaps; C repeated
    (merged,) = append_datasets([old], [new])
    assert merged["order_id"].tolist() == ["A", "A", "B", "C", "C"]
    # Re-uploading exactly the old data adds nothing.
    (same,) = append_datasets([old], [old.copy()])
    assert len(same) == 3
