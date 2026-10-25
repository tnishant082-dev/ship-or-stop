"""Full rebuild: download -> validate -> load raw -> SQL staging/DQ/marts -> Python marts -> SQL verdicts -> BI views.

python scripts/run_pipeline.py
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from shiporstop import db, etl, program, validate  # noqa: E402
from shiporstop.config import LOGS, SQL_DIR  # noqa: E402

LOGS.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(LOGS / "pipeline.log", mode="w")])
log = logging.getLogger("pipeline")


def step(conn, name):
    t = time.time()
    db.run_sql_file(conn, SQL_DIR / name)
    conn.commit()
    log.info("%-28s %.1fs", name, time.time() - t)


def main():
    t0 = time.time()
    db.ensure_database()
    path = etl.download()
    raw = etl.read_raw(path)
    findings = validate.validate_raw(raw)
    for f in findings:
        log.info("raw check %-55s %-5s failed=%d", f.check, f.severity, f.failed_rows)
    validate.raise_on_errors(findings)
    with db.connect() as conn:
        step(conn, "00_schemas.sql")
        step(conn, "01_stats_functions.sql")
        etl.write_validation(conn, findings)
        log.info("loaded %d rows into raw.asos_checkpoints", etl.load(conn, raw, etl.sha256(path)))
        step(conn, "02_staging.sql")
        step(conn, "03_dq_checks.sql")
        bad = conn.execute("select check_name from dq.check_results where severity = 'error' and not passed").fetchall()
        if bad:
            raise SystemExit(f"DQ errors, stopping: {[b[0] for b in bad]}")
        step(conn, "04_marts_checkpoints.sql")
        t = time.time()
        out = program.build(conn)
        log.info("python marts: %d boundary rows, %d null replays (%.1fs)", out["boundaries"], out["null_arms"], time.time() - t)
        step(conn, "05_marts_verdicts.sql")
        step(conn, "06_marts_portfolio.sql")
        step(conn, "07_bi_views.sql")
        k = db.query_df(conn, "select * from mart.program_kpis").iloc[0]
        log.info("experiments=%d arms=%d ship=%d stop=%d inconclusive=%d untrusted=%d",
                 k.experiments, k.arms, k.ship, k.stop, k.inconclusive, k.untrusted)
        log.info("null FPR fixed=%.3f naive=%.3f obf=%.3f msprt=%.3f", k.fpr_fixed, k.fpr_naive, k.fpr_obf, k.fpr_msprt)
    log.info("done in %.0fs", time.time() - t0)


if __name__ == "__main__":
    main()
