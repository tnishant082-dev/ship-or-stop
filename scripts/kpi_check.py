"""Cross-check every KPI card in the Power BI report against SQL.

The DAX side is evaluated by the Analysis Services engine inside the running Power BI Desktop
(scripts/dax_query.ps1), i.e. exactly the numbers the cards display after a refresh from Postgres.
The SQL side is computed independently from mart.* / dq.* tables, not from the bi views.
Writes reports/kpi_crosscheck.csv and exits 1 on any mismatch.

python scripts/kpi_check.py        (Power BI Desktop must have dashboard/ShipOrStop.pbip open)
"""
import csv
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from shiporstop import db  # noqa: E402
from shiporstop.config import REPORTS, ROOT  # noqa: E402

V = "select count(*) from mart.verdicts"
CHECKS = [
    # page, measure, independent SQL
    ("01", "Experiments", "select count(distinct experiment_id) from stg.checkpoints"),
    ("01", "Treatment Arms", "select count(distinct arm_id) from stg.checkpoints"),
    ("01", "Ship Rate", f"select count(*) filter (where verdict = 'SHIP')::float / ({V}) from mart.verdicts"),
    ("01", "Harm Rate", f"select count(*) filter (where verdict like 'STOP%%')::float / ({V}) from mart.verdicts"),
    ("01", "SRM Rate", "select avg((srm_p < 0.001 and abs(treatment_share - 0.5) <= 0.1)::int) from mart.srm"),
    ("01", "FPR Naive Peeking", "select avg(naive_peeking) from mart.null_fpr"),
    ("02", "Healthy Ratio Share", "select avg((ratio_status = 'healthy')::int) from mart.srm"),
    ("02", "DQ Errors", "select count(*) from dq.check_results where severity = 'error' and not passed"),
    ("02", "Median Horizon Days", "select percentile_cont(0.5) within group (order by horizon_days) from mart.final_results where metric_id = 1"),
    ("02", "OBF Median Days Saved", "select percentile_cont(0.5) within group (order by obf_days_saved) from mart.sequential_stops where metric_id = 1"),
    ("02", "Naive Wrong Calls", "select count(*) from mart.sequential_stops where metric_id = 1 and naive_wrong_call"),
    ("03", "Raw Rows", "select count(*) from raw.asos_checkpoints"),
    ("03", "Testable Checkpoints", "select count(*) from stg.checkpoints where is_testable"),
    ("03", "Rejected Rows", "select count(*) from stg.checkpoints where not is_testable"),
    ("03", "DQ Checks", "select count(*) from dq.check_results"),
    ("03", "DQ Warnings", "select count(*) from dq.check_results where severity = 'warn' and not passed"),
    ("04", "Arm Count", "select count(*) from mart.verdicts"),
    ("04", "Median MDE", "select percentile_cont(0.5) within group (order by mde_rel_80) from mart.final_results where metric_id = 1"),
    ("05", "SRM Arms", "select count(*) from mart.srm where ratio_status = 'SRM'"),
    ("05", "Allocation Unknown Arms", "select count(*) from mart.srm where ratio_status = 'allocation unknown'"),
    ("05", "Worst Share Gap", "select max(abs(treatment_share - 0.5)) from mart.srm where ratio_status = 'SRM'"),
    ("06", "FPR Fixed", "select avg(fixed) from mart.null_fpr"),
    ("06", "FPR OBF", "select avg(obrien_fleming) from mart.null_fpr"),
    ("06", "FPR mSPRT", "select avg(msprt) from mart.null_fpr"),
    ("08", "mSPRT Median Days Saved", "select percentile_cont(0.5) within group (order by msprt_days_saved) from mart.sequential_stops where metric_id = 1"),
    ("08", "Arm-days Freed by OBF", "select sum(obf_days_saved) from mart.sequential_stops where metric_id = 1"),
    ("08", "Arm-days Run", "select sum(horizon_days) from mart.sequential_stops where metric_id = 1"),
    ("08", "OBF Agreement", "select avg(obf_agrees::int) filter (where fixed_sig) from mart.sequential_stops where metric_id = 1"),
    ("08", "mSPRT Agreement", "select avg(msprt_agrees::int) filter (where fixed_sig) from mart.sequential_stops where metric_id = 1"),
    ("09", "Ship Arms", "select count(*) from mart.verdicts where verdict = 'SHIP'"),
    ("09", "Stop Arms", "select count(*) from mart.verdicts where verdict like 'STOP%%'"),
    ("09", "Inconclusive Arms", "select count(*) from mart.verdicts where verdict = 'INCONCLUSIVE'"),
    ("09", "Untrusted Arms", "select count(*) from mart.verdicts where verdict like 'INVALID%%' or verdict like 'HOLD%%'"),
    ("09", "Arms with Guardrail Breach", "select count(*) from mart.verdicts where guardrails_breached > 0"),
    ("10", "Avg Observed Win Lift", "select avg(primary_lift) from mart.verdicts where verdict = 'SHIP'"),
    ("10", "Avg Shrunk Win Lift", "select avg(eb_lift) from mart.verdicts where verdict = 'SHIP'"),
    ("11", "Tau Primary", "select tau from mart.heterogeneity where metric_id = 1"),
    ("11", "Shrink Factor", "select avg(shrink_factor) from mart.eb_shrinkage where metric_id = 1"),
    ("13", "Min Metric Corr", "select min(z_corr) from mart.metric_comovement where metric_a <> metric_b"),
    ("13", "Day 7 Z Corr", "select z_corr from mart.early_read where read_day = 7 and early_metric = 1 and final_metric = 1"),
    ("13", "Day 7 Sign Agreement", "select sign_agreement_when_final_sig from mart.early_read where read_day = 7 and early_metric = 1 and final_metric = 1"),
]


def dax_values(measures):
    cols = ",\n    ".join(f'"{m}", [{m}]' for m in measures)
    with tempfile.NamedTemporaryFile("w", suffix=".dax", delete=False, encoding="utf-8") as f:
        f.write(f"EVALUATE ROW (\n    {cols}\n)")
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          str(ROOT / "scripts" / "dax_query.ps1"), f.name], capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f"DAX query failed (is Power BI Desktop open?):\n{out.stderr}")
    row = json.loads(out.stdout)[0]
    return {k.strip("[]"): v for k, v in row.items()}


def main():
    dax = dax_values([m for _, m, _ in CHECKS])
    rows, bad = [], 0
    with db.connect() as conn:
        for page, m, sql in CHECKS:
            s = conn.execute(sql).fetchone()[0]
            s = float(s) if s is not None else float("nan")
            d = float(dax[m]) if dax.get(m) is not None else float("nan")
            ok = math.isclose(s, d, rel_tol=1e-9, abs_tol=1e-12)
            bad += not ok
            rows.append({"page": page, "measure": m, "sql_value": repr(s), "powerbi_value": repr(d), "match": ok})
            print(f"{'ok ' if ok else 'BAD'} p{page} {m:28s} sql={s:<22.10g} powerbi={d:.10g}")
    with open(REPORTS / "kpi_crosscheck.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows) - bad}/{len(rows)} Power BI measures match SQL")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
