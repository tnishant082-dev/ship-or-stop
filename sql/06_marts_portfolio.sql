-- 06 program-level marts: portfolio KPIs, metric tree, segment heterogeneity, metric co-movement,
-- early-read reliability.

create table mart.program_kpis as
with v as (select * from mart.verdicts),
s as (select * from mart.sequential_stops where metric_id = 1),
n as (select avg(naive_peeking) naive, avg(obrien_fleming) obf, avg(msprt) ms, avg(fixed) fixed from mart.null_fpr)
select
    (select count(*) from stg.experiments)                                         as experiments,
    (select count(*) from v)                                                       as arms,
    (select count(*) from mart.checkpoint_stats)                                   as testable_checkpoints,
    (select count(*) filter (where verdict = 'SHIP') from v)                       as ship,
    (select count(*) filter (where verdict like 'STOP%') from v)                   as stop,
    (select count(*) filter (where verdict = 'INCONCLUSIVE') from v)               as inconclusive,
    (select count(*) filter (where outcome = 'untrusted') from v)                  as untrusted,
    (select avg((verdict = 'SHIP')::int) from v)                                   as ship_rate,
    (select avg((verdict like 'STOP%')::int) from v)                               as harm_rate,
    (select avg((ratio_status = 'SRM')::int) from mart.srm)                        as srm_rate,
    (select fixed from n) as fpr_fixed, (select naive from n) as fpr_naive,
    (select obf from n) as fpr_obf, (select ms from n) as fpr_msprt,
    (select count(*) filter (where naive_wrong_call) from s)                       as naive_wrong_calls,
    (select count(*) filter (where fixed_sig) from s)                              as primary_fixed_sig,
    (select count(*) filter (where obf_agrees) from s)                             as obf_agrees,
    (select count(*) filter (where msprt_agrees) from s)                           as msprt_agrees,
    (select percentile_cont(0.5) within group (order by obf_days_saved) from s)    as obf_median_days_saved,
    (select percentile_cont(0.5) within group (order by msprt_days_saved) from s)  as msprt_median_days_saved,
    (select percentile_cont(0.5) within group (order by horizon_days) from s)      as median_horizon_days,
    (select sum(horizon_days) from s)                                              as arm_days_run,
    (select sum(obf_days_saved) from s)                                            as arm_days_saved_obf,
    (select avg(eb_lift) filter (where verdict = 'SHIP') from v)                   as avg_shrunk_win_lift,
    (select avg(primary_lift) filter (where verdict = 'SHIP') from v)              as avg_observed_win_lift,
    (select percentile_cont(0.5) within group (order by mde_rel_80) from v)        as median_mde_rel,
    (select tau from mart.heterogeneity where metric_id = 1)                       as tau_primary,
    (select count(*) from dq.check_results where not passed and severity = 'error') as dq_errors;

-- metric tree: program health decomposed into trust, speed, impact and risk
create table mart.metric_tree as
with k as (select * from mart.program_kpis)
select * from (values
  (1, 'Program health', 'Trust',  'Arms with a healthy sample ratio', (select avg((ratio_status = 'healthy')::int) from mart.srm), 0.95, 'share'),
  (2, 'Program health', 'Trust',  'Data quality errors', (select dq_errors::double precision from k), 0, 'count'),
  (3, 'Program health', 'Trust',  'False positive rate of the stopping rule in use (naive peeking)', (select fpr_naive from k), 0.05, 'share'),
  (4, 'Program health', 'Speed',  'Median days to a decision (full horizon)', (select median_horizon_days from k), 28, 'days'),
  (5, 'Program health', 'Speed',  'Median days saved by O''Brien-Fleming', (select obf_median_days_saved from k), 14, 'days'),
  (6, 'Program health', 'Speed',  'Arm-days that OBF would have freed', (select arm_days_saved_obf from k), null, 'days'),
  (7, 'Program health', 'Impact', 'Ship rate', (select ship_rate from k), 0.20, 'share'),
  (8, 'Program health', 'Impact', 'Average observed lift of shipped arms', (select avg_observed_win_lift from k), null, 'share'),
  (9, 'Program health', 'Impact', 'Average shrunk lift of shipped arms', (select avg_shrunk_win_lift from k), null, 'share'),
  (10, 'Program health', 'Risk',  'Harm rate (primary or guardrail)', (select harm_rate from k), 0.10, 'share'),
  (11, 'Program health', 'Risk',  'Primary arms a naive peek would have called wrongly', (select naive_wrong_calls::double precision from k), 0, 'count'),
  (12, 'Program health', 'Risk',  'Median relative MDE at 80% power', (select median_mde_rel from k), 0.01, 'share')
) t(node_id, root, branch, kpi, value, target, unit);

