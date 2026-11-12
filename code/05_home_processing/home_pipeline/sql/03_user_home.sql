-- ============================================================
-- 03_user_home.sql  --  home hexagon per user, city and resolution
-- Target DB: twitter_cities_v2, schema: revised
--
-- A home needs both activity and night evidence: the user has >= 10
-- tweets in the city (min_user_tweets), and the winning cell has >= 3
-- distinct nights (min_home_nights) and strictly more nights than the
-- user's second cell.
--
-- S2a  revised.home_input -> revised.home_user_cell_nights (UNLOGGED)
--        distinct nights with a night tweet per (city, user, res, cell)
--      revised.home_input -> revised.home_user (UNLOGGED)
--        user totals per city: tweets, night tweets, distinct days / nights
-- S2b  home_user_cell + home_user_cell_nights + home_user
--        -> revised.home_location (normal table, D14)
--
-- One row per (method, night_window, city, user_id, res):
--   D10  method 'nights'       most distinct nights in the cell (default)
--               'night_tweets' most night tweets in the cell
--               'ratio'        legacy: night / all tweets in the cell, only
--                              for users with >= 20 tweets and cells with
--                              >= 2 night tweets (reproduces the first run)
--   D15  a "night" is the local evening plus the following morning:
--        night_date = (created_local - 8 hours)::date, so 20:00 on day D
--        and 07:59 on day D+1 both belong to night D (same for 22-07)
--   D05  'nights' / 'night_tweets': user has >= min_user_tweets in the
--        city, home cell has >= min_home_nights distinct nights and
--        strictly more nights than the second cell (no ties); users
--        below get no row. Candidates: any cell with >= 1 night tweet.
--   D16  confidence  high    >= 5 nights (high_min_nights), strictly
--                            more nights than the second cell
--                    medium  >= 2 nights, strictly more than the second
--                            (with the D05 gate: 3-4 nights)
--                    low     the rest (only 'ratio' rows)
--        Absolute night counts, not a share of the user's nights: a share
--        favours light users (3 of 4 nights) over heavy ones.
--   D02  both night windows ('20-08' default, '22-07' sensitivity)
--   D09  home per (user, city); n_home_cities and is_primary per user
--
-- Ties in every method end on n_all and then cell id (deterministic).
--
-- Reads home_input once per S2a table, then the S2a tables and
-- home_user_cell: expect about 10-20 min in total.
-- Drops and recreates revised.home_user_cell_nights, revised.home_user
-- and revised.home_location. Nothing else is touched.
-- ============================================================


-- ------------------------------------------------------------
-- S1  Session settings (shared server: modest values)
--     The h3index operators (=, <) live in schema public; comparing two
--     cells fails with "operator does not exist" without it on the path.
--     Kept for the V queries below, which also compare cells.
-- ------------------------------------------------------------
set work_mem = '256MB';
set max_parallel_workers_per_gather = 4;
set search_path = revised, public;


-- ------------------------------------------------------------
-- S2a  Distinct nights per cell, and user totals
-- ------------------------------------------------------------
set role twitter_project;

drop table if exists revised.home_user_cell_nights;

create unlogged table revised.home_user_cell_nights as
with night as materialized (
    select distinct city
         , user_id
         , cell_10
         , (created_local - interval '8 hours')::date      as night_date
         , (local_hour >= 22 or local_hour < 7)             as in_22_07
    from revised.home_input
    where local_hour >= 20 or local_hour < 8
)
select city, user_id, 10::smallint as res, cell_10 as cell
     , count(distinct night_date)                           as d_night_20_08
     , count(distinct night_date) filter (where in_22_07)   as d_night_22_07
from night
group by city, user_id, cell_10
union all
select city, user_id, 9::smallint, public.h3_cell_to_parent(cell_10, 9)
     , count(distinct night_date)
     , count(distinct night_date) filter (where in_22_07)
from night
group by city, user_id, public.h3_cell_to_parent(cell_10, 9)
union all
select city, user_id, 8::smallint, public.h3_cell_to_parent(cell_10, 8)
     , count(distinct night_date)
     , count(distinct night_date) filter (where in_22_07)
from night
group by city, user_id, public.h3_cell_to_parent(cell_10, 8);

alter table revised.home_user_cell_nights add primary key (city, user_id, res, cell);

drop table if exists revised.home_user;

