-- ============================================================
-- 08_visits.sql  --  third-place visits of home users
-- Target DB: twitter_cities_v2, schema: revised
--
-- revised.visit: every stay (city, user_id, local_date, cell_10) of a
-- user with a home that is NOT in the home area (home cell + ring 1,
-- 07 S2b) and NOT in the work cell (07 work_final, no ring). With
-- sparse Twitter activity any such place is a potential third place
-- (D20). Home cell, income etc. come by join on (city, user_id) to
-- revised.home_final; res 9 via public.h3_cell_to_parent(cell_10, 9).
--
-- Needs 07 S2a + S2b.
-- Small input (visit_stay): expect a few minutes.
-- Drops and recreates revised.visit. Nothing else is touched.
-- ============================================================


-- ------------------------------------------------------------
-- S1  Session settings (shared server: modest values)
--     public on the path for the h3index operators (D14).
-- ------------------------------------------------------------
set work_mem = '256MB';
set max_parallel_workers_per_gather = 4;
set search_path = revised, public;


-- ------------------------------------------------------------
-- S2  Build revised.visit
-- ------------------------------------------------------------
set role twitter_project;

drop table if exists revised.visit;

create table revised.visit as
with home as (
    -- res 10 home if there is one, else the res 9 home
    select distinct on (city, user_id) city, user_id, cell
    from revised.home_final
    order by city, user_id, res desc
)
select s.city
     , s.user_id
     , s.local_date
     , s.dow
     , s.cell_10
     , s.n_tweets
     , s.first_local
     , s.last_local
     , s.max_point_users
     , round(public.st_distancesphere(public.h3_cell_to_geometry(s.cell_10),
                                      public.h3_cell_to_geometry(h.cell)))::integer as dist_home_m
from revised.visit_stay s
join home h
  on h.city = s.city
 and h.user_id = s.user_id
where not exists (
          select 1
          from revised.visit_home_area a
          where a.city = s.city
            and a.user_id = s.user_id
            and a.cell_10 = s.cell_10
      )
  and not exists (
          select 1
          from revised.work_final w
          where w.city = s.city
            and w.user_id = s.user_id
            and w.cell = s.cell_10
      );

alter table revised.visit add primary key (city, user_id, local_date, cell_10);
create index visit_city_cell_idx on revised.visit (city, cell_10);

reset role;

analyze revised.visit;

reset work_mem;
reset max_parallel_workers_per_gather;


-- ------------------------------------------------------------
-- V1  Size per city, and how much of each user's stays the home and
--     work exclusions remove. Users with no visit at all have every
--     stay at home / work.
-- ------------------------------------------------------------
select s.city
     , count(*)                                                         as n_stays
     , count(v.user_id)                                                 as n_visits
     , round(avg((v.user_id is null)::int)::numeric, 3)                 as share_removed
     , count(distinct s.user_id)                                        as n_users
     , count(distinct v.user_id)                                        as n_users_with_visit
     , round(count(v.user_id)::numeric / count(distinct v.user_id), 1)  as visits_per_user
     , sum(s.n_tweets) filter (where v.user_id is not null)             as n_visit_tweets
     , count(*) filter (where v.user_id is not null
                          and v.max_point_users is not null)            as n_visits_at_shared_point
from revised.visit_stay s
left join revised.visit v
  on v.city = s.city
 and v.user_id = s.user_id
 and v.local_date = s.local_date
 and v.cell_10 = s.cell_10
group by s.city
order by s.city;

-- Distance from home of visits (cell centroids)
select city
     , count(*) filter (where dist_home_m <  1000)                      as n_lt_1km
     , count(*) filter (where dist_home_m >= 1000 and dist_home_m < 5000) as n_1_5km
     , count(*) filter (where dist_home_m >= 5000 and dist_home_m < 10000) as n_5_10km
     , count(*) filter (where dist_home_m >= 10000)                     as n_10km_plus
     , percentile_cont(0.5) within group (order by dist_home_m)         as median_dist_m
from revised.visit
group by city
order by city;


-- ------------------------------------------------------------
-- V2  Activity confound: distinct visited cells per 10 active days
--     by user activity (active days in the city, from visit_stay).
--     If it rises with activity, any per-user count of places must
--     be normalised (or users subsampled to a fixed number of days).
-- ------------------------------------------------------------
with active as (
    select city, user_id, count(distinct local_date) as d_active
    from revised.visit_stay
    group by city, user_id
)
, places as (
    select city, user_id, count(distinct cell_10) as n_cells, count(*) as n_visits
    from revised.visit
    group by city, user_id
)
select a.city
     , case when a.d_active < 10  then '01-09'
            when a.d_active < 20  then '10-19'
            when a.d_active < 50  then '20-49'
            when a.d_active < 100 then '50-99'
            else '100+'
       end                                                              as active_days
     , count(*)                                                         as n_users
     , round(avg(coalesce(p.n_cells, 0))::numeric, 1)                   as avg_cells
     , round(avg(10.0 * coalesce(p.n_cells, 0) / a.d_active)::numeric, 2) as cells_per_10_days
     , round(avg(coalesce(p.n_visits, 0)::numeric / a.d_active), 2)     as visits_per_day
from active a
left join places p
  on p.city = a.city
 and p.user_id = a.user_id
group by 1, 2
order by 1, 2;


-- ------------------------------------------------------------
-- V3  Heaviest visitors per city: Portland has ~3x more visits per
--     user than the others. Automated accounts (job ads, traffic,
--     weather) post from many places and would dominate counts.
--     cells_per_day near 1+ every day over years = not a person.
-- ------------------------------------------------------------
select city, user_id, n_visits, n_cells, n_days, cells_per_day, tweets_per_visit, share_shared_point
from (
    select city
         , user_id
         , count(*)                                                     as n_visits
         , count(distinct cell_10)                                      as n_cells
         , count(distinct local_date)                                   as n_days
         , round(count(distinct cell_10)::numeric / count(distinct local_date), 2) as cells_per_day
         , round(avg(n_tweets), 2)                                      as tweets_per_visit
         , round(avg((max_point_users is not null)::int)::numeric, 2)   as share_shared_point
         , row_number() over (partition by city order by count(*) desc) as rk
    from revised.visit
    group by city, user_id
) x
where rk <= 10
order by city, rk;

-- Concentration: share of all visits made by the top 1% / 10% of users
select city
     , round(sum(n) filter (where pct <= 0.01) / sum(n), 3)             as share_top1pct
     , round(sum(n) filter (where pct <= 0.10) / sum(n), 3)             as share_top10pct
from (
    select city
         , count(*)::numeric                                            as n
         , percent_rank() over (partition by city order by count(*) desc) as pct
    from revised.visit
    group by city, user_id
) u
group by city
order by city;
