-- 05 verdicts: multiplicity, guardrails, sequential stopping and the decision sensitivity grid.

-- program policy lives in a table so the grid below and the dashboard read the same numbers
create table mart.policy as
select 0.05::numeric as alpha, 1.959964::double precision as z_crit, 0.01::double precision as ni_margin,
       1 as primary_metric, 0.001::double precision as srm_p, 0.01::double precision as msprt_tau_rel,
       20.0::double precision as msprt_threshold;

-- final results with Holm inside each experiment (its arms x 4 metrics form one family) and BH across
-- the whole program, plus the MDE each arm could actually detect
create table mart.final_results as
with ranked as (
    select f.*,
           row_number() over (partition by experiment_id order by p_value)  as k_exp,
           count(*)     over (partition by experiment_id)                   as m_exp,
           row_number() over (order by p_value)                             as k_all,
           count(*)     over ()                                             as m_all
    from mart.final_reads f
),
holm as (
    select r.*,
           max(least(1.0, (m_exp - k_exp + 1) * p_value))
               over (partition by experiment_id order by k_exp rows unbounded preceding)  as p_holm,
           min(least(1.0, p_value * m_all / k_all))
               over (order by k_all desc rows unbounded preceding)                         as p_bh
    from ranked r
)
select h.arm_id, h.experiment_id, h.variant_id, h.metric_id, h.metric_name, h.horizon_days, h.looks,
       h.n_c, h.n_t, h.mean_c, h.mean_t, h.diff, h.z, h.rel_lift, h.rel_se, h.rel_ci_low, h.rel_ci_high,
       h.p_value, h.p_holm, h.p_bh, h.always_valid_p_final,
       h.p_value < 0.05 as sig_raw, h.p_holm < 0.05 as sig_holm, h.p_bh < 0.05 as sig_bh,
       (1.959964 + 0.841621) * sqrt(h.v) / h.mean_c as mde_rel_80,
       s.ratio_status, e.eb_lift, e.shrink_factor
from holm h
join mart.srm s using (arm_id)
left join mart.eb_shrinkage e using (arm_id, metric_id);

-- verdict engine: primary superiority + every guardrail non-inferior + healthy sample ratio
create or replace function mart.verdict(p_z double precision, p_margin double precision)
returns table (arm_id text, experiment_id text, verdict text, primary_lift double precision,
               primary_low double precision, primary_high double precision,
               guardrails_breached int, guardrails_unproven int, worst_guardrail_low double precision)
language sql stable as $$
    with g as (
        select f.arm_id,
               count(*) filter (where f.rel_lift + p_z * f.rel_se < -p_margin)                   as breached,
               count(*) filter (where f.rel_lift - p_z * f.rel_se < -p_margin
                                  and f.rel_lift + p_z * f.rel_se >= -p_margin)                 as unproven,
               min(f.rel_lift - p_z * f.rel_se)                                                as worst_low
        from mart.final_results f where f.metric_id <> 1 group by f.arm_id
    )
    select p.arm_id, p.experiment_id,
           case when p.ratio_status = 'SRM'                    then 'INVALID: SRM'
                when p.ratio_status = 'allocation unknown'     then 'HOLD: confirm allocation'
                when p.rel_lift + p_z * p.rel_se < 0           then 'STOP: primary harm'
                when coalesce(g.breached, 0) > 0               then 'STOP: guardrail breach'
                when p.rel_lift - p_z * p.rel_se > 0
                     and coalesce(g.unproven, 0) = 0           then 'SHIP'
                when p.rel_lift - p_z * p.rel_se > 0           then 'SHIP WITH CAUTION'
                else 'INCONCLUSIVE' end,
           p.rel_lift, p.rel_lift - p_z * p.rel_se, p.rel_lift + p_z * p.rel_se,
           coalesce(g.breached, 0)::int, coalesce(g.unproven, 0)::int, g.worst_low
    from mart.final_results p
    left join g using (arm_id)
    where p.metric_id = 1
$$;

create table mart.verdicts as
select v.*, a.horizon_days, a.final_n,
       case when v.verdict like 'SHIP%' then 'win' when v.verdict like 'STOP%' then 'loss'
            when v.verdict = 'INCONCLUSIVE' then 'flat' else 'untrusted' end as outcome,
       f.eb_lift, f.mde_rel_80, f.p_holm
from mart.verdict(1.959964, 0.01) v
join stg.arms a using (arm_id)
join mart.final_results f on f.arm_id = v.arm_id and f.metric_id = 1;

-- sequential replay: when would each stopping rule have called the arm, and does it agree with the
-- full-horizon answer?
create table mart.sequential_stops as
with c as (
    select c.arm_id, c.metric_id, c.look, c.looks, c.day, c.z, c.msprt_lambda, b.boundary
    from mart.checkpoint_stats c
    join mart.obf_boundary b using (arm_id, metric_id, look)
),
firsts as (
    select arm_id, metric_id, max(looks) as looks, max(day) as horizon_days,
           min(day)  filter (where abs(z) >= 1.959964)                       as naive_day,
           min(look) filter (where abs(z) >= 1.959964)                       as naive_look,
           min(day)  filter (where abs(z) >= boundary)                       as obf_day,
           min(look) filter (where abs(z) >= boundary)                       as obf_look,
           min(day)  filter (where msprt_lambda >= 20)                       as msprt_day,
           min(look) filter (where msprt_lambda >= 20)                       as msprt_look
    from c group by arm_id, metric_id
),
signs as (
    select f.*,
           (select sign(z) from c where c.arm_id = f.arm_id and c.metric_id = f.metric_id and c.look = f.naive_look) as naive_sign,
           (select sign(z) from c where c.arm_id = f.arm_id and c.metric_id = f.metric_id and c.look = f.obf_look)   as obf_sign,
           (select sign(z) from c where c.arm_id = f.arm_id and c.metric_id = f.metric_id and c.look = f.msprt_look) as msprt_sign
    from firsts f
)
select s.*, r.sig_raw as fixed_sig, sign(r.z) as fixed_sign, r.ratio_status,
       (s.naive_day is not null and (not r.sig_raw or s.naive_sign <> sign(r.z)))  as naive_wrong_call,
       (s.obf_day is not null and r.sig_raw and s.obf_sign = sign(r.z))            as obf_agrees,
       (s.msprt_day is not null and r.sig_raw and s.msprt_sign = sign(r.z))        as msprt_agrees,
       case when s.obf_day is not null and r.sig_raw and s.obf_sign = sign(r.z)
            then s.horizon_days - s.obf_day end                                    as obf_days_saved,
       case when s.msprt_day is not null and r.sig_raw and s.msprt_sign = sign(r.z)
            then s.horizon_days - s.msprt_day end                                  as msprt_days_saved
from signs s
join mart.final_results r using (arm_id, metric_id);

-- how fragile is the portfolio to the two policy knobs?
create table mart.decision_sensitivity as
select zc.alpha, m.margin as ni_margin, v.verdict, count(*) as arms
from stats.z_crit zc
cross join (values (0.0::double precision), (0.005), (0.01), (0.02), (0.03)) m(margin)
cross join lateral mart.verdict(zc.z, m.margin) v
group by 1, 2, 3;
