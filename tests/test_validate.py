import numpy as np
import pandas as pd
import pytest

from shiporstop import validate


def frame():
    rows = []
    for t in [1.0, 1.5, 2.0]:
        for m in [1, 2]:
            mc = 0.2 if m == 1 else 1.3
            rows.append(dict(experiment_id="abc123", variant_id=1, metric_id=m, time_since_start=t,
                             count_c=1000.0 * t, count_t=1000.0 * t, mean_c=mc, mean_t=mc,
                             variance_c=mc * (1 - mc) if m == 1 else 2.0, variance_t=mc * (1 - mc) if m == 1 else 2.0))
    return pd.DataFrame(rows)


def by_name(findings):
    return {f.check: f for f in findings}


def test_clean_frame_passes():
    f = validate.validate_raw(frame())
    validate.raise_on_errors(f)
    assert all(x.passed for x in f)


def test_duplicate_key_is_an_error():
    df = pd.concat([frame(), frame().iloc[[0]]])
    with pytest.raises(ValueError, match="duplicate"):
        validate.raise_on_errors(validate.validate_raw(df))


def test_binary_mean_out_of_range_is_an_error():
    df = frame()
    df.loc[0, "mean_t"] = 1.4
    assert not by_name(validate.validate_raw(df))["binary metric means within [0, 1]"].passed


def test_empty_checkpoint_is_a_warning_not_an_error():
    df = frame()
    df.loc[2, ["count_c", "count_t", "mean_c", "mean_t", "variance_c", "variance_t"]] = 0.0
    f = validate.validate_raw(df)
    validate.raise_on_errors(f)
    assert by_name(f)["empty checkpoints (all-zero rows, a logging gap)"].failed_rows == 1


def test_decreasing_counts_flagged():
    df = frame()
    df.loc[(df.metric_id == 1) & (df.time_since_start == 2.0), "count_t"] = 500.0
    assert by_name(validate.validate_raw(df))["cumulative counts never decrease"].failed_rows == 1


def test_missing_columns_short_circuit():
    f = validate.validate_raw(frame().drop(columns=["variance_t"]))
    assert len(f) == 1 and not f[0].passed


def test_coerce_types():
    df = validate.coerce(frame().assign(variance_c=np.inf))
    assert df.variance_c.isna().all() and str(df.count_c.dtype) == "Int64"
