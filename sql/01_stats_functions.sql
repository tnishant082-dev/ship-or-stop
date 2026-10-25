-- 01 statistical functions so the verdict logic can live in SQL.
-- normal cdf via erfc with the Numerical Recipes Chebyshev approximation (|error| < 1.2e-7 everywhere,
-- relative accuracy is kept in the tail, which matters for p-values like 1e-20).
create or replace function stats.erfc(x double precision) returns double precision
language sql immutable strict parallel safe as $$
    with t as (select 1.0 / (1.0 + 0.5 * least(abs(x), 26.0)) as t)
    select case when abs(x) >= 26.0 then (case when x > 0 then 0.0 else 2.0 end)
                when x >= 0 then r else 2.0 - r end
    from (select t * exp(-least(x * x, 676.0) - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 +
                 t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 +
                 t * (-0.82215223 + t * 0.17087277))))))))) as r from t) s
$$;

create or replace function stats.norm_sf(z double precision) returns double precision
language sql immutable strict parallel safe as $$ select 0.5 * stats.erfc(z / sqrt(2.0)) $$;

create or replace function stats.norm_cdf(z double precision) returns double precision
language sql immutable strict parallel safe as $$ select 1.0 - stats.norm_sf(z) $$;

create or replace function stats.two_sided_p(z double precision) returns double precision
language sql immutable strict parallel safe as $$ select least(1.0, 2.0 * stats.norm_sf(abs(z))) $$;

-- chi-square with 1 degree of freedom: P(X > x) = 2 * P(Z > sqrt(x))
create or replace function stats.chisq1_sf(x double precision) returns double precision
language sql immutable strict parallel safe as $$ select 2.0 * stats.norm_sf(sqrt(greatest(x, 0))) $$;

-- normal-mixture mSPRT likelihood ratio for H0: delta = 0 (Johari, Pekelis & Walsh 2017)
create or replace function stats.msprt_lambda(d double precision, v double precision, tau2 double precision)
returns double precision language sql immutable strict parallel safe as $$
    select sqrt(v / (v + tau2)) * exp(least(700.0, tau2 * d * d / (2.0 * v * (v + tau2))))
$$;

-- two-sided z critical values used by the sensitivity grid
drop table if exists stats.z_crit;
create table stats.z_crit (alpha numeric primary key, z double precision not null);
insert into stats.z_crit values (0.01, 2.5758293035489), (0.05, 1.9599639845401), (0.10, 1.6448536269515);
