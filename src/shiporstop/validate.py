"""Checks on the raw parquet before anything is loaded. Errors stop the load, warnings are logged."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

EXPECTED_COLUMNS = ["experiment_id", "variant_id", "metric_id", "time_since_start", "count_c", "count_t",
                    "mean_c", "mean_t", "variance_c", "variance_t"]
KEY = ["experiment_id", "variant_id", "metric_id", "time_since_start"]


@dataclass
class Finding:
    check: str
    severity: str     # error | warn
    failed_rows: int
    total_rows: int

    @property
    def passed(self):
        return self.failed_rows == 0


def validate_raw(df: pd.DataFrame):
    n = len(df)
    out = []

    def add(check, severity, failed):
        out.append(Finding(check, severity, int(failed), n))

    missing = set(EXPECTED_COLUMNS) - set(df.columns)
    add("all expected columns present", "error", len(missing))
    if missing:
        return out
    add("no duplicate experiment/variant/metric/checkpoint keys", "error", df.duplicated(KEY).sum())
    add("metric_id in 1..4", "error", (~df.metric_id.isin([1, 2, 3, 4])).sum())
    add("counts are non-negative", "error", ((df.count_c < 0) | (df.count_t < 0)).sum())
    add("empty checkpoints (all-zero rows, a logging gap)", "warn", ((df.count_c == 0) & (df.count_t == 0)).sum())
    add("counts are whole numbers", "error",
        ((df.count_c % 1 != 0) | (df.count_t.fillna(0) % 1 != 0)).sum())
    add("time_since_start is non-negative", "error", (df.time_since_start < 0).sum())
    add("binary metric means within [0, 1]", "error",
        (df.metric_id.eq(1) & ~(df.mean_c.between(0, 1) & df.mean_t.between(0, 1))).sum())
    add("non-negative means", "error", ((df.mean_c < 0) | (df.mean_t < 0)).sum())
    add("variances non-negative when present", "error", ((df.variance_c < 0) | (df.variance_t < 0)).sum())
    add("variance present (rows without it cannot be tested)", "warn",
        (df.variance_c.isna() | df.variance_t.isna()).sum())
    # binary metric: Bernoulli variance should be p(1-p) up to the n/(n-1) correction
    b = df[df.metric_id.eq(1) & df.variance_c.notna()]
    bern = (b.variance_c - b.mean_c * (1 - b.mean_c)).abs() > 1e-3
    add("binary metric variance matches p(1-p)", "warn", bern.sum())
    # cumulative checkpoints: sample size should not go down over time within a series
    s = df[(df.count_c > 0) & (df.count_t > 0)].sort_values(KEY)
    dec = s.groupby(KEY[:3]).count_c.diff().lt(0) | s.groupby(KEY[:3]).count_t.diff().lt(0)
    add("cumulative counts never decrease", "warn", dec.sum())
    return out


def findings_frame(findings):
    return pd.DataFrame([dict(check=f.check, severity=f.severity, failed_rows=f.failed_rows,
                              total_rows=f.total_rows, passed=f.passed) for f in findings])


def raise_on_errors(findings):
    bad = [f for f in findings if f.severity == "error" and not f.passed]
    if bad:
        raise ValueError("raw validation failed: " + "; ".join(f"{f.check} ({f.failed_rows})" for f in bad))


def coerce(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["experiment_id"] = df.experiment_id.astype(str)
    for c in ["variant_id", "metric_id"]:
        df[c] = df[c].astype(int)
    for c in ["count_c", "count_t"]:
        df[c] = df[c].round().astype("Int64")
    for c in ["time_since_start", "mean_c", "mean_t", "variance_c", "variance_t"]:
        df[c] = df[c].astype(float).replace([np.inf, -np.inf], np.nan)
    return df
