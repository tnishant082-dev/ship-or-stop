import pytest


@pytest.fixture(scope="session")
def conn():
    from shiporstop import db
    try:
        c = db.connect()
        c.execute("select 1 from mart.program_kpis")
    except Exception as exc:  # no warehouse built -> skip warehouse tests
        pytest.skip(f"warehouse not available: {exc}")
    yield c
    c.close()


@pytest.fixture(scope="session")
def q(conn):
    from shiporstop import db
    return lambda sql, params=None: db.query_df(conn, sql, params)
