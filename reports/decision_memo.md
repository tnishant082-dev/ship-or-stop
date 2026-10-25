# Decision memo: how we should run experiments next quarter

**To:** Head of Experimentation, Product Analytics leads
**From:** Nishant Tyagi, Product Analytics
**Evidence:** 78 real A/B(/n) tests from ASOS.com (ASOS Digital Experiments Dataset, Liu et al. 2021, CC BY 4.0).
99 treatment arms, 4 decision metrics, 23,366 testable checkpoints. All numbers below come from `mart.*` in
Postgres and match the Power BI cards (41/41 measures, `reports/kpi_crosscheck.csv`).

## The ask

1. **Retire "stop when p < 0.05 on the daily dashboard".** Adopt a pre-registered O'Brien-Fleming (OBF) plan as
   the default stopping rule.
2. **Gate every readout on a sample-ratio check** (chi-square p < 0.001 blocks the readout).
3. **Put shrunk lifts in roadmaps and impact roll-ups**, not raw ones.
4. **Shrink the guardrail set** from three metrics to one, once the few arms where they disagree have been reviewed.

## Why

### 1. Peeking makes our error rate about 4x what we claim

| stopping rule | false positive rate on null replays of the real checkpoint schedules |
|---|---|
| fixed horizon (one look at the end) | 5.0% |
| **naive peeking (stop at first \|z\| >= 1.96)** | **18.8%** |
| O'Brien-Fleming | 5.1% |
| mSPRT (always-valid) | 1.0% |

Each arm's own checkpoint schedule was replayed 3,000 times with no true effect. With 10 equally spaced looks,
naive peeking already reaches 19%. At 120 looks it reaches 39%.

On the real primary-metric paths, 46 of 99 arms cross 1.96 at some checkpoint. **For 20 of them the full-horizon
answer disagrees**: either it isn't significant, or it points the other way. Arm 036afc/v2 shows the pattern. It
crosses -1.96 on day 5, which a daily dashboard would read as a loss to kill, and it ends at z = +0.8.

### 2. OBF is just as safe and much faster

* OBF stops 30 arms and agrees with the full horizon on **24 of the 26** arms that are significant at the end.
* Median **25 days saved** per agreeing arm (median test length is 44 days), or about **750 arm-days** of traffic
  freed across the portfolio. That is roughly 16% of all arm-days run.
* mSPRT is valid at any look, but because it is conservative here it only recovers 18 of 26. Use it for
  continuous guardrail monitoring and kill switches, not for the ship decision.

### 3. 12% of readouts should not have been trusted

* **9 arms fail SRM** at p < 0.001 with treatment shares like 49.2% on millions of users. A gap that size is a
  bug in assignment, logging or bot filtering, not noise. Arm 329386/v1 is below 50% from the first day, which
  points to assignment rather than a mid-test change.
* **3 arms** sit far from 50/50 (3%, 67%, 89%). That was probably intended, but the planned split isn't recorded,
  so they can't be checked. They are on **hold**.
* The data has its own incidents. One experiment logged an all-zero checkpoint, two arms *lost* treatment users
  between checkpoints, and 49 checkpoints show a one-off z spike that reverts at the next look. All of them
  are in `dq.incidents` for follow-up with the platform team.

### 4. The portfolio is mostly flat, and wins are smaller than they look

| verdict | arms |
|---|---|
| SHIP | 14 |
| STOP: primary harm | 10 |
| INCONCLUSIVE | 63 |
| INVALID: SRM | 9 |
| HOLD: confirm allocation | 3 |

* **1 in 7 arms wins and 1 in 10 hurts.** Inconclusive is the normal result, so it shouldn't be treated as a
  failure.
* **Short tests never shipped.** No arm that ran 3 weeks or less got a SHIP, and 15% of them hurt the primary
  metric. Tests over 6 weeks win 15% of the time and lose 4%.
* **Between-experiment heterogeneity:** true primary effects vary with a standard deviation of only **0.71%**
  around a mean of +0.11% (I² = 0.96). Empirical-Bayes shrinkage barely moves precise wins (ee6ff7: +2.97% to
  +2.63%) but collapses noisy ones (591c2c: +1.87% to +0.41%). Shipped arms average +1.00% observed and +0.95%
  shrunk.

### 5. The guardrails mostly repeat the primary metric

Final z-scores of the four metrics correlate **0.89 to 0.97** across arms, and each metric is significant in
26–29% of arms. A day-7 read of the primary metric correlates 0.89 with the final read and has the right sign
in 86% of arms that end significant. It is a good early warning, but still no basis for a decision.

## How robust is this?

Re-deciding all 99 arms under 3 alphas x 5 guardrail margins:

| alpha \ margin | 0% | 0.5% | 1% | 2% | 3% |
|---|---|---|---|---|---|
| 0.01 | 6 | 9 | 10 | 10 | 10 |
| **0.05** | 7 | 13 | **14** | 14 | 14 |
| 0.10 | 9 | 15 | 17 | 17 | 17 |

(arms that SHIP)

The number of ships moves with policy, but the peeking, SRM and shrinkage findings don't depend on it. At a margin
above 1% the guardrails stop binding. The margin is a business call, so it needs a named owner.

## Owners and next steps

| # | action | owner | done when |
|---|---|---|---|
| 1 | OBF plan template (horizon, looks, alpha spending) in the experiment brief | Experimentation platform | template live, first 5 tests use it |
| 2 | Automatic SRM gate on every readout | Data engineering | readout blocked when p < 0.001 |
| 3 | Planned allocation stored in experiment config | Product analytics | 0 arms on HOLD |
| 4 | Shrunk lifts in the quarterly impact roll-up | Analytics lead | Q-review deck uses `eb_lift` |
| 5 | Review the arms where guardrails disagree, then reduce to one guardrail | Metrics council | decision recorded |

## Caveats

* The metrics are anonymised. Treating M1 as the primary metric and M2–M4 as guardrails is this program's assumed
  policy, not ASOS's actual practice, and the dataset authors say the results don't represent ASOS's business.
* Only group-level summary statistics exist, so heterogeneity is measured across experiments and experiment
  types, not user segments.
* OBF boundaries are fitted to each arm's real information fractions after the fact. In production, the horizon
  and look schedule would be fixed up front.
