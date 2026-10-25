-- 00 schemas and raw landing tables. raw is append-only per load; everything downstream is rebuilt.
create schema if not exists raw;
create schema if not exists dq;
create schema if not exists stats;
drop schema if exists bi cascade;
drop schema if exists mart cascade;
drop schema if exists stg cascade;
create schema stg;
create schema mart;
create schema bi;

create table if not exists raw.asos_checkpoints (
    experiment_id    text             not null,
    variant_id       integer          not null,
    metric_id        integer          not null,
    time_since_start double precision not null,
    count_c          bigint,
    count_t          bigint,
    mean_c           double precision,
    mean_t           double precision,
    variance_c       double precision,
    variance_t       double precision
);

create table if not exists raw.load_audit (
    load_id       serial primary key,
    source_file   text not null,
    source_sha256 text not null,
    rows_loaded   integer not null,
    loaded_at     timestamptz not null default now()
);

create table if not exists dq.check_results (
    check_id    serial primary key,
    layer       text    not null,
    check_name  text    not null,
    severity    text    not null check (severity in ('error', 'warn')),
    failed_rows bigint  not null,
    total_rows  bigint  not null,
    passed      boolean not null,
    checked_at  timestamptz not null default now()
);
