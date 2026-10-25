import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
SQL_DIR = ROOT / "sql"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
LOGS = ROOT / "logs"

DATASET_URL = "https://osf.io/62t7f/download"          # ASOS Digital Experiments Dataset, OSF 64jsb, CC BY 4.0
DATASET_FILE = RAW_DIR / "asos_digital_experiments_dataset.parquet"

# password is never stored here, libpq reads it from pgpass.conf / PGPASSWORD
DB = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("SOS_DB", "ship_or_stop"),
    "user": os.getenv("PGUSER", "postgres"),
}

# decision framework (the dataset anonymises metrics, roles below are the program's policy)
ALPHA = 0.05
PRIMARY_METRIC = 1
GUARDRAIL_METRICS = (2, 3, 4)
NI_MARGIN = 0.01            # a guardrail may not drop by more than 1% (relative)
SRM_P = 0.001
ALLOCATION_TOLERANCE = 0.10  # |share - 0.5| above this = probably a deliberate unequal split
TAU_REL = 0.01              # mSPRT mixing sd as a share of the control mean
METRIC_NAMES = {1: "M1 binary (primary)", 2: "M2 count", 3: "M3 count", 4: "M4 real-valued"}
