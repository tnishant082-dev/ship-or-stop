"""Fixed-horizon helpers. These are the reference implementations the SQL marts are tested against."""
import numpy as np
from scipy import stats


def two_sided_p(z):
    return 2 * stats.norm.sf(np.abs(z))


def srm_pvalue(n_c, n_t, share_t=0.5):
    n = n_c + n_t
    exp = np.array([n * (1 - share_t), n * share_t])
    return stats.chisquare([n_c, n_t], exp).pvalue


def holm(p):
    """Holm step-down adjusted p-values"""
    p = np.asarray(p, float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    run = 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (m - k) * p[i]))
        adj[i] = run
    return adj


def benjamini_hochberg(p):
    p = np.asarray(p, float)
    m = len(p)
    order = np.argsort(p)[::-1]
    adj = np.empty(m)
    run = 1.0
    for k, i in enumerate(order):
        rank = m - k
        run = min(run, p[i] * m / rank)
        adj[i] = run
    return adj


def z_test_means(n_c, m_c, v_c, n_t, m_t, v_t):
    d = m_t - m_c
    se = np.sqrt(v_c / n_c + v_t / n_t)
    z = d / se
    return d, se, z, two_sided_p(z)


def mde_rel(baseline_mean, var_c, var_t, n_c, n_t, alpha=0.05, power=0.8):
    """smallest relative lift detectable with the sample an arm actually got"""
    se = np.sqrt(var_c / n_c + var_t / n_t)
    return (stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)) * se / baseline_mean
