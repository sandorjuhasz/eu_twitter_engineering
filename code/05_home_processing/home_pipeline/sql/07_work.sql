-- ============================================================
-- 07_work.sql  --  stays of home users, home area and work place
-- Target DB: twitter_cities_v2, schema: revised
--
-- Base for the visits table (08) and a minimal work label (D19, D20).
-- Only users with a home (revised.home_final, any res).
--
-- S2a  revised.tweet -> revised.visit_stay
--        one row per (city, user_id, local_date, cell_10): a stay.
--        Filters as 01 S2b (2013-17, gps, own-city bbox, original /
--        reply / quote, local time) EXCEPT D18: shared points are KEPT
--        (check-in venues are third-place visits); only generic city
--        points are dropped: shared points (>= 100 users) within ~30 m
--        of a city default coordinate in `generic_points` (catches the
--        variants different apps use). max_point_users flags shared
--        points.
-- S2b  revised.home_final -> revised.visit_home_area
--        res 10 cells counted as home: the res 10 home cell and its
--        ring 1 (~200 m, GPS jitter around home); users with only a
--        res 9 home: the 7 res 10 children of that cell
--      visit_stay -> revised.work_final
--        work = the cell outside the home area with the most distinct
--        Mon-Fri dates with a tweet at 09-16h local, if it has >= 3
--        such dates and strictly more than any other cell. Nothing
--        else (no tiers, no res 9): most users get no work row, and
--        that is fine.
--
-- V0 lists the largest shared points; the generic_points list in
-- S2a was taken from it (2026-11-13).
-- S2a reads revised.tweet once: about 10-30 min (psql in tmux).
-- Drops and recreates revised.visit_stay, revised.visit_home_area and
-- revised.work_final. Nothing else is touched.
-- ============================================================


-- ------------------------------------------------------------
-- S1  Session settings (shared server: modest values)
--     public on the path for the h3index operators (D14).
-- ------------------------------------------------------------
set work_mem = '256MB';
set max_parallel_workers_per_gather = 4;
set search_path = revised, public;