create unlogged table revised.home_user as
select city
     , user_id
     , count(*)                                                          as n_all
     , count(*) filter (where local_hour >= 20 or local_hour < 8)        as n_night_20_08
     , count(*) filter (where local_hour >= 22 or local_hour < 7)        as n_night_22_07
     , count(distinct created_local::date)                               as d_active
     , count(distinct (created_local - interval '8 hours')::date)
           filter (where local_hour >= 20 or local_hour < 8)             as d_night_20_08
     , count(distinct (created_local - interval '8 hours')::date)
           filter (where local_hour >= 22 or local_hour < 7)             as d_night_22_07
from revised.home_input
group by city, user_id;

alter table revised.home_user add primary key (city, user_id);

reset role;

analyze revised.home_user_cell_nights;
analyze revised.home_user;


-- ------------------------------------------------------------
-- S2b  Build revised.home_location
-- ------------------------------------------------------------
set role twitter_project;

drop table if exists revised.home_location;

create table revised.home_location as
with params(min_user_tweets, min_home_nights, ratio_min_user_tweets, ratio_min_night_per_cell, high_min_nights) as (
    values (10, 3, 20, 2, 5)
)
, candidates as (
    select w.night_window
         , c.city
         , c.user_id
         , c.res
         , c.cell
         , c.n_all
         , case w.night_window when '20-08' then c.n_night_20_08 else c.n_night_22_07 end as n_night
         , case w.night_window when '20-08' then n.d_night_20_08 else n.d_night_22_07 end as d_night
         , u.n_all                                                                         as n_user_all
         , case w.night_window when '20-08' then u.n_night_20_08 else u.n_night_22_07 end as n_user_night
         , case w.night_window when '20-08' then u.d_night_20_08 else u.d_night_22_07 end as d_user_night
    from revised.home_user_cell c
    join revised.home_user_cell_nights n
      on n.city = c.city
     and n.user_id = c.user_id
     and n.res = c.res
     and n.cell = c.cell
    join revised.home_user u
      on u.city = c.city
     and u.user_id = c.user_id
    cross join (values ('20-08'), ('22-07')) w(night_window)
)
, scored as (
    select m.method
         , c.*
         , c.n_night::double precision / c.n_all as ratio
         , case m.method
               when 'nights'       then c.d_night::double precision
               when 'night_tweets' then c.n_night::double precision
               else                     c.n_night::double precision / c.n_all
           end as k1
         , case m.method
               when 'nights'       then c.n_night
               when 'night_tweets' then c.d_night
               else                     c.n_all
           end as k2
         , case m.method when 'ratio' then 0 else c.n_all end as k3
    from candidates c
    cross join (values ('nights'), ('night_tweets'), ('ratio')) m(method)
    where c.n_night >= 1
      and (   m.method <> 'ratio'
           or (    c.n_user_all >= (select ratio_min_user_tweets from params)
               and c.n_night >= (select ratio_min_night_per_cell from params)))
)
, ranked as (
    select s.*
         , row_number() over w   as rk
         , lead(cell) over w     as cell_second
         , lead(d_night) over w  as d_night_second
         , lead(n_night) over w  as n_night_second
         , lead(ratio) over w    as ratio_second
         , count(*) over (partition by method, night_window, city, user_id, res) as n_candidates
    from scored s
    window w as (
        partition by method, night_window, city, user_id, res
        order by k1 desc, k2 desc, k3 desc, cell
    )
)
select method
     , night_window
     , city
     , user_id
     , res
     , cell
     , d_night
     , n_night
     , n_all
     , ratio
     , cell_second
     , d_night_second
     , n_night_second
     , ratio_second
     , n_candidates
     , n_user_all
     , n_user_night
     , d_user_night
     , n_all::double precision / n_user_all                               as share_user_tweets
     , n_night::double precision / n_user_night                           as share_user_night
     , d_night::double precision / d_user_night                           as share_user_nights
     , case
           when d_night >= (select high_min_nights from params)
            and d_night > coalesce(d_night_second, 0)                      then 'high'
           when d_night >= 2
            and d_night > coalesce(d_night_second, 0)                      then 'medium'
           else 'low'
       end                                                                as confidence
     , count(*) over (partition by method, night_window, user_id, res)    as n_home_cities
     , row_number() over (
           partition by method, night_window, user_id, res
           order by d_user_night desc, n_user_night desc, n_user_all desc, city
       ) = 1                                                              as is_primary
from ranked
where rk = 1
  and (   method = 'ratio'
       or (    n_user_all >= (select min_user_tweets from params)
           and d_night >= (select min_home_nights from params)
           and d_night > coalesce(d_night_second, 0)));

