-- ============================================================
-- 05_diagnostics.sql  --  how far can we trust the homes?
-- Target DB: twitter_cities_v2, schema: revised
--
-- No ground truth, so accuracy is judged by consistency (D16):
--   temporal stability  detect a home separately in 2013-2015 and in
--                       2016-2017 (local time); the share of users who
--                       keep the same cell, by night evidence, activity
--                       and tier. Real moves lower it, so it is a lower
--                       bound on accuracy; we look for where it levels
--                       off to set min_home_nights / min_user_tweets /
--                       high_min_nights.
--   nesting             res 10 home inside the res 9 / 8 home
--   multi-city / bots   who has homes in two cities; tweets per day
--
-- Period homes use the 'nights' ranking (D10, D15) and the 20-08
-- window, with NO gate (any cell with a night tweet), so the V queries
-- can apply any gate afterwards. Res 10 and 9 only.
--
-- S2a  revised.home_input -> revised.home_diag_period_cell (UNLOGGED)
-- S2c  adds an interleaved split (alternate weeks wk-a / wk-b) to
--         home_diag_period_cell: reliability without moves (V8)
-- S2b  -> revised.home_diag_period_home (UNLOGGED), best cell per
--         (period, city, user, res)
-- Reads home_input once with distinct counts: expect 10-20 min for S2a.
-- Drops and recreates the two home_diag_ tables. Nothing else is touched.
-- ============================================================


-- ------------------------------------------------------------
-- S1  Session settings (shared server: modest values)
--     public on the path for the h3index operators (D14).
-- ------------------------------------------------------------
set work_mem = '256MB';
set max_parallel_workers_per_gather = 4;
set search_path = revised, public;


-- ------------------------------------------------------------
-- S2a  Counts per period, user, res and cell
-- ------------------------------------------------------------
set role twitter_project;

drop table if exists revised.home_diag_period_cell;

create unlogged table revised.home_diag_period_cell as
with t as (
    select city
         , user_id
         , case when created_local < timestamp '2016-01-01' then '2013-15' else '2016-17' end as period
         , cell_10
         , case when local_hour >= 20 or local_hour < 8
                then (created_local - interval '8 hours')::date
           end as night_date
    from revised.home_input
)
select t.period
     , t.city
     , t.user_id
     , r.res
     , r.cell
     , count(*)                       as n_all
     , count(t.night_date)            as n_night
     , count(distinct t.night_date)   as d_night
from t
cross join lateral (
    values (10::smallint, t.cell_10)
         , (9::smallint,  public.h3_cell_to_parent(t.cell_10, 9))
) r(res, cell)
group by t.period, t.city, t.user_id, r.res, r.cell;

alter table revised.home_diag_period_cell add primary key (period, city, user_id, res, cell);

reset role;

analyze revised.home_diag_period_cell;


-- ------------------------------------------------------------
-- S2c  Interleaved split: alternate calendar weeks (Mon-Sun) go to
--      'wk-a' / 'wk-b'. Both halves span 2013-17, so moving house
--      cannot make them differ: agreement here measures the method's
--      reliability, the gap to the period split measures moves.
--      A night belongs to the week of its night date. Adds rows to
--      home_diag_period_cell (re-runnable); rerun S2b afterwards.
--      Reads home_input once: expect about as long as S2a.
-- ------------------------------------------------------------
set role twitter_project;

delete from revised.home_diag_period_cell where period in ('wk-a', 'wk-b');

insert into revised.home_diag_period_cell
with t as (
    select city
         , user_id
         , cell_10
         , case when local_hour >= 20 or local_hour < 8
                then (created_local - interval '8 hours')::date
           end as night_date
         , created_local::date as day_date
    from revised.home_input
)
select case when ((coalesce(t.night_date, t.day_date) - date '2012-12-31') / 7) % 2 = 0
            then 'wk-a' else 'wk-b' end   as period
     , t.city
     , t.user_id
     , r.res
     , r.cell
     , count(*)                       as n_all
     , count(t.night_date)            as n_night
     , count(distinct t.night_date)   as d_night
