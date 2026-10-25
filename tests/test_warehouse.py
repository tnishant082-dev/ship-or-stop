"""Reconcile the SQL marts against independent pandas / scipy recomputation."""
import numpy as np
import pandas as pd
import pytest
from scipy import stats as st

from shiporstop import stats
from shiporstop.config import DATASET_FILE


def test_raw_reconciles_with_source_file(q):
    src = pd.read_parquet(DATASET_FILE)
    assert q("select count(*) n from raw.asos_checkpoints").n[0] == len(src)
    assert q("select count(distinct experiment_id) n from raw.asos_checkpoints").n[0] == src.experiment_id.nunique() == 78


def test_no_dq_errors(q):
    assert q("select count(*) n from dq.check_results where severity = 'error' and not passed").n[0] == 0


def test_rejected_plus_testable_equals_staging(q):
    r = q("""select (select count(*) from stg.checkpoints) s, (select count(*) from stg.rejected_checkpoints) r,
                    (select count(*) from mart.checkpoint_stats) t""").iloc[0]
    assert r.s == r.r + r.t


def test_checkpoint_z_matches_pandas(q):
    c = q("""select s.n_c, s.n_t, s.mean_c, s.mean_t, s.variance_c, s.variance_t, m.z, m.p_naive
             from mart.checkpoint_stats m join stg.checkpoints s using (arm_id, metric_id, day)""")
    d, se, z, p = stats.z_test_means(c.n_c, c.mean_c, c.variance_c, c.n_t, c.mean_t, c.variance_t)
    assert np.allclose(c.z, z, rtol=1e-9)
    assert np.allclose(c.p_naive, p, rtol=2e-6, atol=1e-12)


def test_holm_and_bh_match_python(q):
    f = q("select experiment_id, p_value, p_holm, p_bh from mart.final_results")
    holm = f.groupby("experiment_id").p_value.transform(lambda s: stats.holm(s.values))
    assert np.allclose(f.p_holm, holm, rtol=1e-9, atol=1e-15)
    assert np.allclose(f.p_bh, stats.benjamini_hochberg(f.p_value.values), rtol=1e-9, atol=1e-15)


def test_srm_matches_scipy(q):
    s = q("select n_c, n_t, srm_p from mart.srm")
    ref = [st.chisquare([a, b]).pvalue for a, b in zip(s.n_c, s.n_t)]
    assert np.allclose(s.srm_p, ref, rtol=1e-5, atol=1e-12)


def test_verdicts_recomputed_in_pandas(q):
    f = q("select arm_id, metric_id, rel_lift, rel_se, ratio_status from mart.final_results")
    z = 1.959964
    out = {}
    for arm, g in f.groupby("arm_id"):
        p = g[g.metric_id == 1].iloc[0]
        gr = g[g.metric_id != 1]
        breach = (gr.rel_lift + z * gr.rel_se < -0.01).any()
        unproven = ((gr.rel_lift - z * gr.rel_se < -0.01) & ~(gr.rel_lift + z * gr.rel_se < -0.01)).any()
        if p.ratio_status == "SRM":
            v = "INVALID: SRM"
        elif p.ratio_status == "allocation unknown":
            v = "HOLD: confirm allocation"
        elif p.rel_lift + z * p.rel_se < 0:
            v = "STOP: primary harm"
        elif breach:
            v = "STOP: guardrail breach"
        elif p.rel_lift - z * p.rel_se > 0:
            v = "SHIP WITH CAUTION" if unproven else "SHIP"
        else:
            v = "INCONCLUSIVE"
        out[arm] = v
    sql = q("select arm_id, verdict from mart.verdicts").set_index("arm_id").verdict
    assert sql.to_dict() == out


def test_obf_boundaries_decrease_and_end_near_fixed(q):
    b = q("select arm_id, metric_id, look, boundary from mart.obf_boundary order by 1, 2, 3")
    mono = b.groupby(["arm_id", "metric_id"]).boundary.apply(lambda s: (np.diff(s.values) <= 1e-9).all())
    assert mono.all()
    last = b.groupby(["arm_id", "metric_id"]).boundary.last()
    assert last.between(1.8, 2.7).all()


def test_sequential_first_crossing(q):
    c = q("""select c.arm_id, c.metric_id, c.day, c.z from mart.checkpoint_stats c where c.metric_id = 1""")
    first = c[c.z.abs() >= 1.959964].groupby("arm_id").day.min()
    s = q("select arm_id, naive_day from mart.sequential_stops where metric_id = 1 and naive_day is not null")
    assert s.set_index("arm_id").naive_day.sort_index().equals(first.sort_index().rename("naive_day"))


def test_null_replay_shows_peeking_inflation(q):
    k = q("select fpr_fixed, fpr_naive, fpr_obf, fpr_msprt from mart.program_kpis").iloc[0]
    assert abs(k.fpr_fixed - 0.05) < 0.01 and abs(k.fpr_obf - 0.05) < 0.01
    assert k.fpr_naive > 0.12 and k.fpr_msprt < 0.05


def test_program_kpis_add_up(q):
    k = q("select * from mart.program_kpis").iloc[0]
    assert k.ship + k.stop + k.inconclusive + k.untrusted + \
        q("select count(*) n from mart.verdicts where verdict = 'SHIP WITH CAUTION'").n[0] == k.arms == 99


def test_sensitivity_grid_is_complete(q):
    g = q("select alpha, ni_margin, sum(arms) n from mart.decision_sensitivity group by 1, 2")
    assert len(g) == 15 and (g.n == 99).all()


def test_metric_comovement_symmetric(q):
    m = q("select metric_a, metric_b, z_corr from mart.metric_comovement").pivot(index="metric_a", columns="metric_b", values="z_corr")
    assert np.allclose(m.values, m.values.T) and np.allclose(np.diag(m.values), 1)


@pytest.mark.parametrize("view", ["program_kpis", "arms", "final_results", "checkpoints", "srm", "null_fpr",
                                  "peeking_curve", "sequential_stops", "sequential_summary", "verdict_counts",
                                  "decision_sensitivity", "heterogeneity", "eb_shrinkage", "metric_tree",
                                  "verdict_segments", "metric_comovement", "metric_sensitivity", "early_read",
                                  "dq_checks", "layer_rows", "experiments", "dq_incidents", "srm_trajectory"])
def test_bi_views_not_empty(q, view):
    assert q(f"select count(*) n from bi.{view}").n[0] > 0
