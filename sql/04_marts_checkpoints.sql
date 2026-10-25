-- 04 checkpoint-level statistics, final reads and sample-ratio health.

-- every testable look: difference, unpooled variance, z, relative lift (delta method), information
-- fraction against the final look, naive 1.96 crossings and the mSPRT always-valid p-value
create table mart.checkpoint_stats as
with base as (
    select c.arm_id, c.experiment_id, c.variant_id, c.metric_id, c.metric_name, c.day, c.n_c, c.n_t,
           c.mean_c, c.mean_t,
           c.mean_t - c.mean_c                                          as diff,
           c.variance_c / c.n_c + c.variance_t / c.n_t                  as v,
           c.variance_c / c.n_c                                         as vm_c,
           c.variance_t / c.n_t                                         as vm_t
    from stg.checkpoints c
    where c.is_testable
),
seq as (
    select b.*,
           row_number() over w                                          as look,
           count(*) over (partition by arm_id, metric_id)               as looks,
           last_value(v) over (partition by arm_id, metric_id order by day
                               rows between unbounded preceding and unbounded following) as v_final,
           last_value(mean_c) over (partition by arm_id, metric_id order by day
                               rows between unbounded preceding and unbounded following) as mean_c_final
    from base b
    window w as (partition by arm_id, metric_id order by day)
),
z as (
    select s.*,
           diff / sqrt(v)                                               as z,
           mean_t / mean_c - 1                                          as rel_lift,
           sqrt(vm_t / mean_c ^ 2 + mean_t ^ 2 * vm_c / mean_c ^ 4)      as rel_se,
           least(1.0, v_final / v)                                      as info_raw,
           (0.01 * mean_c_final) ^ 2                                    as tau2
    from seq s
),
m as (
    select z.*,
           max(info_raw) over w                                         as info_frac,
           abs(z.z) >= 1.959964                                         as naive_cross,
           stats.msprt_lambda(diff, v, tau2)                            as msprt_lambda
    from z
    window w as (partition by arm_id, metric_id order by day)
)
select m.*,
       least(1.0, 1.0 / max(msprt_lambda) over w)                      as always_valid_p,
       bool_or(naive_cross) over w                                     as crossed_so_far,
       stats.two_sided_p(m.z)                                          as p_naive
from m
window w as (partition by arm_id, metric_id order by day);

create index on mart.checkpoint_stats (arm_id, metric_id, look);

-- final (full-horizon) read per arm x metric
create table mart.final_reads as
select arm_id, experiment_id, variant_id, metric_id, metric_name, day as horizon_days, looks,
       n_c, n_t, mean_c, mean_t, diff, v, z, rel_lift, rel_se,
       rel_lift - 1.959964 * rel_se                                    as rel_ci_low,
       rel_lift + 1.959964 * rel_se                                    as rel_ci_high,
       p_naive                                                         as p_value,
       always_valid_p                                                  as always_valid_p_final
from mart.checkpoint_stats
where look = looks;

-- sample ratio: chi-square against the 50/50 split most arms use. Arms far from 50/50 were probably split
-- unequally on purpose; the dataset does not publish the planned split, so they are held for a config check.
create table mart.srm as
with f as (
    select arm_id, experiment_id, variant_id, n_c, n_t, (n_c + n_t) / 2.0 as e
    from mart.final_reads where metric_id = 1
)
select arm_id, experiment_id, variant_id, n_c, n_t,
       n_t::double precision / (n_c + n_t)                                         as treatment_share,
       ((n_c - e) ^ 2 + (n_t - e) ^ 2) / e                                         as chi_sq,
       stats.chisq1_sf(((n_c - e) ^ 2 + (n_t - e) ^ 2) / e)                        as srm_p,
       abs(n_t::double precision / (n_c + n_t) - 0.5) > 0.10                        as allocation_unknown,
       (stats.chisq1_sf(((n_c - e) ^ 2 + (n_t - e) ^ 2) / e) < 0.001
        and abs(n_t::double precision / (n_c + n_t) - 0.5) <= 0.10)                 as srm_flag,
       case when abs(n_t::double precision / (n_c + n_t) - 0.5) > 0.10 then 'allocation unknown'
            when stats.chisq1_sf(((n_c - e) ^ 2 + (n_t - e) ^ 2) / e) < 0.001 then 'SRM'
            else 'healthy' end                                                      as ratio_status
from f;

-- how the treatment share moved over the life of each arm (SRM that appears mid-test points to a bug that
-- shipped mid-test, SRM from day one points to assignment)
create table mart.srm_trajectory as
select c.arm_id, c.day, c.look,
       c.n_t::double precision / (c.n_c + c.n_t)                                 as treatment_share,
       stats.chisq1_sf(((c.n_c - (c.n_c + c.n_t) / 2.0) ^ 2 + (c.n_t - (c.n_c + c.n_t) / 2.0) ^ 2)
                       / ((c.n_c + c.n_t) / 2.0))                                as srm_p
from mart.checkpoint_stats c
where c.metric_id = 1;

-- checkpoint glitches: cumulative statistics should move smoothly, so a z that jumps by more than 3 and
-- comes back at the next look points to a bad aggregation run for that checkpoint
create table mart.checkpoint_glitches as
select arm_id, metric_id, day, z, prev_z, next_z
from (select arm_id, metric_id, day, z, lag(z) over w as prev_z, lead(z) over w as next_z
      from mart.checkpoint_stats window w as (partition by arm_id, metric_id order by day)) s
where abs(z - prev_z) > 3 and abs(next_z - z) > 3 and sign(z - prev_z) <> sign(next_z - z);

delete from dq.check_results where layer = 'mart';
insert into dq.check_results (layer, check_name, severity, failed_rows, total_rows, passed)
select 'mart', 'one-checkpoint z spikes (> 3 and back)', 'warn', (select count(*) from mart.checkpoint_glitches),
       (select count(*) from mart.checkpoint_stats), (select count(*) from mart.checkpoint_glitches) = 0
union all
select 'mart', 'final reads per arm x metric equal staging series', 'error',
       abs((select count(*) from mart.final_reads) - (select count(*) from (select distinct arm_id, metric_id
            from stg.checkpoints where is_testable) s)),
       (select count(*) from mart.final_reads),
       (select count(*) from mart.final_reads) = (select count(*) from (select distinct arm_id, metric_id
            from stg.checkpoints where is_testable) s);

insert into dq.incidents
select 'one-checkpoint z spike', arm_id, metric_id, day,
       format('z %s -> %s -> %s', round(prev_z::numeric, 2), round(z::numeric, 2), round(next_z::numeric, 2))
from mart.checkpoint_glitches;
