-- ============================================================
-- 01_home_input.sql  --  slim input table for home detection
-- Target DB: twitter_cities_v2, schema: revised
--
-- One pass over revised.tweet -> revised.home_input (UNLOGGED),
-- one row per tweet that can feed home detection:
--   D04  2013-01-01 <= created_at < 2018-01-01
--   D07  gps coordinates only (no place centroids)
--   D08  inside the bbox of the tweet's own city label
--   D11  tweet_type in (original, reply, quote); retweets dropped
--   D03  local time per city (created_at is UTC)
--   D14  H3 res 10 only; res 9 / 8 are derived later via h3_cell_to_parent
--
-- Night window (D02), minimum activity (D05) and ranking (D10) are NOT
-- applied here, so every sensitivity run reuses this table.
--
-- Expected: ~43.6M rows (C06 minus retweets), ~3-4 GB, about 5-15 min.
-- Drops and recreates revised.home_input. Nothing else is touched.
-- ============================================================


-- ------------------------------------------------------------
-- S1  Session settings (shared server: modest values)
-- ------------------------------------------------------------
set work_mem = '256MB';
set max_parallel_workers_per_gather = 4;


-- ------------------------------------------------------------
-- S2  Build revised.home_input
-- point() takes (x, y) = (lon, lat).
-- ------------------------------------------------------------
set role twitter_project;

drop table if exists revised.home_input;

create unlogged table revised.home_input as
with bbox(city, tz, lat_min, lat_max, lon_min, lon_max) as (
    values ('london',    'Europe/London',       51.2867601, 51.6918741,  -0.5103751,    0.3340155)
         , ('portland',  'America/Los_Angeles', 45.4325360, 45.6528812, -122.8367489, -122.4720252)
         , ('amsterdam', 'Europe/Amsterdam',    52.2781742, 52.4310638,    4.7287776,    5.0791622)
)
, located as (
    select t.city
         , t.tweet_id
         , t.user_id
         , (t.created_at at time zone 'UTC') at time zone b.tz as created_local
         , public.h3_latlng_to_cell(point(t.lon, t.lat), 10)  as cell_10
    from revised.tweet t
    join bbox b
      on b.city = t.city
     and t.lat between b.lat_min and b.lat_max
     and t.lon between b.lon_min and b.lon_max
    where t.created_at >= timestamp '2013-01-01'
      and t.created_at <  timestamp '2018-01-01'
      and t.tweet_type in ('original', 'reply', 'quote')
)
select city
     , tweet_id
     , user_id
     , created_local
     , extract(hour from created_local)::smallint as local_hour
     , cell_10
from located;

alter table revised.home_input add primary key (city, tweet_id);

reset role;

analyze revised.home_input;

reset work_mem;
reset max_parallel_workers_per_gather;


-- ------------------------------------------------------------
-- V1  Size per city (compare with C06: ams 3,191,990 / 238,514;
--     lon 35,960,332 / 963,010; pdx 4,528,967 / 112,710, minus retweets)
--     and users that would pass D05 (>= 20 tweets in the city).
-- ------------------------------------------------------------
select city
     , count(*)                                   as n_tweets
     , count(distinct user_id)                    as n_users
     , count(*) filter (where cell_10 is null)    as n_cell_null
     , min(created_local)                         as first_local
     , max(created_local)                         as last_local
from revised.home_input
group by city
order by city;

select city
     , count(*)                                   as n_users
     , count(*) filter (where n >= 20)            as n_users_20plus
     , sum(n) filter (where n >= 20)              as n_tweets_of_20plus
from (
    select city, user_id, count(*) as n
    from revised.home_input
    group by city, user_id
) u
group by city
order by city;


-- ------------------------------------------------------------
-- V2  Table size on disk
-- ------------------------------------------------------------
select pg_size_pretty(pg_table_size('revised.home_input'))          as table_size
     , pg_size_pretty(pg_indexes_size('revised.home_input'))        as index_size;