from t
cross join lateral (
    values (10::smallint, t.cell_10)
         , (9::smallint,  public.h3_cell_to_parent(t.cell_10, 9))
) r(res, cell)
group by 1, t.city, t.user_id, r.res, r.cell;

reset role;

analyze revised.home_diag_period_cell;


-- ------------------------------------------------------------
-- S2b  Best cell per period, city, user and res ('nights', no gate)
-- ------------------------------------------------------------
set role twitter_project;

drop table if exists revised.home_diag_period_home;

create unlogged table revised.home_diag_period_home as
with ranked as (
    select c.*
         , row_number() over w                                            as rk
         , lead(d_night) over w                                           as d_night_second
         , sum(n_all) over (partition by period, city, user_id, res)      as n_user_all
    from revised.home_diag_period_cell c
    window w as (
        partition by period, city, user_id, res
        order by d_night desc, n_night desc, n_all desc, cell
    )
)
select period
     , city
     , user_id
     , res
     , cell
     , d_night
     , n_night
     , n_all
     , n_user_all::bigint                                as n_user_all
     , d_night > coalesce(d_night_second, 0)             as strict_lead
from ranked
where rk = 1
  and d_night >= 1;

alter table revised.home_diag_period_home add primary key (period, city, user_id, res);

reset role;

analyze revised.home_diag_period_home;

reset work_mem;
reset max_parallel_workers_per_gather;


-- ------------------------------------------------------------
-- V1  Stability by night evidence. Users with a period home in both
--     periods; evidence = the weaker of the two periods. Columns:
--     all users, and users passing the gate in both periods
--     (strict lead, >= 10 tweets) -> where does share_same level off?
-- ------------------------------------------------------------
with pair as (
    select a.city
         , a.res
         , least(a.d_night, b.d_night)                                    as d_min
         , a.cell = b.cell                                                as same
         , a.strict_lead and b.strict_lead
           and a.n_user_all >= 10 and b.n_user_all >= 10                  as gated
    from revised.home_diag_period_home a
    join revised.home_diag_period_home b
      on b.city = a.city and b.user_id = a.user_id and b.res = a.res
     and b.period = '2016-17'
    where a.period = '2013-15'
)
select city
     , res
     , case
           when d_min = 1  then '1'
           when d_min = 2  then '2'
           when d_min <= 4 then '3-4'
           when d_min <= 9 then '5-9'
           else '10+'
       end                                                                as nights_min
     , count(*)                                                           as n_users
     , round(avg(same::int)::numeric, 3)                                  as share_same
     , count(*) filter (where gated)                                      as n_gated
     , round(avg(same::int) filter (where gated)::numeric, 3)             as share_same_gated
from pair
group by city, res, 3
order by city, res desc, 3;


-- ------------------------------------------------------------
-- V2  Stability by activity: user tweets in the weaker period,
--     gated pairs with >= 3 nights in both periods.
-- ------------------------------------------------------------
with pair as (
    select a.city
         , a.res
         , least(a.n_user_all, b.n_user_all)   as n_min
         , a.cell = b.cell                     as same
    from revised.home_diag_period_home a
    join revised.home_diag_period_home b
      on b.city = a.city and b.user_id = a.user_id and b.res = a.res
     and b.period = '2016-17'
    where a.period = '2013-15'
      and a.strict_lead and b.strict_lead
      and a.d_night >= 3 and b.d_night >= 3
)
select city
     , res
     , case
           when n_min < 10 then '01-09'
           when n_min < 20 then '10-19'
           when n_min < 50 then '20-49'
           else '50+'
       end                                     as tweets_min
     , count(*)                                as n_users
     , round(avg(same::int)::numeric, 3)       as share_same
from pair
group by city, res, 3
order by city, res desc, 3;


