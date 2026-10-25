import numpy as np
import pytest
from scipy import stats as st
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportions_ztest

from shiporstop import stats


@pytest.fixture
def pvals():
    return np.random.default_rng(1).uniform(0, 0.2, 25)


def test_holm_matches_statsmodels(pvals):
    assert np.allclose(stats.holm(pvals), multipletests(pvals, method="holm")[1])


def test_bh_matches_statsmodels(pvals):
    assert np.allclose(stats.benjamini_hochberg(pvals), multipletests(pvals, method="fdr_bh")[1])


def test_srm_pvalue():
    assert stats.srm_pvalue(50_000, 50_000) == pytest.approx(1.0)
    assert stats.srm_pvalue(50_000, 49_000) < 0.01
    assert stats.srm_pvalue(20_000, 30_000, share_t=0.6) == pytest.approx(1.0)


def test_z_test_matches_unpooled_proportions():
    n_c, n_t, x_c, x_t = 40_000, 40_000, 8_000, 8_300
    p_c, p_t = x_c / n_c, x_t / n_t
    d, se, z, p = stats.z_test_means(n_c, p_c, p_c * (1 - p_c), n_t, p_t, p_t * (1 - p_t))
    z_sm, _ = proportions_ztest([x_t, x_c], [n_t, n_c], prop_var=False)
    assert z == pytest.approx(z_sm, rel=1e-3)
    assert p == pytest.approx(2 * st.norm.sf(abs(z)))


def test_mde_shrinks_with_sample_size():
    small = stats.mde_rel(0.2, 0.16, 0.16, 10_000, 10_000)
    big = stats.mde_rel(0.2, 0.16, 0.16, 1_000_000, 1_000_000)
    assert big == pytest.approx(small / 10, rel=1e-9)
