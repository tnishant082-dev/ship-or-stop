"""Export result tables to reports/*.csv and draw the README figures from the bi.* views.

python scripts/build_reports.py
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from shiporstop import db  # noqa: E402
from shiporstop.config import FIGURES, REPORTS  # noqa: E402

plt.rcParams.update({"figure.dpi": 130, "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
                     "axes.titleweight": "bold"})
BLUE, RED, GREEN, GREY = "#1F4E79", "#C0392B", "#5B8C5A", "#9AA5B1"

EXPORTS = ["program_kpis", "arms", "final_results", "srm", "null_fpr", "peeking_curve", "sequential_summary",
           "verdict_counts", "decision_sensitivity", "heterogeneity", "eb_shrinkage", "metric_tree",
           "verdict_segments", "metric_comovement", "metric_sensitivity", "early_read", "dq_checks", "dq_incidents"]


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    with db.connect() as c:
        t = {v: db.query_df(c, f"select * from bi.{v}") for v in EXPORTS}
        traj = db.query_df(c, "select * from bi.checkpoints where metric_id = 1 and arm_id in ('036afc/v2', 'a4386f/v1') order by day")
    for name, df in t.items():
        df.to_csv(REPORTS / f"{name}.csv", index=False)

    f = t["null_fpr"].sort_values("rule_order")
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    ax.bar(f.rule, f.false_positive_rate * 100, color=[GREY, RED, BLUE, GREEN])
    ax.axhline(5, ls="--", c="k", lw=.8)
    for i, v in enumerate(f.false_positive_rate):
        ax.text(i, v * 100 + .4, f"{v:.1%}", ha="center")
    ax.set_ylabel("false positive rate, %")
    ax.set_title("A/A replay on the real ASOS checkpoint schedules")
    fig.tight_layout(); fig.savefig(FIGURES / "peeking_fpr.png"); plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.2), sharey=False)
    for ax, (arm, title) in zip(axes, [("036afc/v2", "036afc/v2: a day-5 peek calls a loss that vanishes"),
                                       ("a4386f/v1", "a4386f/v1: real winner, OBF stops on day 11.5 of 89")]):
        g = traj[traj.arm_id == arm]
        ax.plot(g.day, g.z, c="k", lw=1.4, label="z")
        ax.plot(g.day, g.obf_upper, c=BLUE, label="O'Brien-Fleming"); ax.plot(g.day, g.obf_lower, c=BLUE)
        ax.axhline(1.96, c=RED, ls="--", lw=.8, label="naive 1.96"); ax.axhline(-1.96, c=RED, ls="--", lw=.8)
        lim = max(4.5, g.z.abs().max() + .5)
        ax.set_ylim(-lim, lim); ax.set_xlabel("days since start"); ax.set_title(title, fontsize=8.5)
    axes[0].legend(fontsize=7, loc="upper right")
    fig.tight_layout(); fig.savefig(FIGURES / "trajectories.png"); plt.close(fig)

    v = t["verdict_counts"].sort_values("verdict_order")
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    ax.barh(v.verdict[::-1], v.arms[::-1], color=BLUE)
    for i, n in enumerate(v.arms[::-1]):
        ax.text(n + .5, i, str(n), va="center")
    ax.set_title("Verdicts for 99 treatment arms")
    fig.tight_layout(); fig.savefig(FIGURES / "verdicts.png"); plt.close(fig)

    e = t["eb_shrinkage"]; e = e[e.metric_id == 1].sort_values("observed_lift")
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    x = range(len(e))
    ax.errorbar(x, e.observed_lift * 100, yerr=1.96 * e.rel_se * 100, fmt="o", ms=2.5, c=GREY, lw=.6, label="observed ±95% CI")
    ax.scatter(x, e.eb_lift * 100, s=10, c="#7A5C99", zorder=3, label="empirical-Bayes shrunk")
    ax.axhline(0, c="k", lw=.6); ax.set_xticks([]); ax.set_ylabel("primary lift, %"); ax.legend(fontsize=7)
    ax.set_title("Winner's curse: lifts before and after shrinkage")
    fig.tight_layout(); fig.savefig(FIGURES / "shrinkage.png"); plt.close(fig)

    s = t["decision_sensitivity"]; s = s[s.verdict == "SHIP"].pivot(index="alpha", columns="ni_margin", values="arms").fillna(0)
    fig, ax = plt.subplots(figsize=(5.2, 2.6))
    ax.imshow(s.values, cmap="Greens")
    ax.set_xticks(range(s.shape[1])); ax.set_xticklabels([f"{c:.1%}" for c in s.columns])
    ax.set_yticks(range(s.shape[0])); ax.set_yticklabels([str(a) for a in s.index])
    for i in range(s.shape[0]):
        for j in range(s.shape[1]):
            ax.text(j, i, int(s.values[i, j]), ha="center", va="center")
    ax.set_xlabel("guardrail non-inferiority margin"); ax.set_ylabel("alpha"); ax.set_title("Arms that SHIP")
    fig.tight_layout(); fig.savefig(FIGURES / "sensitivity.png"); plt.close(fig)

    k = t["program_kpis"].iloc[0].to_dict()
    (REPORTS / "program_kpis.json").write_text(json.dumps({a: (float(b) if b is not None else None) for a, b in k.items()}, indent=2))
    print(f"wrote {len(EXPORTS)} csv files and 5 figures")


if __name__ == "__main__":
    main()