-- ------------------------------------------------------------
-- V0  Largest shared points per city (fast: small table). Generic
--     city points (no venue: the city's default coordinate) go into
--     generic_points in S2a; airports, stations, venues stay.
-- ------------------------------------------------------------
select city, lat, lon, n_users, n_tweets
from (
    select s.*
         , row_number() over (partition by city order by n_users desc) as rk
    from revised.home_shared_points s
) x
where rk <= 10
order by city, rk;

-- V0b Shared points that S2a drops (>= 100 users, ~30 m around a
--     generic centre): should be the defaults and their variants only
with generic_points(city, lat, lon) as (
    values ('london', 51.507114, -0.127318), ('london', 51.507198, -0.127500)
         , ('amsterdam', 52.373100, 4.892200), ('portland', 45.520000, -122.682000)
)
select distinct s.city, s.lat, s.lon, s.n_users, s.n_tweets
from revised.home_shared_points s
join generic_points g
  on g.city = s.city
 and abs(s.lat - g.lat) < 0.0003
 and abs(s.lon - g.lon) < 0.0004
where s.n_users >= 100
order by s.city, s.n_users desc;


-- ------------------------------------------------------------
-- S2a  Build revised.visit_stay
-- point() takes (x, y) = (lon, lat).
-- ------------------------------------------------------------
set role twitter_project;

drop table if exists revised.visit_stay;

create table revised.visit_stay as
with generic_points(city, lat, lon) as (
    -- city-level default coordinates from V0 (2026-11-13); venues,
    -- landmarks, stations, airports and neighbourhood points (Soho,
    -- Shoreditch) stay. Dropped: shared points (>= min_point_users)
    -- within 0.0003 deg lat / 0.0004 deg lon (~30 m) of a centre, so
    -- the variants of the same default (51.507195 / 51.507221 ...,
    -- float32 storage) go too; private GPS fixes there stay.
    values ('london',    51.507114,   -0.127318)    -- generic London
         , ('london',    51.507198,   -0.127500)    -- generic London (Wikipedia)
         , ('amsterdam', 52.373100,    4.892200)    -- generic Amsterdam
         , ('portland',  45.520000, -122.682000)    -- generic Portland
)
, params(min_point_users, d_lat, d_lon) as (
    values (100, 0.0003, 0.0004)
)
, bbox(city, tz, lat_min, lat_max, lon_min, lon_max) as (
    values ('london',    'Europe/London',       51.2867601, 51.6918741,  -0.5103751,    0.3340155)
         , ('portland',  'America/Los_Angeles', 45.4325360, 45.6528812, -122.8367489, -122.4720252)
         , ('amsterdam', 'Europe/Amsterdam',    52.2781742, 52.4310638,    4.7287776,    5.0791622)
)
, home_user as (
    select distinct city, user_id
    from revised.home_final
)
, located as (
    select t.city
         , t.user_id
         , (t.created_at at time zone 'UTC') at time zone b.tz as created_local
         , public.h3_latlng_to_cell(point(t.lon, t.lat), 10)  as cell_10
         , s.n_users                                           as point_users
    from revised.tweet t
    join home_user u
      on u.city = t.city
     and u.user_id = t.user_id
    join bbox b
      on b.city = t.city
     and t.lat between b.lat_min and b.lat_max
     and t.lon between b.lon_min and b.lon_max
    left join revised.home_shared_points s
      on s.city = t.city
     and s.lat = t.lat
     and s.lon = t.lon
    where t.created_at >= timestamp '2013-01-01'
      and t.created_at <  timestamp '2018-01-01'
      and t.tweet_type in ('original', 'reply', 'quote')
      and not (
              coalesce(s.n_users, 0) >= (select min_point_users from params)
          and exists (
                  select 1
                  from generic_points g
                  cross join params p
                  where g.city = t.city
                    and abs(t.lat - g.lat) < p.d_lat
                    and abs(t.lon - g.lon) < p.d_lon
              )
      )
)
select city
     , user_id
     , created_local::date                                               as local_date
     , extract(isodow from created_local::date)::smallint                as dow
     , cell_10
     , count(*)                                                          as n_tweets
     , count(*) filter (where extract(hour from created_local) between 9 and 16) as n_daytime
     , min(created_local)                                                as first_local
     , max(created_local)                                                as last_local
     , max(point_users)                                                  as max_point_users
from located
group by city, user_id, created_local::date, cell_10;

alter table revised.visit_stay add primary key (city, user_id, local_date, cell_10);

reset role;

analyze revised.visit_stay;


-- ------------------------------------------------------------
-- S2b  Build revised.visit_home_area and revised.work_final
-- ------------------------------------------------------------
set role twitter_project;

drop table if exists revised.visit_home_area;

create table revised.visit_home_area as
select h.city, h.user_id, public.h3_grid_disk(h.cell, 1) as cell_10
from revised.home_final h
where h.res = 10
union
select h.city, h.user_id, public.h3_cell_to_children(h.cell, 10)
from revised.home_final h
where h.res = 9
  and not exists (
      select 1
      from revised.home_final h10
      where h10.city = h.city
        and h10.user_id = h.user_id
        and h10.res = 10
  );

alter table revised.visit_home_area add primary key (city, user_id, cell_10);

drop table if exists revised.work_final;

create table revised.work_final as
with params(min_work_days) as (
    values (3)
)
, cell_days as (
    select s.city
         , s.user_id
         , s.cell_10
         , count(distinct s.local_date) as d_work_days
    from revised.visit_stay s
    where s.dow between 1 and 5
      and s.n_daytime > 0
      and not exists (
          select 1
          from revised.visit_home_area a
          where a.city = s.city
            and a.user_id = s.user_id
            and a.cell_10 = s.cell_10
      )
    group by s.city, s.user_id, s.cell_10
)
, ranked as (
    select c.*
         , row_number() over (partition by city, user_id order by d_work_days desc, cell_10) as rk
         , lead(d_work_days) over (partition by city, user_id order by d_work_days desc, cell_10) as d_second_days
    from cell_days c
)
, home as (
    -- res 10 home if there is one, else the res 9 home
    select distinct on (city, user_id) city, user_id, cell
    from revised.home_final
    order by city, user_id, res desc
)
select r.city
     , r.user_id
     , r.cell_10                                                          as cell
     , r.d_work_days
     , r.d_second_days
     , round(public.st_distancesphere(public.h3_cell_to_geometry(r.cell_10),
                                      public.h3_cell_to_geometry(h.cell)))::integer as dist_home_m
from ranked r
join home h
  on h.city = r.city
 and h.user_id = r.user_id
cross join params p
where r.rk = 1
  and r.d_work_days >= p.min_work_days
  and r.d_work_days > coalesce(r.d_second_days, 0);

alter table revised.work_final add primary key (city, user_id);

reset role;

analyze revised.visit_home_area;
analyze revised.work_final;

reset work_mem;
reset max_parallel_workers_per_gather;


-- ------------------------------------------------------------
-- V1  Stays, work places and commute distance per city.
--     Tweets in visit_stay should exceed home_input tweets of the same
--     users (the difference is the kept shared points).
-- ------------------------------------------------------------
select s.city
     , count(*)                                                         as n_stays
     , sum(s.n_tweets)                                                  as n_tweets
     , sum(s.n_tweets) filter (where s.max_point_users >= 100)          as n_tweets_shared_100
     , count(distinct s.user_id)                                        as n_users
from revised.visit_stay s
group by s.city
order by s.city;

select u.city
     , count(*)                                                         as n_home_users
     , count(w.user_id)                                                 as n_work
     , round(avg((w.user_id is not null)::int)::numeric, 3)             as share_work
     , count(*) filter (where w.dist_home_m <  1000)                    as n_lt_1km
     , count(*) filter (where w.dist_home_m >= 1000 and w.dist_home_m < 5000) as n_1_5km
     , count(*) filter (where w.dist_home_m >= 5000)                    as n_5km_plus
     , percentile_cont(0.5) within group (order by w.d_work_days)       as median_work_days
from (select distinct city, user_id from revised.home_final) u
left join revised.work_final w
  on w.city = u.city
 and w.user_id = u.user_id
group by u.city
order by u.city;

-- Top 5 work cells per city: expect business districts, universities,
-- stations, airports
select city, cell, n_users, lat, lon
from (
    select city
         , cell
         , count(*)                                                     as n_users
         , round(public.st_y(public.h3_cell_to_geometry(cell))::numeric, 5) as lat
         , round(public.st_x(public.h3_cell_to_geometry(cell))::numeric, 5) as lon
         , row_number() over (partition by city order by count(*) desc) as rk
    from revised.work_final
    group by city, cell
) x
where rk <= 5
order by city, rk;

-- Generic points gone: the cells of the generic centres must show
-- max_point_users below the generic counts (75,534 / 20,561 / 41,456 /
-- 13,485); Soho (16,508) stays by design
select city, cell_10::text, count(*) as n_stays, max(max_point_users) as max_point_users
from revised.visit_stay
where (city, cell_10) in (('portland',  '8a28f0004b67fff'::h3index),
                          ('london',    '8a195da49b5ffff'::h3index),
                          ('london',    '8a195da49847fff'::h3index))
group by 1, 2;
