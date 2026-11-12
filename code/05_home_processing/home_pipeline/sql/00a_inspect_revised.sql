-- ============================================================
-- 00a_inspect_revised.sql  --  first look at the `revised` schema
-- Target DB: twitter_cities_v2, schema: revised
--
-- READ-ONLY and fast (only catalog tables, no scans of tweet).
-- Run each block separately.
-- ============================================================


-- ------------------------------------------------------------
-- R01  Where am I?
-- Must say twitter_cities_v2. can_set_role must be true, otherwise
-- we cannot create the pipeline tables later.
-- ------------------------------------------------------------
select current_database() as db
     , current_user as me
     , pg_has_role(current_user, 'twitter_project', 'member') as can_set_role_twitter_project
     , current_setting('search_path') as search_path
     , version();


-- ------------------------------------------------------------
-- R02  Columns of every table in revised, one row per table
-- (tells us what the new tweet / place / user tables look like)
-- ------------------------------------------------------------
select table_name
     , string_agg(column_name || ' ' || data_type, ', ' order by ordinal_position) as columns
from information_schema.columns
where table_schema = 'revised'
group by table_name
order by table_name;


-- ------------------------------------------------------------
-- R03  Primary keys and indexes in revised
-- ------------------------------------------------------------
select tablename, indexname, indexdef
from pg_indexes
where schemaname = 'revised'
order by tablename, indexname;


-- ------------------------------------------------------------
-- R04  Size and owner of each table
-- ------------------------------------------------------------
select c.relname as table_name
     , pg_size_pretty(pg_total_relation_size(c.oid)) as total_size
     , c.reltuples::bigint as est_rows
     , pg_get_userbyid(c.relowner) as owner
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'revised' and c.relkind = 'r'
order by pg_total_relation_size(c.oid) desc;


-- ------------------------------------------------------------
-- R05  Build notes left by whoever built revised (small table)
-- ------------------------------------------------------------
select * from revised.build_stats;


-- ------------------------------------------------------------
-- R06  Is h3 installed in this database?  (old check C02)
-- The pipeline needs h3. Extensions are per database, not per schema.
-- ------------------------------------------------------------
select e.extname, e.extversion, n.nspname as installed_in_schema
from pg_extension e
join pg_namespace n on n.oid = e.extnamespace
where e.extname in ('h3', 'h3_postgis', 'postgis');
