-- ============================================================
-- 02_user_cell_counts.sql  --  tweet counts per user, city and hexagon
-- Target DB: twitter_cities_v2, schema: revised
--
-- revised.home_input -> revised.home_user_cell (UNLOGGED),
-- one row per (city, user_id, res, cell) with
--   n_all          all tweets in the cell
--   n_night_20_08  local hour >= 20 or < 8   (D02 default)
--   n_night_22_07  local hour >= 22 or < 7   (D02 sensitivity)
-- at res 10, 9, 8. Res 9 / 8 are summed from res 10 via
-- h3_cell_to_parent, which is exact (D14).
--
-- No user or cell is filtered here: minimum activity (D05), the
-- "no home" rule (D12) and the ranking (D10) are applied in step 03.
--
-- Reads only home_input (~43.6M rows): expect a few minutes.
-- Drops and recreates revised.home_user_cell. Nothing else is touched.
-- ============================================================


-- ------------------------------------------------------------
-- S1  Session settings (shared server: modest values)
-- ------------------------------------------------------------
set work_mem = '256MB';
set max_parallel_workers_per_gather = 4;


-- ------------------------------------------------------------
-- S2  Build revised.home_user_cell
-- ------------------------------------------------------------
set role twitter_project;

drop table if exists revised.home_user_cell;

create unlogged table revised.home_user_cell as
with c10 as materialized (
    select city
         , user_id
         , cell_10
         , count(*)                                                      as n_all
         , count(*) filter (where local_hour >= 20 or local_hour < 8)    as n_night_20_08
         , count(*) filter (where local_hour >= 22 or local_hour < 7)    as n_night_22_07
    from revised.home_input
    group by city, user_id, cell_10
)
select city, user_id, 10::smallint as res, cell_10 as cell
     , n_all, n_night_20_08, n_night_22_07
from c10
union all
select city, user_id, 9::smallint, public.h3_cell_to_parent(cell_10, 9)
     , sum(n_all)::bigint, sum(n_night_20_08)::bigint, sum(n_night_22_07)::bigint
from c10
group by city, user_id, public.h3_cell_to_parent(cell_10, 9)
union all
select city, user_id, 8::smallint, public.h3_cell_to_parent(cell_10, 8)
     , sum(n_all)::bigint, sum(n_night_20_08)::bigint, sum(n_night_22_07)::bigint
from c10
group by city, user_id, public.h3_cell_to_parent(cell_10, 8);

alter table revised.home_user_cell add primary key (city, user_id, res, cell);

reset role;

analyze revised.home_user_cell;

reset work_mem;
reset max_parallel_workers_per_gather;


-- ------------------------------------------------------------
-- V1  Rows and totals per city and resolution. n_all must be the
--     same at every res within a city (and equal home_input V1).
-- ------------------------------------------------------------
select city
     , res
     , count(*)                  as n_rows
     , count(distinct user_id)   as n_users
     , sum(n_all)                as n_all
     , sum(n_night_20_08)        as n_night_20_08
     , sum(n_night_22_07)        as n_night_22_07
from revised.home_user_cell
group by city, res
order by city, res desc;


-- ------------------------------------------------------------
-- V2  Table size on disk
-- ------------------------------------------------------------
select pg_size_pretty(pg_table_size('revised.home_user_cell'))      as table_size
     , pg_size_pretty(pg_indexes_size('revised.home_user_cell'))    as index_size;
