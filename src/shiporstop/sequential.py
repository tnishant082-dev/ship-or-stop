"""Sequential testing and program-level estimators for summary-statistic experiment data.

Everything works on per-checkpoint summaries (n, mean, variance per arm), which is what the ASOS
Digital Experiments Dataset ships. No user-level data is needed.
"""
import numpy as np
from scipy import stats


def diff_and_var(n_c, m_c, v_c, n_t, m_t, v_t):
    """difference in means and its variance (unpooled)"""
    d = np.asarray(m_t) - np.asarray(m_c)
    V = np.asarray(v_c) / np.asarray(n_c) + np.asarray(v_t) / np.asarray(n_t)
    return d, V


def rel_lift(m_c, m_t, v_c, n_c, v_t, n_t, alpha=0.05):
    """relative lift m_t/m_c - 1 with delta-method CI"""
    z = stats.norm.ppf(1 - alpha / 2)
    vm_c, vm_t = v_c / n_c, v_t / n_t
    r = m_t / m_c
    se = np.sqrt(vm_t / m_c ** 2 + m_t ** 2 * vm_c / m_c ** 4)
    return r - 1, se, r - 1 - z * se, r - 1 + z * se


def msprt_lambda(d, V, tau2):
    """normal-mixture mSPRT likelihood ratio (Johari et al. 2017), H0: delta = 0.
    reject when Lambda >= 1/alpha; always-valid p-value is min(1, 1/max_so_far(Lambda))"""
    d, V = np.asarray(d, float), np.asarray(V, float)
    return np.sqrt(V / (V + tau2)) * np.exp(tau2 * d ** 2 / (2 * V * (V + tau2)))


def always_valid_p(lam):
    return np.minimum(1.0, 1.0 / np.maximum.accumulate(np.asarray(lam, float)))


def obf_boundary(info_frac, alpha=0.05, n_sim=20000, seed=11):
    """Two-sided O'Brien-Fleming-shaped boundary c/sqrt(t_k) calibrated by Monte Carlo so that
    the overall type I error over the given (possibly irregular) looks equals alpha."""
    t = np.asarray(info_frac, float)
    t = t / t[-1]
    rng = np.random.default_rng(seed)
    inc = np.diff(np.concatenate([[0.0], t]))
    paths = np.cumsum(rng.standard_normal((n_sim, len(t))) * np.sqrt(inc), axis=1)
    z = paths / np.sqrt(t)
    stat = np.max(np.abs(z) * np.sqrt(t), axis=1)  # |z_k| >= c/sqrt(t_k)  <=>  |z_k| sqrt(t_k) >= c
    c = np.quantile(stat, 1 - alpha)
    return c / np.sqrt(t)


def null_peeking_fpr(info_frac, tau2_std, alpha=0.05, n_sim=4000, seed=3):
    """Type I error of three stopping rules on a null Brownian path observed at the real
    checkpoint schedule. info_frac = V_final / V_k style information fractions (increasing).
    tau2_std is the mSPRT mixing variance in units of the final-look variance."""
    t = np.asarray(info_frac, float)
    t = t / t[-1]
    rng = np.random.default_rng(seed)
    inc = np.diff(np.concatenate([[0.0], t]))
    S = np.cumsum(rng.standard_normal((n_sim, len(t))) * np.sqrt(inc), axis=1)  # sum-score, Var = t
    z = S / np.sqrt(t)
    zc = stats.norm.ppf(1 - alpha / 2)
    naive = (np.abs(z) >= zc).any(axis=1).mean()
    fixed = (np.abs(z[:, -1]) >= zc).mean()
    b = obf_boundary(t, alpha)
    obf = (np.abs(z) >= b).any(axis=1).mean()
    # in difference scale with final variance 1: d_k = S_k / t_k, V_k = 1 / t_k
    d, V = S / t, 1.0 / t
    lam = msprt_lambda(d, V, tau2_std)
    ms = (lam >= 1 / alpha).any(axis=1).mean()
    return dict(fixed=fixed, naive_peeking=naive, obrien_fleming=obf, msprt=ms)


def dersimonian_laird(y, se):
    """random-effects tau^2 and pooled mean"""
    y, se = np.asarray(y, float), np.asarray(se, float)
    w = 1 / se ** 2
    mu_fe = np.sum(w * y) / w.sum()
    Q = np.sum(w * (y - mu_fe) ** 2)
    k = len(y)
    tau2 = max(0.0, (Q - (k - 1)) / (w.sum() - (w ** 2).sum() / w.sum()))
    wr = 1 / (se ** 2 + tau2)
    mu = np.sum(wr * y) / wr.sum()
    I2 = max(0.0, (Q - (k - 1)) / Q) if Q > 0 else 0.0
    return dict(tau2=tau2, mu=mu, Q=Q, I2=I2, k=k)


def eb_shrink(y, se, tau2, mu):
    """normal-normal empirical Bayes posterior mean and sd"""
    y, se = np.asarray(y, float), np.asarray(se, float)
    B = se ** 2 / (se ** 2 + tau2) if tau2 > 0 else np.ones_like(se)
    post = mu + (1 - B) * (y - mu)
    post_sd = np.sqrt((1 - B) * se ** 2)
    return post, post_sd, B