-- ------------------------------------------------------------
-- V2b V2 on the week split (S2c): does reliability itself fall with
--     activity, or only period stability (heavy users move / have
--     more night places over time)? Res 10, period next to weeks.
-- ------------------------------------------------------------
with pair as (
    select case when a.period = '2013-15' then 'period' else 'weeks' end as split
         , a.city
         , least(a.n_user_all, b.n_user_all)   as n_min
         , a.cell = b.cell                     as same
    from revised.home_diag_period_home a
    join revised.home_diag_period_home b
      on b.city = a.city and b.user_id = a.user_id and b.res = a.res
     and b.period = case a.period when '2013-15' then '2016-17' else 'wk-b' end
    where a.period in ('2013-15', 'wk-a')
      and a.res = 10
      and a.strict_lead and b.strict_lead
      and a.d_night >= 3 and b.d_night >= 3
)
select city
     , case
           when n_min < 10 then '01-09'
           when n_min < 20 then '10-19'
           when n_min < 50 then '20-49'
           else '50+'
       end                                                         as tweets_min
     , count(*) filter (where split = 'period')                    as n_period
     , round(avg(same::int) filter (where split = 'period')::numeric, 3) as share_period
     , count(*) filter (where split = 'weeks')                     as n_weeks
     , round(avg(same::int) filter (where split = 'weeks')::numeric, 3)  as share_weeks
from pair
group by city, 2
order by city, 2;


-- ------------------------------------------------------------
-- V3  Stability by tier of the full-period home (03, 'nights', 20-08):
--     does 'high' mean more stable? Also: does the full-period home
--     equal the 2016-17 home (the more recent place)?
-- ------------------------------------------------------------
select h.city
     , h.res
     , h.confidence
     , count(*)                                                       as n_homes
     , count(a.user_id) filter (where b.user_id is not null)          as n_both_periods
     , round(avg((a.cell = b.cell)::int)::numeric, 3)                 as share_same_periods
     , round(avg((h.cell = b.cell)::int)::numeric, 3)                 as share_full_eq_2016_17
from revised.home_location h
left join revised.home_diag_period_home a
  on a.city = h.city and a.user_id = h.user_id and a.res = h.res and a.period = '2013-15'
left join revised.home_diag_period_home b
  on b.city = h.city and b.user_id = h.user_id and b.res = h.res and b.period = '2016-17'
where h.method = 'nights'
  and h.night_window = '20-08'
  and h.res in (10, 9)
group by h.city, h.res, h.confidence
order by h.city, h.res desc, h.confidence;


-- ------------------------------------------------------------
-- V4  Nesting: is the res 10 home inside the res 9 / res 8 home?
--     ('nights', 20-08, users with a home at all three res)
-- ------------------------------------------------------------
select h10.city
     , count(*)                                                                        as n_users
     , round(avg((public.h3_cell_to_parent(h10.cell, 9) = h9.cell)::int)::numeric, 3)  as share_10_in_9
     , round(avg((public.h3_cell_to_parent(h10.cell, 8) = h8.cell)::int)::numeric, 3)  as share_10_in_8
from revised.home_location h10
join revised.home_location h9
  on h9.method = h10.method and h9.night_window = h10.night_window
 and h9.city = h10.city and h9.user_id = h10.user_id and h9.res = 9
join revised.home_location h8
  on h8.method = h10.method and h8.night_window = h10.night_window
 and h8.city = h10.city and h8.user_id = h10.user_id and h8.res = 8
where h10.method = 'nights'
  and h10.night_window = '20-08'
  and h10.res = 10
group by h10.city
order by h10.city;


-- ------------------------------------------------------------
-- V5  Users with homes in more than one city ('nights', 20-08, res 9)
-- ------------------------------------------------------------
with multi as (
    select user_id
         , string_agg(city, ' + ' order by city)          as cities
         , sum(n_user_all)                                as n_tweets
         , sum(d_user_night)                              as d_nights
         , bool_and(confidence = 'high')                  as all_high
    from revised.home_location
    where method = 'nights'
      and night_window = '20-08'
      and res = 9
      and n_home_cities > 1
    group by user_id
)
select cities
     , count(*)                                           as n_users
     , count(*) filter (where all_high)                   as n_all_high
     , percentile_disc(0.5) within group (order by n_tweets)  as median_tweets
     , percentile_disc(0.5) within group (order by d_nights)  as median_nights
from multi
group by cities
order by n_users desc;


