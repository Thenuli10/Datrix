import numpy as np
import pandas as pd

from app.services.drift import check_drift, training_profile


def make(n: int, shift: float = 0.0, seed: int = 0, mix=(0.5, 0.3, 0.2)) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"x": rng.normal(10 + shift, 2, n),
                         "plan": rng.choice(["basic", "pro", "team"], n, p=list(mix))})


def test_identical_data_not_drifted():
    df = make(3000)
    report = check_drift(training_profile(df), df)
    assert not report.drifted and {c.column for c in report.columns} == {"x", "plan"}


def test_same_distribution_new_sample_not_drifted():
    assert not check_drift(training_profile(make(3000)), make(3000, seed=1)).drifted


def test_shifted_numeric_and_categorical_drift():
    report = check_drift(training_profile(make(3000)), make(3000, shift=3.0, seed=2, mix=(0.1, 0.2, 0.7)))
    cols = {c.column: c for c in report.columns}
    assert report.drifted and cols["x"].drifted and cols["plan"].drifted
    assert cols["x"].statistic > 0.2 and cols["x"].p_value < 0.01


def test_profile_is_compact_and_skips_missing_columns():
    prof = training_profile(make(5000))
    assert len(prof["numeric"]["x"]["sample"]) == 2000 and len(prof["numeric"]["x"]["props"]) == 10
    assert check_drift(prof, pd.DataFrame({"other": [1, 2]})).columns == []