alter table mart.metric_tree add column status text, add column value_display text, add column target_display text;
update mart.metric_tree set
    value_display  = case unit when 'share' then to_char(value * 100, 'FM990.0') || '%'
                               when 'days' then to_char(value, 'FM999,990.0') || ' days'
                               else to_char(value, 'FM999,990') end,
    target_display = case when target is null then '-'
                          when unit = 'share' then to_char(target * 100, 'FM990.0') || '%'
                          when unit = 'days' then to_char(target, 'FM990') || ' days'
                          else to_char(target, 'FM990') end;
update mart.metric_tree set status = case
    when target is null then 'info'
    when kpi like 'Median days saved%' or kpi like 'Arms with a healthy%' or kpi = 'Ship rate'
         then case when value >= target then 'on target' else 'off target' end
    else case when value <= target then 'on target' else 'off target' end end;

-- segment heterogeneity: do outcomes differ by the kind of experiment?
create table mart.verdict_segments as
with a as (
    select v.*, e.arms as experiment_arms,
           case when v.final_n < 500000 then '1 small (<0.5M)' when v.final_n < 2000000 then '2 medium (0.5-2M)'
                else '3 large (2M+)' end                                              as size_band,
           case when v.horizon_days <= 21 then '1 up to 3 weeks' when v.horizon_days <= 42 then '2 3-6 weeks'
                else '3 over 6 weeks' end                                             as horizon_band,
           case when e.arms = 1 then '1 A/B' else '2 A/B/n' end                       as design
    from mart.verdicts v join stg.experiments e using (experiment_id)
),
long as (
    select 'size' as dimension, size_band as segment, * from a
    union all select 'horizon', horizon_band, * from a
    union all select 'design', design, * from a
)
select dimension, segment, count(*) as arms,
       avg((outcome = 'win')::int)        as win_rate,
       avg((outcome = 'loss')::int)       as loss_rate,
       avg((outcome = 'flat')::int)       as flat_rate,
       avg((outcome = 'untrusted')::int)  as untrusted_rate,
       avg(abs(primary_lift))             as avg_abs_lift,
       percentile_cont(0.5) within group (order by mde_rel_80) as median_mde
from long group by dimension, segment;

-- do the four metrics tell the same story? correlation of final z across arms, per metric pair
create table mart.metric_comovement as
select a.metric_id as metric_a, b.metric_id as metric_b,
       a.metric_name as metric_a_name, b.metric_name as metric_b_name,
       corr(a.z, b.z)                                                      as z_corr,
       avg((sign(a.z) = sign(b.z))::int)                                   as sign_agreement,
       avg((a.sig_raw = b.sig_raw)::int)                                   as significance_agreement,
       count(*)                                                            as arms
from mart.final_results a
join mart.final_results b using (arm_id)
group by 1, 2, 3, 4;

create table mart.metric_sensitivity as
select metric_id, metric_name, count(*) as arms,
       avg(sig_raw::int)                                       as share_significant,
       avg(sig_holm::int)                                      as share_significant_holm,
       percentile_cont(0.5) within group (order by abs(z))     as median_abs_z,
       percentile_cont(0.5) within group (order by mde_rel_80) as median_mde_rel
from mart.final_results group by 1, 2;

-- early read: how well does the z at day d predict the final z?
create table mart.early_read as
with days(read_day) as (values (3.0), (7.0), (14.0), (21.0), (28.0)),
early as (
    select d.read_day, c.arm_id, c.metric_id, c.z,
           row_number() over (partition by d.read_day, c.arm_id, c.metric_id order by c.day desc) rn
    from days d join mart.checkpoint_stats c on c.day <= d.read_day
)
select e.read_day, e.metric_id as early_metric, f.metric_id as final_metric,
       count(*)                                                                   as arms,
       corr(e.z, f.z)                                                             as z_corr,
       avg((sign(e.z) = sign(f.z))::int) filter (where f.sig_raw)                 as sign_agreement_when_final_sig,
       avg((abs(e.z) >= 1.959964)::int)                                           as share_sig_early,
       avg(((abs(e.z) >= 1.959964) and not f.sig_raw)::int)                       as share_early_sig_not_final
from early e
join mart.final_results f on f.arm_id = e.arm_id
join mart.final_results fp on fp.arm_id = e.arm_id and fp.metric_id = e.metric_id
where e.rn = 1 and fp.horizon_days > e.read_day
group by 1, 2, 3;