-- ------------------------------------------------------------
-- V6  Possible bots: tweets per active day of users with a home
--     ('nights', 20-08, res 9)
-- ------------------------------------------------------------
select h.city
     , case
           when u.n_all::numeric / u.d_active < 2  then '0-2'
           when u.n_all::numeric / u.d_active < 5  then '2-5'
           when u.n_all::numeric / u.d_active < 20 then '5-20'
           else '20+'
       end                                                    as tweets_per_day
     , count(*)                                               as n_homes
     , count(*) filter (where h.confidence = 'high')          as n_high
     , round(avg(h.share_user_tweets)::numeric, 3)            as avg_share_user_tweets
from revised.home_location h
join revised.home_user u
  on u.city = h.city and u.user_id = h.user_id
where h.method = 'nights'
  and h.night_window = '20-08'
  and h.res = 9
group by h.city, 2
order by h.city, 2;


-- ------------------------------------------------------------
-- V7  When the two period homes differ, how far apart are they?
--     Gated pairs (>= 3 nights, strict lead, >= 10 tweets in both
--     periods). Next door (< 300 m) points to GPS jitter / cell
--     borders; several km points to moves (or a partner's home).
-- ------------------------------------------------------------
with pair as (
    select a.city
         , a.res
         , case when a.cell = b.cell then 0
                else public.st_distancesphere(public.h3_cell_to_geometry(a.cell),
                                              public.h3_cell_to_geometry(b.cell))
           end as dist_m
    from revised.home_diag_period_home a
    join revised.home_diag_period_home b
      on b.city = a.city and b.user_id = a.user_id and b.res = a.res
     and b.period = '2016-17'
    where a.period = '2013-15'
      and a.strict_lead and b.strict_lead
      and a.d_night >= 3 and b.d_night >= 3
      and a.n_user_all >= 10 and b.n_user_all >= 10
)
select city
     , res
     , count(*)                                                       as n_users
     , round(avg((dist_m = 0)::int)::numeric, 3)                      as share_same
     , round(avg((dist_m > 0 and dist_m < 300)::int)::numeric, 3)     as share_lt_300m
     , round(avg((dist_m >= 300 and dist_m < 1000)::int)::numeric, 3) as share_300m_1km
     , round(avg((dist_m >= 1000 and dist_m < 5000)::int)::numeric, 3) as share_1_5km
     , round(avg((dist_m >= 5000)::int)::numeric, 3)                  as share_5km_plus
from pair
group by city, res
order by city, res desc;


-- ------------------------------------------------------------
-- V8  Reliability vs moves: period split (2013-15 / 2016-17) next to
--     the interleaved week split (wk-a / wk-b). Gated pairs as in V7
--     (>= 3 nights, strict lead, >= 10 tweets in both halves).
--     Needs S2c + S2b.
-- ------------------------------------------------------------
with pair as (
    select case when a.period = '2013-15' then 'period' else 'weeks' end as split
         , a.city
         , a.res
         , least(a.d_night, b.d_night)                                    as d_min
         , case when a.cell = b.cell then 0
                else public.st_distancesphere(public.h3_cell_to_geometry(a.cell),
                                              public.h3_cell_to_geometry(b.cell))
           end                                                            as dist_m
    from revised.home_diag_period_home a
    join revised.home_diag_period_home b
      on b.city = a.city and b.user_id = a.user_id and b.res = a.res
     and b.period = case a.period when '2013-15' then '2016-17' else 'wk-b' end
    where a.period in ('2013-15', 'wk-a')
      and a.strict_lead and b.strict_lead
      and a.d_night >= 3 and b.d_night >= 3
      and a.n_user_all >= 10 and b.n_user_all >= 10
)
select city
     , res
     , split
     , count(*)                                                           as n_users
     , round(avg((dist_m = 0)::int)::numeric, 3)                          as share_same
     , round(avg((dist_m > 0 and dist_m < 1000)::int)::numeric, 3)        as share_lt_1km
     , round(avg((dist_m >= 1000)::int)::numeric, 3)                      as share_1km_plus
     , round(avg((dist_m = 0)::int) filter (where d_min >= 5)::numeric, 3) as share_same_5n
     , round(avg((dist_m = 0)::int) filter (where d_min >= 10)::numeric, 3) as share_same_10n
from pair
group by city, res, split
order by city, res desc, split;
