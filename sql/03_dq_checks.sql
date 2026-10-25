-- 03 data quality checks on staging. 'error' rows stop the pipeline (scripts/run_pipeline.py).
delete from dq.check_results where layer = 'staging';

with
raw_n  as (select count(*) n from raw.asos_checkpoints),
stg_n  as (select count(*) n from stg.checkpoints),
dups   as (select count(*) - count(distinct (experiment_id, variant_id, metric_id, time_since_start)) n
           from raw.asos_checkpoints),
untest as (select count(*) n from stg.checkpoints where not is_testable),
nondec as (select count(*) n from (
               select n_c, n_t, lag(n_c) over w pc, lag(n_t) over w pt from stg.checkpoints where is_testable
               window w as (partition by arm_id, metric_id order by day)) s where n_c < pc or n_t < pt),
empty  as (select count(*) n from stg.checkpoints where n_c = 0 and n_t = 0),
binr   as (select count(*) n from stg.checkpoints
           where metric_id = 1 and (mean_c not between 0 and 1 or mean_t not between 0 and 1)),
-- the same arm should carry the same sample sizes on every metric at a given checkpoint
xmetric as (
    select count(*) n from (
        select arm_id, day from stg.checkpoints where is_testable
        group by arm_id, day having count(distinct n_c) > 1 or count(distinct n_t) > 1) s),
-- variants of one experiment share the control group
shared_ctrl as (
    select count(*) n from (
        select experiment_id, metric_id, day from stg.checkpoints where is_testable
        group by experiment_id, metric_id, day having count(distinct n_c) > 1) s),
short_series as (select count(*) n from (select arm_id, metric_id from stg.checkpoints where is_testable
                                         group by 1, 2 having count(*) < 4) s),
irregular as (select count(*) n from stg.checkpoints where day_step is not null and day_step not in (0.5, 1.0)),
gaps as (select count(*) n from stg.checkpoints where day_step > 3),
no_primary as (select count(*) n from stg.arms where primary_looks = 0),
series_n as (select count(*) n from (select distinct arm_id, metric_id from stg.checkpoints) s),
arms_n as (select count(*) n from stg.arms)
insert into dq.check_results (layer, check_name, severity, failed_rows, total_rows, passed)
select 'staging', c, s, f, t, f = 0 from (values
    ('raw rows reconcile to staging + duplicates', 'error',
        (select n from raw_n) - (select n from stg_n) - (select n from dups), (select n from raw_n)),
    ('duplicate checkpoint keys in raw', 'error', (select n from dups), (select n from raw_n)),
    ('binary metric means inside [0, 1]', 'error', (select n from binr), (select n from stg_n)),
    ('cumulative sample size never decreases', 'warn', (select n from nondec), (select n from stg_n)),
    ('empty checkpoints (all-zero rows, logging gap)', 'warn', (select n from empty), (select n from stg_n)),
    ('rows not testable (missing variance or n <= 1)', 'warn', (select n from untest), (select n from stg_n)),
    ('arm sample size differs across metrics at a checkpoint', 'warn', (select n from xmetric), (select n from stg_n)),
    ('variants of one experiment report different control n', 'warn', (select n from shared_ctrl), (select n from stg_n)),
    ('series with fewer than 4 testable looks', 'warn', (select n from short_series), (select n from series_n)),
    ('checkpoint spacing not 12h or 24h', 'warn', (select n from irregular), (select n from stg_n)),
    ('gaps longer than 3 days between checkpoints', 'warn', (select n from gaps), (select n from stg_n)),
    ('arms without a testable primary metric', 'error', (select n from no_primary), (select n from arms_n))
) v(c, s, f, t);

-- row-level incident log for the warnings above, so they can be followed up rather than just counted
drop table if exists dq.incidents;
create table dq.incidents as
select 'sample size went down' as incident, arm_id, metric_id, day,
       format('control %s -> %s, treatment %s -> %s', pc, n_c, pt, n_t) as detail
from (select arm_id, metric_id, day, n_c, n_t, lag(n_c) over w pc, lag(n_t) over w pt
      from stg.checkpoints where is_testable
      window w as (partition by arm_id, metric_id order by day)) s
where n_c < pc or n_t < pt
union all
select 'empty checkpoint', arm_id, metric_id, day, 'all counts and stats are zero'
from stg.checkpoints where n_c = 0 and n_t = 0
union all
select 'gap > 3 days', arm_id, metric_id, day, format('%s days since previous checkpoint', day_step)
from stg.checkpoints where day_step > 3;
