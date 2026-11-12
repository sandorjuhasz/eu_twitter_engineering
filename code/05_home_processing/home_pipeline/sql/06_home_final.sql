-- ============================================================
-- 06_home_final.sql  --  final home table for analysis
-- Target DB: twitter_cities_v2, schema: revised
--
-- One row per (city, user_id, res), res 10 and 9 (D17). Settings are
-- fixed by the 05 checks: method 'nights', window 20-08, gate 10 tweets
-- / 3 nights / strict lead, high = >= 5 nights (D05, D10, D16).
-- A user has a row per city with a home (D09); at res 9 a few more
-- users pass the gate than at res 10, so the two res are not the same
-- user set.
--
-- Columns besides the home cell:
--   evidence      nights, night tweets and tweets in the home cell and
--                 for the user in the city
--   cell_night_tweets  the home under the 'night_tweets' ranking (most
--                 night tweets instead of most nights), for sensitivity;
--                 null if that method gives no home
--   moved         2013-15 and 2016-17 homes (05, gated as V7) >= 1 km
--                 apart; null if the user has no gated home in both
--                 periods (~95% of users), period_dist_m the distance
--   multi_city    homes in more than one city (same res)
--   suspect_bot   homes in all three cities at any res (05 V5)
--
-- Needs 03 (home_location) and 05 S2a + S2b (home_diag_period_home).
-- The diag tables are UNLOGGED: if they are empty after a server
-- restart, rerun 05 S2a + S2b first.
--
-- S2  home_location + home_diag_period_home -> revised.home_final
-- Small inputs: expect well under a minute.
-- Drops and recreates revised.home_final. Nothing else is touched.
-- ============================================================


-- ------------------------------------------------------------
-- S1  Session settings (shared server: modest values)
--     public on the path for the h3index operators (D14).
-- ------------------------------------------------------------
set work_mem = '256MB';
set max_parallel_workers_per_gather = 4;
set search_path = revised, public;


-- ------------------------------------------------------------
-- S2  Build revised.home_final
-- ------------------------------------------------------------
set role twitter_project;

drop table if exists revised.home_final;

create table revised.home_final as
with params(moved_min_m, period_min_nights, period_min_tweets) as (
    values (1000, 3, 10)
)
, home as (
    select *
    from revised.home_location
    where method = 'nights'
      and night_window = '20-08'
      and res in (10, 9)
)
, alt as (
    select city, user_id, res, cell
    from revised.home_location
    where method = 'night_tweets'
      and night_window = '20-08'
      and res in (10, 9)
)
, period as (
    select a.city
         , a.user_id
         , a.res
         , case when a.cell = b.cell then 0
                else public.st_distancesphere(public.h3_cell_to_geometry(a.cell),
                                              public.h3_cell_to_geometry(b.cell))
           end as dist_m
    from revised.home_diag_period_home a
    join revised.home_diag_period_home b
      on b.city = a.city and b.user_id = a.user_id and b.res = a.res
     and b.period = '2016-17'
    cross join params p
    where a.period = '2013-15'
      and a.strict_lead and b.strict_lead
      and a.d_night >= p.period_min_nights and b.d_night >= p.period_min_nights
      and a.n_user_all >= p.period_min_tweets and b.n_user_all >= p.period_min_tweets
)
select h.city
     , h.user_id
     , h.res
     , h.cell
     , h.confidence
     , h.d_night                                       as d_home_nights
     , h.n_night                                       as n_home_night_tweets
     , h.n_all                                         as n_home_tweets
     , h.d_user_night                                  as d_user_nights
     , h.n_user_night                                  as n_user_night_tweets
     , h.n_user_all                                    as n_user_tweets
     , h.share_user_nights
     , h.share_user_tweets
     , h.d_night_second                                as d_second_nights
     , a.cell                                          as cell_night_tweets
     , p.dist_m >= (select moved_min_m from params)    as moved
     , round(p.dist_m)::integer                        as period_dist_m
     , h.n_home_cities
     , h.n_home_cities > 1                             as multi_city
     , max(h.n_home_cities) over (partition by h.user_id) = 3 as suspect_bot
     , h.is_primary
from home h
left join alt a
  on a.city = h.city and a.user_id = h.user_id and a.res = h.res
left join period p
  on p.city = h.city and p.user_id = h.user_id and p.res = h.res;

alter table revised.home_final add primary key (city, user_id, res);
create index home_final_res_cell_idx on revised.home_final (res, cell);

reset role;

analyze revised.home_final;

reset work_mem;
reset max_parallel_workers_per_gather;


-- ------------------------------------------------------------
-- V1  Counts per city and res: must match 03 home_location
--     ('nights', 20-08): res 9 ams 10,872 / lon 140,959 / pdx 11,174
-- ------------------------------------------------------------
select city
     , res
     , count(*)                                                    as n_homes
     , count(*) filter (where confidence = 'high')                 as n_high
     , round(avg((cell = cell_night_tweets)::int)::numeric, 3)     as share_eq_night_tweets
     , count(moved)                                                as n_moved_known
     , round(avg(moved::int)::numeric, 3)                          as share_moved
     , count(*) filter (where multi_city)                          as n_multi_city
     , count(*) filter (where suspect_bot)                         as n_suspect_bot
from revised.home_final
group by city, res
order by city, res desc;
