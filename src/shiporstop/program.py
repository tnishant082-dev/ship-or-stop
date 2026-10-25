"""Python side of the marts: things SQL is bad at (Monte Carlo boundaries, null simulations,
random-effects estimation). Reads mart.* written by sql/04, writes mart.* tables read by sql/05+."""
import logging
import zlib

import numpy as np
import pandas as pd

from . import db, sequential as sq
from .config import ALPHA

log = logging.getLogger(__name__)

DDL = """
drop table if exists mart.obf_boundary, mart.null_fpr, mart.peeking_curve, mart.heterogeneity, mart.eb_shrinkage;
create table mart.obf_boundary (arm_id text, metric_id int, look int, info_frac double precision,
                                boundary double precision, primary key (arm_id, metric_id, look));
create table mart.null_fpr (arm_id text primary key, looks int, fixed double precision,
                            naive_peeking double precision, obrien_fleming double precision, msprt double precision);
create table mart.peeking_curve (looks int primary key, naive_peeking double precision,
                                 obrien_fleming double precision, msprt double precision);
create table mart.heterogeneity (metric_id int primary key, arms int, pooled_lift double precision,
                                 tau double precision, i2 double precision, q double precision);
create table mart.eb_shrinkage (arm_id text, metric_id int, observed_lift double precision, rel_se double precision,
                                eb_lift double precision, eb_sd double precision, shrink_factor double precision,
                                primary key (arm_id, metric_id));
"""


def seed(*parts):
    return zlib.crc32("/".join(map(str, parts)).encode())


def obf_and_null(cs, n_sim_boundary=4000, n_sim_null=3000):
    bnd, fpr = [], []
    for (arm, m), g in cs.groupby(["arm_id", "metric_id"], sort=True):
        g = g.sort_values("look")
        t = g.info_frac.to_numpy()
        b = sq.obf_boundary(t, ALPHA, n_sim=n_sim_boundary, seed=seed(arm, m))
        bnd.append(pd.DataFrame({"arm_id": arm, "metric_id": m, "look": g.look.to_numpy(),
                                 "info_frac": t, "boundary": b}))
        if m == 1 and len(g) >= 2:
            tau2_std = g.tau2.iloc[-1] / g.v.iloc[-1]
            r = sq.null_peeking_fpr(t, tau2_std, ALPHA, n_sim=n_sim_null, seed=seed("null", arm))
            fpr.append(dict(arm_id=arm, looks=len(g), **r))
    return pd.concat(bnd, ignore_index=True), pd.DataFrame(fpr)


def peeking_curve(tau2_std=1.0):
    rows = []
    for k in [1, 2, 3, 5, 7, 10, 14, 20, 30, 45, 60, 90, 120]:
        t = np.arange(1, k + 1) / k
        r = sq.null_peeking_fpr(t, tau2_std, ALPHA, n_sim=6000, seed=seed("curve", k))
        rows.append(dict(looks=k, naive_peeking=r["naive_peeking"], obrien_fleming=r["obrien_fleming"],
                         msprt=r["msprt"]))
    return pd.DataFrame(rows)


def heterogeneity(fr):
    rows, shr = [], []
    for m, g in fr.groupby("metric_id"):
        r = sq.dersimonian_laird(g.rel_lift, g.rel_se)
        post, psd, B = sq.eb_shrink(g.rel_lift, g.rel_se, r["tau2"], r["mu"])
        rows.append(dict(metric_id=m, arms=r["k"], pooled_lift=r["mu"], tau=float(np.sqrt(r["tau2"])),
                         i2=r["I2"], q=r["Q"]))
        shr.append(pd.DataFrame({"arm_id": g.arm_id, "metric_id": m, "observed_lift": g.rel_lift,
                                 "rel_se": g.rel_se, "eb_lift": post, "eb_sd": psd, "shrink_factor": B}))
    return pd.DataFrame(rows), pd.concat(shr, ignore_index=True)


def build(conn):
    cs = db.query_df(conn, "select arm_id, metric_id, look, info_frac, tau2, v from mart.checkpoint_stats")
    fr = db.query_df(conn, """select f.arm_id, f.metric_id, f.rel_lift, f.rel_se
                              from mart.final_reads f join mart.srm s using (arm_id)
                              where s.ratio_status = 'healthy'""")
    log.info("obf boundaries + null replay on %d series", cs.groupby(["arm_id", "metric_id"]).ngroups)
    bnd, fpr = obf_and_null(cs)
    curve = peeking_curve()
    het, shr = heterogeneity(fr)
    with conn.transaction():
        conn.execute(DDL)
        db.copy_df(conn, bnd, "mart.obf_boundary")
        db.copy_df(conn, fpr, "mart.null_fpr", ["arm_id", "looks", "fixed", "naive_peeking", "obrien_fleming", "msprt"])
        db.copy_df(conn, curve, "mart.peeking_curve")
        db.copy_df(conn, het, "mart.heterogeneity")
        db.copy_df(conn, shr, "mart.eb_shrinkage")
    return dict(boundaries=len(bnd), null_arms=len(fpr), het=het)
