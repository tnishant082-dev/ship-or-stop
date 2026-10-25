-- 07 bi.* views: the only objects Power BI reads. Stable names, readable labels, no business logic.

create view bi.program_kpis as select * from mart.program_kpis;

create view bi.experiments as
select e.experiment_id, e.arms, e.horizon_days, e.max_arm_n, e.primary_looks,
       count(*) filter (where v.verdict = 'SHIP')            as ship_arms,
       count(*) filter (where v.verdict like 'STOP%')        as stop_arms,
       string_agg(distinct v.verdict, ', ')                  as verdicts
from stg.experiments e join mart.verdicts v using (experiment_id)
group by 1, 2, 3, 4, 5;

create view bi.arms as
select v.arm_id, v.experiment_id, v.verdict, v.outcome,
       case v.outcome when 'win' then 1 when 'loss' then 2 when 'flat' then 3 else 4 end as outcome_order,
       v.primary_lift, v.primary_low, v.primary_high, v.eb_lift, v.mde_rel_80, v.p_holm,
       v.guardrails_breached, v.guardrails_unproven, v.worst_guardrail_low,
       v.horizon_days, v.final_n, s.treatment_share, s.srm_p, s.ratio_status
from mart.verdicts v join mart.srm s using (arm_id);

create view bi.final_results as
select arm_id, experiment_id, metric_id, metric_name, horizon_days, looks, n_c, n_t, mean_c, mean_t,
       z, rel_lift, rel_ci_low, rel_ci_high, p_value, p_holm, p_bh, always_valid_p_final,
       sig_raw, sig_holm, sig_bh, mde_rel_80, ratio_status, eb_lift, shrink_factor
from mart.final_results;

create view bi.checkpoints as
select c.arm_id, c.metric_id, c.metric_name, c.look, c.day, c.n_c + c.n_t as n, c.z, c.rel_lift,
       c.rel_lift - 1.959964 * c.rel_se as rel_ci_low, c.rel_lift + 1.959964 * c.rel_se as rel_ci_high,
       c.info_frac, c.always_valid_p, c.p_naive, b.boundary as obf_upper, -b.boundary as obf_lower,
       1.959964 as naive_upper, -1.959964 as naive_lower
from mart.checkpoint_stats c join mart.obf_boundary b using (arm_id, metric_id, look);

create view bi.srm as select * from mart.srm;
create view bi.srm_trajectory as select * from mart.srm_trajectory;

create view bi.null_fpr as
select 'Fixed horizon' as rule, 1 as rule_order, avg(fixed) as false_positive_rate from mart.null_fpr
union all select 'Naive peeking', 2, avg(naive_peeking) from mart.null_fpr
union all select 'O''Brien-Fleming', 3, avg(obrien_fleming) from mart.null_fpr
union all select 'mSPRT', 4, avg(msprt) from mart.null_fpr;

create view bi.peeking_curve as select * from mart.peeking_curve;

create view bi.sequential_stops as
select s.*, case when s.metric_id = 1 then 'primary' else 'guardrail' end as metric_role
from mart.sequential_stops s;

create view bi.sequential_summary as
select 'Naive 1.96' as rule, 1 as rule_order,
       count(*) filter (where naive_day is not null) as arms_stopped,
       count(*) filter (where naive_wrong_call) as wrong_calls,
       null::bigint as agrees_with_fixed, null::double precision as median_days_saved
from mart.sequential_stops where metric_id = 1
union all
select 'O''Brien-Fleming', 2, count(*) filter (where obf_day is not null),
       count(*) filter (where obf_day is not null and not obf_agrees), count(*) filter (where obf_agrees),
       percentile_cont(0.5) within group (order by obf_days_saved)
from mart.sequential_stops where metric_id = 1
union all
select 'mSPRT', 3, count(*) filter (where msprt_day is not null),
       count(*) filter (where msprt_day is not null and not msprt_agrees), count(*) filter (where msprt_agrees),
       percentile_cont(0.5) within group (order by msprt_days_saved)
from mart.sequential_stops where metric_id = 1;

create view bi.verdict_counts as
select verdict, outcome, count(*) as arms,
       case verdict when 'SHIP' then 1 when 'SHIP WITH CAUTION' then 2 when 'INCONCLUSIVE' then 3
                    when 'STOP: guardrail breach' then 4 when 'STOP: primary harm' then 5
                    when 'HOLD: confirm allocation' then 6 else 7 end as verdict_order
from mart.verdicts group by verdict, outcome;

create view bi.decision_sensitivity as
select alpha, ni_margin, verdict, arms,
       'alpha ' || alpha::text as alpha_label,
       'margin ' || to_char(ni_margin * 100, 'FM0.0') || '%' as margin_label
from mart.decision_sensitivity;

create view bi.heterogeneity as
select h.*, case h.metric_id when 1 then 'M1 binary' when 2 then 'M2 count' when 3 then 'M3 count'
                 else 'M4 real-valued' end as metric_name
from mart.heterogeneity h;
create view bi.eb_shrinkage as
select e.*, e.observed_lift - e.eb_lift as shrinkage, abs(e.observed_lift) - abs(e.eb_lift) as abs_shrinkage
from mart.eb_shrinkage e;
create view bi.metric_tree as select * from mart.metric_tree;
create view bi.verdict_segments as select * from mart.verdict_segments;
create view bi.metric_comovement as select * from mart.metric_comovement;
create view bi.metric_sensitivity as select * from mart.metric_sensitivity;
create view bi.early_read as
select r.*, case r.early_metric when 1 then 'M1' when 2 then 'M2' when 3 then 'M3' else 'M4' end as early_metric_name,
       case r.final_metric when 1 then 'M1' when 2 then 'M2' when 3 then 'M3' else 'M4' end as final_metric_name,
       'day ' || r.read_day::int as read_label
from mart.early_read r;
create view bi.dq_checks as select check_id, layer, check_name, severity, failed_rows, total_rows, passed from dq.check_results;
create view bi.load_audit as select * from raw.load_audit;
create view bi.layer_rows as
select 'raw' as layer, 1 as layer_order, 'raw.asos_checkpoints' as object, count(*) as row_count from raw.asos_checkpoints
union all select 'staging', 2, 'stg.checkpoints', count(*) from stg.checkpoints
union all select 'staging', 2, 'stg.rejected_checkpoints', count(*) from stg.rejected_checkpoints
union all select 'mart', 3, 'mart.checkpoint_stats', count(*) from mart.checkpoint_stats
union all select 'mart', 3, 'mart.obf_boundary', count(*) from mart.obf_boundary
union all select 'mart', 3, 'mart.final_results', count(*) from mart.final_results
union all select 'mart', 3, 'mart.verdicts', count(*) from mart.verdicts;
create view bi.dq_incidents as select * from dq.incidents where metric_id = 1;
