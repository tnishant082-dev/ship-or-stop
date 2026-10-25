import numpy as np

from shiporstop import sequential as sq


def test_obf_boundary_controls_alpha_and_is_decreasing():
    t = np.linspace(0.05, 1, 30)
    b = sq.obf_boundary(t, 0.05)
    assert np.all(np.diff(b) < 0)
    assert 1.96 < b[-1] < 2.3


def test_null_peeking_rates():
    r = sq.null_peeking_fpr(np.linspace(0.02, 1, 60), tau2_std=1.0, n_sim=4000)
    assert abs(r["fixed"] - 0.05) < 0.015
    assert r["naive_peeking"] > 0.12          # peeking inflates type I error
    assert abs(r["obrien_fleming"] - 0.05) < 0.015
    assert r["msprt"] <= 0.06                  # always valid


def test_msprt_grows_with_signal():
    lam0 = sq.msprt_lambda(0.0, 1.0, 1.0)
    lam5 = sq.msprt_lambda(5.0, 1.0, 1.0)
    assert lam0 < 1 < lam5
    p = sq.always_valid_p([0.5, 30, 2])
    assert p[-1] == p[1] == 1 / 30            # always-valid p never goes back up


def test_dersimonian_laird_and_shrinkage():
    rng = np.random.default_rng(0)
    true = rng.normal(0, 0.5, 400)
    se = np.full(400, 0.5)
    y = true + rng.normal(0, se)
    r = sq.dersimonian_laird(y, se)
    assert abs(np.sqrt(r["tau2"]) - 0.5) < 0.1
    post, _, B = sq.eb_shrink(y, se, r["tau2"], r["mu"])
    assert np.all(np.abs(post - r["mu"]) <= np.abs(y - r["mu"]) + 1e-12)
    assert np.mean((post - true) ** 2) < np.mean((y - true) ** 2)


def test_rel_lift_ci_covers_point():
    l, se, lo, hi = sq.rel_lift(0.2, 0.21, 0.16, 1e5, 0.166, 1e5)
    assert lo < l < hi and abs(l - 0.05) < 1e-12
