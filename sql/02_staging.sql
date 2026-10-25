-- 02 staging: typed, de-duplicated checkpoints with series keys and look numbers.
-- A "series" is one treatment arm (experiment x variant) on one metric. Control stats are repeated on each
-- variant row in the source, so every row is a self-contained treatment-vs-control comparison.

create table stg.checkpoints as
with dedup as (
    select distinct on (experiment_id, variant_id, metric_id, round(time_since_start::numeric, 2))
           r.*
    from raw.asos_checkpoints r
    order by experiment_id, variant_id, metric_id, round(time_since_start::numeric, 2), count_c desc
),
typed as (
    select experiment_id,
           variant_id,
           experiment_id || '/v' || variant_id                    as arm_id,
           metric_id,
           case metric_id when 1 then 'M1 binary' when 2 then 'M2 count'
                          when 3 then 'M3 count' else 'M4 real-valued' end as metric_name,
           round(time_since_start::numeric, 2)::double precision  as day,
           count_c::bigint                                        as n_c,
           count_t::bigint                                        as n_t,
           mean_c, mean_t, variance_c, variance_t,
           (variance_c is not null and variance_t is not null
            and count_c > 1 and count_t > 1 and mean_c > 0)       as is_testable
    from dedup
)
select t.*,
       row_number() over w                                        as look_seq,
       count(*) over (partition by arm_id, metric_id)             as n_looks_all,
       lag(n_c) over w                                            as prev_n_c,
       lag(n_t) over w                                            as prev_n_t,
       day - lag(day) over w                                      as day_step
from typed t
window w as (partition by arm_id, metric_id order by day);

create index on stg.checkpoints (arm_id, metric_id, day);

-- rows that cannot be used for inference are kept aside, not silently dropped
create table stg.rejected_checkpoints as
select *, case when n_c = 0 and n_t = 0 then 'empty checkpoint (logging gap)'
               when variance_c is null or variance_t is null then 'missing variance'
               when n_c <= 1 or n_t <= 1 then 'n <= 1'
               else 'zero control mean' end as reason
from stg.checkpoints
where not is_testable;

create table stg.arms as
select arm_id,
       min(experiment_id)                                          as experiment_id,
       min(variant_id)                                             as variant_id,
       count(distinct metric_id)                                   as metrics,
       max(day)                                                    as horizon_days,
       max(n_c + n_t) filter (where metric_id = 1)                 as final_n,
       count(*) filter (where metric_id = 1 and is_testable)       as primary_looks
from stg.checkpoints
group by arm_id;

create table stg.experiments as
select experiment_id,
       count(*)                       as arms,
       max(horizon_days)              as horizon_days,
       max(final_n)                   as max_arm_n,
       sum(primary_looks)             as primary_looks
from stg.arms
group by experiment_id;
