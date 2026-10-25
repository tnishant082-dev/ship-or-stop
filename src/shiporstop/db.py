from contextlib import contextmanager
from pathlib import Path

import psycopg

from .config import DB


def connect(dbname=None, autocommit=False):
    params = dict(DB)
    if dbname:
        params["dbname"] = dbname
    return psycopg.connect(**params, autocommit=autocommit)


def ensure_database():
    with connect("postgres", autocommit=True) as c:
        if not c.execute("select 1 from pg_database where datname = %s", (DB["dbname"],)).fetchone():
            c.execute(f'create database "{DB["dbname"]}"')


def run_sql_file(conn, path: Path):
    conn.execute(Path(path).read_text(encoding="utf-8"))


def query_df(conn, sql, params=None):
    import pandas as pd
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)


def copy_df(conn, df, table, columns=None):
    import pandas as pd
    cols = list(columns or df.columns)
    data = df[cols].astype(object)
    data = data.where(pd.notna(data), None)
    with conn.cursor() as cur:
        with cur.copy(f"copy {table} ({', '.join(cols)}) from stdin") as cp:
            for row in data.itertuples(index=False, name=None):
                cp.write_row(row)


@contextmanager
def transaction(conn):
    with conn.transaction():
        yield conn
