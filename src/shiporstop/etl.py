"""Download -> validate -> load into raw.asos_checkpoints."""
import hashlib
import logging
import urllib.request

import pandas as pd

from . import db, validate
from .config import DATASET_FILE, DATASET_URL

log = logging.getLogger(__name__)


def download(force=False):
    if DATASET_FILE.exists() and not force:
        return DATASET_FILE
    DATASET_FILE.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading %s", DATASET_URL)
    urllib.request.urlretrieve(DATASET_URL, DATASET_FILE)
    return DATASET_FILE


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_raw(path=None):
    return pd.read_parquet(path or DATASET_FILE)


def load(conn, df, source_sha):
    df = validate.coerce(df)
    with conn.transaction():
        conn.execute("truncate raw.asos_checkpoints, raw.load_audit restart identity")
        db.copy_df(conn, df, "raw.asos_checkpoints", validate.EXPECTED_COLUMNS)
        conn.execute("insert into raw.load_audit (source_file, source_sha256, rows_loaded) values (%s, %s, %s)",
                     (DATASET_FILE.name, source_sha, len(df)))
    return len(df)


def write_validation(conn, findings):
    with conn.transaction():
        conn.execute("delete from dq.check_results where layer = 'raw-file'")
        for f in findings:
            conn.execute("insert into dq.check_results (layer, check_name, severity, failed_rows, total_rows, passed)"
                         " values ('raw-file', %s, %s, %s, %s, %s)",
                         (f.check, f.severity, f.failed_rows, f.total_rows, f.passed))
