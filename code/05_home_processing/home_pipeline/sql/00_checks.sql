-- ============================================================
-- 00_checks.sql  --  preflight checks for the home pipeline
-- Target DB: twitter_cities_v2, schema: revised
--
-- READ-ONLY. Run each block separately. The results settle the open
-- items in DECISIONS.md.
--
-- C01 (settings, role), C03 (column types) and C04 (indexes, sizes) were
-- settled with 00a_inspect_revised.sql and are not repeated here.
-- h3 / postgis live in schema public, so h3 functions are called as
-- public.h3_... (the session search_path may be just `revised`).
--
-- Blocks marked [FULL SCAN] read most or all of revised.tweet
-- (167M rows, 59 GB with indexes): expect minutes, not seconds.
-- ============================================================


-- ------------------------------------------------------------
-- C02  h3 smoke test  (-> D14)
-- h3 is an "unreleased" build, so check the functions the pipeline uses.
-- point() takes (x, y) = (lon, lat).
-- parent_9 and direct_9 must be identical.
-- ------------------------------------------------------------
select public.h3_lat_lng_to_cell(point(4.9, 52.37), 10) as cell_10
     , public.h3_cell_to_parent(public.h3_lat_lng_to_cell(point(4.9, 52.37), 10), 9) as parent_9
     , public.h3_lat_lng_to_cell(point(4.9, 52.37), 9) as direct_9;


-- ------------------------------------------------------------
-- C05  Unit of place.err  (-> D07)
-- If err is in metres: city-level places (~20-30 km half diameter) have err
-- of ~10000-30000 and only POIs / small neighbourhoods pass err < 200.
-- If err is in km: nearly everything passes.
-- ------------------------------------------------------------
select place_type
     , count(*) as n_places
     , min(err) as err_min
     , percentile_cont(0.5) within group (order by err) as err_median
     , max(err) as err_max
     , count(*) filter (where err < 200) as n_err_lt_200
from revised.place
group by place_type
order by n_places desc;

-- Spot check: a few well known places by name.
select place_id, place_name, place_type, err
from revised.place
where place_name in ('Amsterdam', 'Portland', 'London', 'Greater London', 'Westminster')
order by place_name, err;


-- ------------------------------------------------------------
-- C06  Size of the home-detection input  (-> D04, D05, D07, D08)  [FULL SCAN]
-- Tweets in the 2013-2017 window inside the city bboxes, split by
-- coordinate source, using the legacy rule: gps if both coordinates exist,
-- else the place centroid when err < 200. Place tweets are split into
-- POIs (venue check-ins, err = 0) and other small places (see C05).
-- ------------------------------------------------------------
with bbox(city_bbox, lat_min, lat_max, lon_min, lon_max) as (
    values ('london',    51.2867601, 51.6918741,  -0.5103751,    0.3340155)
         , ('portland',  45.4325360, 45.6528812, -122.8367489, -122.4720252)
         , ('amsterdam', 52.2781742, 52.4310638,    4.7287776,    5.0791622)
)
, located as (
    select t.user_id
         , case when t.lat is not null and t.lon is not null then 'gps'
                when p.place_type = 'poi'                   then 'place_poi'
                else 'place_other'
           end as src
         , case when t.lat is not null and t.lon is not null then t.lat else p.centroid_lat end as lat
         , case when t.lat is not null and t.lon is not null then t.lon else p.centroid_lon end as lon
    from revised.tweet t
    left join revised.place p on p.place_id = t.place_id and p.err < 200
    where t.created_at >= timestamp '2013-01-01'
      and t.created_at <  timestamp '2018-01-01'
)
select b.city_bbox
     , l.src
     , count(*)                  as n_tweets
     , count(distinct l.user_id) as n_users
from located l
join bbox b
  on l.lat between b.lat_min and b.lat_max
 and l.lon between b.lon_min and b.lon_max
group by b.city_bbox, l.src
order by b.city_bbox, l.src;
-- Rows with neither gps nor a qualifying place centroid have NULL lat/lon
-- and drop out in the bbox join, as in the old pipeline.


-- ------------------------------------------------------------
-- C07  tweet_id uniqueness across cities  (-> D13 network join key)  [FULL SCAN]
-- PK is (city, tweet_id). A non-zero count means joins on tweet_id alone
-- fan out rows; the pipeline joins on (city, tweet_id) either way.
-- ------------------------------------------------------------
select count(*) as tweet_ids_in_more_than_one_city
from (
    select tweet_id
    from revised.tweet
    group by tweet_id
    having count(*) > 1
) x;


-- ------------------------------------------------------------
-- C08  Users appearing in more than one city  (-> D09 home scope)  [FULL SCAN]
-- 1% sample of users (user_id % 100 = 0).
-- ------------------------------------------------------------
select count(*) as sampled_users
     , count(*) filter (where n_cities > 1) as users_in_more_than_one_city
from (
    select user_id, count(distinct city) as n_cities
    from revised.tweet
    where user_id % 100 = 0
    group by user_id
) x;


-- ------------------------------------------------------------
-- C09  Tweet types in the window  (-> D11 which tweet types feed home)  [FULL SCAN]
-- Split by whether the tweet carries gps coordinates.
-- ------------------------------------------------------------
select tweet_type
     , count(*) as n
     , count(*) filter (where lat is not null and lon is not null) as n_with_gps
from revised.tweet
where created_at >= timestamp '2013-01-01'
  and created_at <  timestamp '2018-01-01'
group by tweet_type
order by n desc;


-- ------------------------------------------------------------
-- C10  Hour-of-day profile per city, UTC vs local  (-> D02, D03)  [FULL SCAN]
-- created_at is UTC stored as timestamp without time zone, so it is first
-- marked as UTC, then converted to the city's local clock (DST handled).
-- The night window (legacy 20:00-08:00) should sit on the low part of the
-- local curve.
-- ------------------------------------------------------------
with tz(city, tz_name) as (
    values ('london',    'Europe/London')
         , ('amsterdam', 'Europe/Amsterdam')
         , ('portland',  'America/Los_Angeles')
)
select t.city
     , extract(hour from (t.created_at at time zone 'UTC') at time zone tz.tz_name)::int as hour_local
     , count(*) as n_tweets
from revised.tweet t
join tz on tz.city = t.city
where t.created_at >= timestamp '2013-01-01'
  and t.created_at <  timestamp '2018-01-01'
group by 1, 2
order by 1, 2;
-- The UTC profile is the same query with extract(hour from t.created_at).
