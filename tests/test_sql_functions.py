import numpy as np
import pytest
from scipy import stats as st

from shiporstop import sequential as sq


@pytest.mark.parametrize("z", [-6.0, -2.5, -1.0, 0.0, 0.5, 1.959964, 3.0, 5.0, 8.0, 12.0])
def test_norm_sf_matches_scipy(conn, z):
    got = conn.execute("select stats.norm_sf(%s)", (z,)).fetchone()[0]
    assert got == pytest.approx(st.norm.sf(z), rel=2e-6, abs=1e-12)


def test_tail_p_values_keep_relative_accuracy(conn):
    got = conn.execute("select stats.two_sided_p(9.5)").fetchone()[0]
    assert got == pytest.approx(2 * st.norm.sf(9.5), rel=1e-5)
    assert conn.execute("select stats.two_sided_p(40)").fetchone()[0] == 0.0


def test_chisq1_sf(conn):
    for x in [0.1, 3.841459, 10.83, 50.0]:
        assert conn.execute("select stats.chisq1_sf(%s)", (x,)).fetchone()[0] == pytest.approx(st.chi2.sf(x, 1), rel=2e-6)


def test_msprt_lambda_matches_python(conn):
    for d, v, t2 in [(0.0, 1.0, 1.0), (0.01, 1e-5, 4e-6), (3.0, 1.0, 0.5)]:
        got = conn.execute("select stats.msprt_lambda(%s, %s, %s)", (d, v, t2)).fetchone()[0]
        assert got == pytest.approx(float(sq.msprt_lambda(d, v, t2)), rel=1e-9)