alter table revised.home_location add primary key (method, night_window, city, user_id, res);

reset role;

analyze revised.home_location;

reset work_mem;
reset max_parallel_workers_per_gather;


-- ------------------------------------------------------------
-- V1  Coverage and strength per method, city and res (20-08).
--     'ratio' must match the first run (e.g. london res 10: 164,458).
--     'nights' res 9 with min_home_nights = 3 and no min_user_tweets:
--     ams 12,509; lon 150,228; pdx 11,828 (upper bound for this run).
-- ------------------------------------------------------------
select method
     , city
     , res
     , count(*)                                               as n_homes
     , count(*) filter (where n_user_all >= 20)               as n_homes_20plus
     , count(*) filter (where confidence = 'high')            as n_high
     , count(*) filter (where confidence = 'medium')          as n_medium
     , count(*) filter (where confidence = 'low')             as n_low
     , round(avg(share_user_tweets)::numeric, 3)              as avg_share_user_tweets
     , round(avg(share_user_nights)::numeric, 3)              as avg_share_user_nights
from revised.home_location
where night_window = '20-08'
group by method, city, res
order by method, city, res desc;


-- ------------------------------------------------------------
-- V2  Do the methods agree? (D10) Users with a 'ratio' home, i.e.
--     >= 20 tweets, 20-08. ratio_nights_kept = nights of the ratio
--     home / nights of the 'nights' home (1 = no loss).
-- ------------------------------------------------------------
select n.city
     , n.res
     , count(*)                                               as n_users
     , count(*) filter (where n.cell = r.cell)                as n_same_nights_ratio
     , count(*) filter (where n.cell = t.cell)                as n_same_nights_night_tweets
     , round(avg(r.d_night::numeric / n.d_night), 2)          as ratio_nights_kept
from revised.home_location n
join revised.home_location r
  on r.method = 'ratio' and r.night_window = n.night_window
 and r.city = n.city and r.user_id = n.user_id and r.res = n.res
join revised.home_location t
  on t.method = 'night_tweets' and t.night_window = n.night_window
 and t.city = n.city and t.user_id = n.user_id and t.res = n.res
where n.method = 'nights'
  and n.night_window = '20-08'
group by n.city, n.res
order by n.city, n.res desc;


-- ------------------------------------------------------------
-- V3  Users with homes in more than one city (D09), 'nights', 20-08
-- ------------------------------------------------------------
select res
     , count(*) filter (where is_primary)                                         as n_users
     , count(*) filter (where is_primary and n_home_cities > 1)                   as n_users_multi_city
     , count(*) filter (where is_primary and n_home_cities > 1
                          and confidence = 'high')                                as n_multi_city_primary_high
from revised.home_location
where method = 'nights'
  and night_window = '20-08'
group by res
order by res desc;


-- ------------------------------------------------------------
-- V4  Same home under both night windows? (D02), per method, res 10
-- ------------------------------------------------------------
select a.method
     , a.city
     , count(*)                                       as n_both
     , count(*) filter (where a.cell = b.cell)        as n_same_cell
     , round(avg((a.cell = b.cell)::int)::numeric, 3) as share_same
from revised.home_location a
join revised.home_location b
  on b.method = a.method and b.city = a.city and b.user_id = a.user_id and b.res = a.res
 and b.night_window = '22-07'
where a.night_window = '20-08'
  and a.res = 10
group by a.method, a.city
order by a.method, a.city;


-- ------------------------------------------------------------
-- V5  Inclusiveness: who gets a home, by activity ('nights', 20-08, res 9)
-- ------------------------------------------------------------
select u.city
     , case
           when u.n_all < 5  then '01-04'
           when u.n_all < 10 then '05-09'
           when u.n_all < 20 then '10-19'
           when u.n_all < 50 then '20-49'
           else '50+'
       end                                                    as tweets
     , count(*)                                               as n_users
     , count(h.user_id)                                       as n_homes
     , count(*) filter (where h.confidence = 'high')          as n_high
     , count(*) filter (where h.confidence = 'medium')        as n_medium
     , count(*) filter (where h.confidence = 'low')           as n_low
from revised.home_user u
left join revised.home_location h
  on h.city = u.city and h.user_id = u.user_id
 and h.method = 'nights' and h.night_window = '20-08' and h.res = 9
group by u.city, 2
order by u.city, 2;
