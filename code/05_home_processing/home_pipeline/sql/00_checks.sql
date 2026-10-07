-- ============================================================
-- 00_checks.sql  --  preflight checks for the home pipeline
-- Target DB: twitter_cities_v2
--
-- READ-ONLY. Run each block separately (psql / DBeaver) and paste the
-- results back so we can settle the open items in DECISIONS.md.
-- Blocks marked [FULL SCAN] read the whole tweet table (164M rows):
-- expect minutes, not seconds.
-- ============================================================


-- ------------------------------------------------------------
-- C01  Server settings and role  (-> run settings for the pipeline)
-- ------------------------------------------------------------
select version();
select current_user as me
     , pg_has_role(current_user, 'twitter_project', 'member') as can_set_role_twitter_project
     , current_setting('TimeZone') as session_timezone;
select name, setting, unit
from pg_settings
where name in ('shared_buffers', 'work_mem', 'maintenance_work_mem'
             , 'max_parallel_workers_per_gather', 'max_parallel_workers'
             , 'max_worker_processes', 'effective_cache_size');


-- ------------------------------------------------------------
-- C02  Is h3 available?  (-> D14; the pipeline needs h3 functions)
-- ------------------------------------------------------------
select extname, extversion from pg_extension where extname in ('h3', 'h3_postgis', 'postgis');
select name, default_version, installed_version
from pg_available_extensions
where name like 'h3%';

-- Smoke test (fails with "function does not exist" if h3 is missing).
-- Note the old notebooks call h3_lat_lng_to_cell(point(lon, lat), res):
-- point() takes (x, y) = (lon, lat).
select h3_lat_lng_to_cell(point(4.9, 52.37), 10) as cell_10
     , h3_cell_to_parent(h3_lat_lng_to_cell(point(4.9, 52.37), 10), 9) as parent_9
     , h3_lat_lng_to_cell(point(4.9, 52.37), 9) as direct_9;
-- parent_9 and direct_9 must be identical.


-- ------------------------------------------------------------
-- C03  Column types  (-> D03 time zone, D06 coordinates)
-- created_at must be 'timestamp without time zone' (UTC by convention).
-- ------------------------------------------------------------
select table_name, column_name, data_type
from information_schema.columns
where table_schema = 'public'
  and ((table_name = 'tweet' and column_name in ('city', 'tweet_id', 'user_id', 'created_at', 'place_id', 'lat', 'lon', 'tweet_type'))
    or (table_name = 'place' and column_name in ('place_id', 'place_type', 'centroid_lat', 'centroid_lon', 'err'))
    or (table_name in ('mention_network', 'reply_network') and column_name in ('city', 'tweet_id', 'created_at')))
order by table_name, column_name;


-- ------------------------------------------------------------
-- C04  Indexes and physical order of tweet  (-> speed plan)
-- correlation near 1 or -1 = table is physically sorted by that column;
-- near 0 = scattered (range scans on that index are slow, seq scan wins).
-- Needs fresh stats: run `analyze tweet;` first if pg_stats is empty.
-- ------------------------------------------------------------
select indexname, indexdef
from pg_indexes
where schemaname = 'public' and tablename in ('tweet', 'place', 'mention_network', 'reply_network')
order by tablename, indexname;

select attname, n_distinct, correlation
from pg_stats
where schemaname = 'public' and tablename = 'tweet'
  and attname in ('city', 'tweet_id', 'user_id', 'created_at', 'place_id');

select relname
     , pg_size_pretty(pg_total_relation_size(oid)) as total_size
     , pg_size_pretty(pg_relation_size(oid)) as heap_size
     , reltuples::bigint as est_rows
from pg_class
where relname in ('tweet', 'place', 'mention_network', 'reply_network', 'twitter_user');


-- ------------------------------------------------------------
-- C05  Unit of place.err  (-> D07; docs say metres, notebooks say nothing)
-- If err is in metres: city-level places (~20-30 km half diameter) have err
-- of ~10000-30000 and only POIs/small neighbourhoods pass err < 200.
-- If err is in km: nearly everything passes. This shows which one it is.
-- ------------------------------------------------------------
select place_type
     , count(*) as n_places
     , min(err) as err_min
     , percentile_cont(0.5) within group (order by err) as err_median
     , max(err) as err_max
     , count(*) filter (where err < 200) as n_err_lt_200
from place
group by place_type
order by n_places desc;

-- Spot check: a few well known places by name.
select place_id, place_name, place_type, err
from place
where place_name in ('Amsterdam', 'Portland', 'London', 'Greater London', 'Westminster')
order by place_name, err;


-- ------------------------------------------------------------
-- C06  Size of the home-detection input  (-> D04, D05, D07, D08)
-- How many tweets fall into the 2013-2017 window, split by coordinate source,
-- using the same bbox as the old notebooks. Uses the (city, created_at) index.
-- ------------------------------------------------------------
with bbox(city_bbox, lat_min, lat_max, lon_min, lon_max) as (
    values ('london',    51.2867601, 51.6918741,  -0.5103751,    0.3340155)
         , ('portland',  45.4325360, 45.6528812, -122.8367489, -122.4720252)
         , ('amsterdam', 52.2781742, 52.4310638,    4.7287776,    5.0791622)
)
, located as (
    -- same rule as the old tweet_places: gps if both coordinates exist,
    -- else the place centroid when err < 200
    select t.user_id
         , case when t.lat is not null and t.lon is not null then 'gps' else 'place_centroid' end as src
         , case when t.lat is not null and t.lon is not null then t.lat else p.centroid_lat end as lat
         , case when t.lat is not null and t.lon is not null then t.lon else p.centroid_lon end as lon
    from tweet t
    left join place p on p.place_id = t.place_id and p.err < 200
    where t.created_at >= timestamp '2013-01-01'
      and t.created_at <  timestamp '2018-01-01'
)
select b.city_bbox
     , l.src
     , count(*)                as n_tweets
     , count(distinct l.user_id) as n_users
from located l
join bbox b
  on l.lat between b.lat_min and b.lat_max
 and l.lon between b.lon_min and b.lon_max
group by b.city_bbox, l.src
order by b.city_bbox, l.src;
-- Rows where neither gps nor a qualifying place centroid exists have NULL
-- lat/lon and drop out in the bbox join, as in the old pipeline.


-- ------------------------------------------------------------
-- C07  tweet_id uniqueness across cities  (-> D13 network join key)
-- PK is (city, tweet_id). If the same tweet_id occurs in two cities,
-- joining mention_network/reply_network to tweet on tweet_id alone
-- fans out rows. [FULL SCAN]
-- ------------------------------------------------------------
select count(*) as tweet_ids_in_more_than_one_city
from (
    select tweet_id
    from tweet
    group by tweet_id
    having count(*) > 1
) x;


-- ------------------------------------------------------------
-- C08  Users appearing in more than one city  (-> D09 home scope)
-- Sample of ~1% of users (user_id % 100 = 0); still a full scan. [FULL SCAN]
-- ------------------------------------------------------------
select count(*) as sampled_users
     , count(*) filter (where n_cities > 1) as users_in_more_than_one_city
from (
    select user_id, count(distinct city) as n_cities
    from tweet
    where user_id % 100 = 0
    group by user_id
) x;


-- ------------------------------------------------------------
-- C09  Tweet types in the window  (-> D11 which tweet types feed home)
-- ------------------------------------------------------------
select tweet_type, count(*) as n
from tweet
where created_at >= timestamp '2013-01-01'
  and created_at <  timestamp '2018-01-01'
group by tweet_type
order by n desc;
