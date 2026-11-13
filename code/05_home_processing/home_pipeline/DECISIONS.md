# Home location pipeline: decision log

Every choice that can change which hexagon a user gets as "home" is listed here, with its default,
why it matters and how to check it. The parameter names match `config.yaml` (not written yet).

**Status values:** `open` (not decided, needs evidence), `proposed` (default chosen, not yet checked against data),
`settled` (checked and agreed).

**How to use this file:** when you revisit a decision, change the default in `config.yaml`, run with a new
`--run-label`, compare the runs with the diagnostics, then update the entry (date, evidence, status).
Every run stores its parameters in `home_run.params`, so old results stay reproducible.

**Goals (2026-11-11):** (1) homes as accurate as we can make them; (2) as many users with a home as the evidence
allows. A home needs both a minimum activity and minimum night evidence in the home cell (D05), and every home
carries a confidence tier (D16).

Origin: the first version of these rules comes from the `_zi` code (`../zita_notebooks/TWITTER_FINAL.ipynb`) and
`../zita_notebooks/home_location_inference_tables.ipynb`. "Legacy" below means what those notebooks do.

---

## D01. Signal: night-time tweets per hexagon
- **What:** a user's home is the hexagon where they tweet at night.
- **Legacy:** night = 20:00 to 08:00; hexagon = H3 at resolutions 10, 9, 8, computed separately.
- **Status:** proposed
- **Check:** `05_diagnostics.sql`, share of users with a home and share of their tweets in that hexagon, per city.

## D02. Night window hours
- **Parameters:** `night_start` = 20, `night_end` = 8
- **Legacy:** `hour < 8 or hour >= 20`
- **C10 result (2026-11-07):** in local time all cities bottom out at 04-05h but **peak at 20-21h**, so 20-08
  starts at the busiest hour of the day (evenings out, not only at home). 20-08 holds ~37% of tweets, 22-07 ~21%.
- **V4 result (2026-11-12):** with `nights`, 95-97% of users who have a home in both windows get the same cell, so
  the window choice hardly changes homes; 20-08 gives more users (22-07 keeps ~65-73%). Keeps 20-08 as default.
- **Proposed default:** 20-08 local (comparable with legacy and the literature, keeps the most signal);
  sensitivity run with 22-07. Compare how many homes change between the two.
- **Implementation:** `02_user_cell_counts.sql` stores night counts for both windows (`n_night_20_08`,
  `n_night_22_07`) in `home_user_cell`, so the sensitivity run needs no second pass.
- **Status:** proposed
- **Check:** hour-of-day histogram of tweets per city (in local time). The night window should sit on the low
  part of the curve.

## D03. Clock for the night window (time zone)
- **Parameter:** `tz_mode` = `local` | `utc`
- **Legacy:** `utc`. `tweet.created_at` is `timestamp` (UTC); the notebooks call `extract(hour ...)` on it directly.
- **Problem:** 20:00-08:00 UTC is about 12:00-00:00 local in Portland (UTC-8 / UTC-7) and 21:00-09:00 or
  22:00-10:00 in Amsterdam. Portland "homes" are mostly picked from daytime tweets.
- **Default:** `local`, using `Europe/London`, `Europe/Amsterdam`, `America/Los_Angeles` (daylight saving handled by
  Postgres). `utc` stays available to reproduce legacy results.
- **Status:** settled (2026-11-07): `local`. C03 confirmed the type; C10 shows UTC 20-08 covers 69% of Portland's
  tweets, mostly afternoon and evening.
- **Check:** night-hour histogram per city under both modes; detection rate per city under both modes.

## D04. Time window
- **Parameter:** `window` = 2013-01-01 to 2017-12-31 (inclusive), stored as `window_id = '2013-2017'`
- **Legacy:** `date_trunc('year', created_at) between date '2013-01-01' and date '2017-01-01'`. This works, and
  includes all of 2017, but only by accident of truncation. The new code uses an explicit half-open range
  (`>= 2013-01-01 and < 2018-01-01`).
- **Note (01 run, 2026-11-07):** the window is cut in UTC, so in local time it runs e.g. 2012-12-31 16:00 to
  2017-12-31 16:00 in Portland and 01:00 to 01:00 in Amsterdam. A few hours at each end of five years: ignored.
- **Later:** yearly or rolling windows. The output schema already has `window_id`; the logic does not.
- **Status:** proposed

## D05. Minimum activity per user
- **Parameters:** `min_user_tweets` = 20, `min_night_per_cell` = 2
- **Legacy:** at least 20 located tweets in the window and city bboxes; a hexagon must have at least 2 night tweets
  to be a candidate.
- **Note:** the second threshold is applied per hexagon *after* roll-up to each resolution, so it is not the same
  tweets at res 10 and res 8.
- **Parameters (2026-11-11):** `min_user_tweets` = 10, `min_home_nights` = 3, for `nights` and `night_tweets`.
- **Rule:** the user has >= `min_user_tweets` tweets in the city, and the home cell has >= `min_home_nights`
  distinct nights (D15) and strictly more nights than the user's second cell; otherwise no home.
  The tweet floor was added so a user with only 3 tweets on 3 nights cannot get a home; 10 sits between no floor
  and the legacy 20. Candidate cells: >= 1 night tweet. The legacy gates
  (20 tweets / 2 night tweets per cell) stay on the `ratio` method only, to reproduce the first run.
- **Why:** total activity is the wrong gate. 20+ users whose best cell has only 1 night: ams 3,310, lon 29,739,
  pdx 2,966 (legacy gives them a home); users with < 20 tweets but several nights in one cell get none. A first
  version with no gate (any night tweet) gave homes to 54-64% of users, ~80% of them on a single night: too loose.
- **Evidence (03 v2, nights, 20-08, res 9, untied homes by nights in cell):** >= 2 nights: ams 25,592 / lon 214,391 /
  pdx 17,958; >= 3 nights: 12,509 / 150,228 / 11,828; legacy ratio: 13,735 / 167,008 / 14,322. N = 3 keeps a user
  count close to legacy with every home seen on 3+ different nights; two nights can be a single weekend away.
- **Status:** proposed (sensitivity: nights 2, tweets 5 / 20)
- **Check:** `03` V5 (homes by activity bucket, shows what 20 would cut); D16 stability checks by bucket.

## D06. Tweets with coordinates
- **Rule:** tweets with `lat` and `lon` are used as they are. `lat`/`lon` are 32-bit floats from the load
  (about 1 m precision), well below H3 res 10 (about 65 m edge), so no issue. In the `revised` schema they are `double precision` (full precision).
- **Status:** proposed

## D07. Tweets with only a Place (no coordinates)
- **Parameters:** `use_place_centroids` = true, `place_err_max` = 200
- **Legacy:** tweets without coordinates take the place centroid if `place.err < 200`.
- **Open points:**
  1. Unit of `err`. `twitter_cities_v2_documentation.md` says metres; the old notebooks never state it. If it is km,
     the filter does almost nothing. Check C05.
  2. Many tweets share one centroid, so the centroid's hexagon can win as "home" by sheer count.
- **C05 result (2026-11-07):** err is in metres; the filter effectively means "POI places" (all POIs have err = 0)
  plus 15 non-POI places, some of which have err = 0 because their bbox is degenerate (a city cannot be 0 m wide).
  Proposed refinement: accept `place_type = 'poi'`, plus non-POI places only with `0 < err < 200`. Open question: POI
  tweets are often venue check-ins (bars, stations), which are not homes; decide after C06 shows their share.
- **C06 result (2026-11-07):** place-only tweets are negligible: 0 in London, 40 in Amsterdam, 57k in Portland
  (1.3% of Portland's located tweets, almost all POI check-ins).
- **Default (changed):** GPS only (`use_place_centroids` = false). Removes the check-in and broken-bbox problems at
  almost no cost in coverage. The `src` flag stays so a run with centroids can still be compared.
- **Status:** proposed
- **Check:** share of homes whose winning cell has mostly centroid tweets; compare against a GPS-only run.

## D08. City bounding boxes
- **Rule:** a tweet belongs to a city if its (possibly centroid) coordinates fall inside that city's box:

  | city | lat_min | lat_max | lon_min | lon_max |
  |---|---|---|---|---|
  | london | 51.2867601 | 51.6918741 | -0.5103751 | 0.3340155 |
  | portland | 45.4325360 | 45.6528812 | -122.8367489 | -122.4720252 |
  | amsterdam | 52.2781742 | 52.4310638 | 4.7287776 | 5.0791622 |

- **Note:** these are rectangles. London's covers more than Greater London. The boxes do not overlap.
- **Refinement (2026-11-07, `01_home_input.sql`):** a tweet must fall inside the box of its own `city` label, so the
  home-input city always equals the `city` used in the `(city, tweet_id)` key of `tweet` and the networks. C06
  matched boxes on coordinates only; the V1 counts in `01_home_input.sql` show whether this drops anything.
- **Status:** proposed

## D09. Home scope: per user or per user and city
- **Legacy:** one home per user across all cities (ranking is over all of the user's hexagons).
- **Open:** a user with tweets in two city boxes gets one home in one city. Check C08 for how many users this is.
- **C08 result (2026-11-07):** 1% user sample, all years and tweets: 2,415 of 34,378 users (7.0%) tweet in more than
  one city, i.e. roughly 240k users overall. Likely an upper bound: the home input (2013-2017, gps, in bbox, minimum
  activity) will drop most visitors with a handful of tweets. Still higher than expected for three cities: suspected
  bots / automated accounts (job, weather, cross-posting) and possibly how the collection assigned the `city` label.
  Not pursued with more full scans; `05_diagnostics.sql` profiles multi-city users on the slim input (city pairs,
  tweet volume, homes in 2+ cities), and D05 / D12 thresholds are tuned from there.
- **Proposal:** detect home per `(user, city)`, with the minimum-activity rule (D05) applied per `(user, city)`.
  `home_location` gets `n_home_cities` and `is_primary` (city with the most night tweets; tie-break all tweets). Analyses
  wanting one home per user filter `is_primary`; city-level networks use the city's own home. Diagnostics report how
  many users end up with homes in two cities.
- **Status:** proposed

## D10. Ranking of candidate hexagons
- **Parameter:** `ranking` = `ratio` (legacy)
- **Legacy:** `ratio = night tweets in hexagon / all tweets in hexagon`; highest wins; ties go to the hexagon with
  more total tweets. New code adds the cell id as last tie-break so reruns are deterministic.
- **Problem:** a hexagon with 2 of 2 tweets at night (ratio 1.0) beats one with 30 of 40 (0.75). Spots visited briefly at
  night can beat the real home.
- **Alternatives to compare:** most night tweets; ratio with shrinkage (e.g. add pseudo-counts); require a minimum
  share of the user's night tweets.
- **03 first run (2026-11-11), ratio, 20-08, res 10:** avg ratio of the home cell ~0.8, but the home holds only
  21-24% of the user's tweets and 31-37% of their night tweets; about a third of homes tie with the second cell on
  ratio (london 53,643 of 164,458), mostly small cells at ratio 1.0. The ratio picks small, all-night cells, not the
  place with the most night activity. Confirms the problem above.
- **Change (2026-11-11):** `method` column in `home_location`, three methods side by side:
  `nights` (most distinct nights in the cell, D15; ties: night tweets, all tweets, cell) = **proposed default**;
  `night_tweets` (most night tweets; ties: nights, all tweets, cell); `ratio` (legacy, legacy gates).
  Distinct nights, not tweet counts, because a single burst (an evening of 15 tweets at a bar or event) counts once;
  "distinct days" criteria are the usual choice in the mobile-phone home detection literature for the same reason.
- **Status:** proposed; V2 (2026-11-11): `nights` and `night_tweets` agree on 99.8% of users, `ratio` on only 34-47%.
- **Check:** `03` V2 (agreement between methods, nights the ratio home keeps), V4 (window stability per method);
  D16 stability checks.

## D11. Tweet types
- **Parameter:** `tweet_types` = original, reply, quote
- **Legacy:** all rows in `tweet` are used, including retweets and quotes.
- **Open:** whether retweets and quotes carry a location that tells us where the user is. See C09 for the counts.
- **C09 result (2026-11-07):** 2013-2017 gps share by type: original 51.5%, reply 38.7%, quote 1.3%, retweet 47.8%
  (of only 69k retweets). Quotes and retweets together are 81k of 46.8M gps tweets (0.17%), so the choice barely
  matters. Retweets are dropped anyway: native retweets carry no geo, so a 48% gps share suggests the coordinates may
  come from the retweeted tweet (another user's location) or from old manual "RT" tweets. Quotes are written by the
  user and kept.
- **Status:** proposed

## D12. "No home" rule
- **Rule:** a user has a home at a resolution only if at least one hexagon has `min_night_per_cell` night tweets.
- **Legacy:** this is implicit. The ranking picks a "top" hexagon even when no hexagon qualifies, and the Y/N flag
  only ends up Y because the night count is NULL for it.
- **New code:** explicit. Users without a qualifying hexagon get no `home_location` row at that resolution.
- **Status:** proposed

## D13. Network edges "same home location"
- **Legacy:** `mention_network_same_homeloc_s*_zi` and `reply_network_same_homeloc_s*_zi` keep an edge if both users
  have a home flag in the same city box as the tweet. They do **not** compare hexagons, so the name overstates it.
- **Join key:** the legacy SQL joins `mention_network` / `reply_network` to `tweet` on `tweet_id` only; the key is
  `(city, tweet_id)`. Check C07.
- **C07 result (2026-11-07):** 0 tweet_ids occur in more than one city, so legacy joins on `tweet_id` alone did not
  duplicate rows. New code still joins on `(city, tweet_id)` to match the PK and use the index.
- **Keys in `revised` (2026-11-07):** `tweet` PK `(city, tweet_id)`; `mention_network` and `reply_network` PK
  `(city, user_id1_source, user_id2_interaction, tweet_id)`; `place` PK `place_id`. So the join to `tweet` must use
  `(city, tweet_id)`, and the user columns are `user_id1_source` (author) and `user_id2_interaction` (mentioned / replied-to user).
- **New code:** `mention_network_home` / `reply_network_home`, joined on `(city, tweet_id)`. A stricter "same
  hexagon / within distance" variant can be added later and named accordingly.
- **Status:** open

## D14. Technical choices (not methodological)
- H3 computed once at res 10; res 9 and 8 via `h3_cell_to_parent`. Exact, since counts add up under roll-up.
- h3 functions are called with the schema prefix and the new name: `public.h3_latlng_to_cell`, `public.h3_cell_to_parent`.
- Scripts that compare two h3 cells set `search_path = revised, public` in S1: the `h3index` operators live in
  `public`, and a `revised`-only path gives "operator does not exist: public.h3index = public.h3index" (03, 2026-11-11).
- Intermediates are `UNLOGGED`; the result table `home_location` is a normal table.
- Pipeline tables live in schema `revised` with the prefix `home_` (`home_input`, ...), so they group together and
  can be dropped without touching the core tables (agreed 2026-11-07).
- `home_input` (step 01) holds only filters that no sensitivity run changes (D03, D04, D07, D08, D11, res-10 cell);
  night window, minimum activity and ranking are applied in later steps, so it is built once.
- All DDL wrapped in `SET ROLE twitter_project; ... RESET ROLE;`.
- **Status:** proposed


## D15. Counting nights
- **Rule:** a night is the local evening plus the following morning: `night_date = (created_local - 8 hours)::date`.
  20:00 on day D and 07:59 on day D+1 are both night D; the same date works for 22-07.
- **Stored:** `home_user_cell_nights.d_night_20_08 / d_night_22_07` per (city, user, res, cell), computed at each
  res separately (distinct counts do not add up under roll-up, unlike D14); `home_user.d_night_*` and `d_active`
  per (city, user).
- **Status:** proposed

## D16. Confidence tiers
- **Parameter:** `high_min_nights` = 5
- **Rule:** `high`: home cell has >= 5 distinct nights and strictly more nights than the second cell. `medium`: >= 2
  nights and strictly more than the second cell (with the D05 gate: 3-4 nights). `low`: the rest (one night, or a
  tie; only `ratio` rows). Computed from nights for every method, so for `ratio` it describes the evidence, not the
  ranking. A label only: it never removes a home.
- **History:** first version (2026-11-11) also required >= 50% of the user's nights for `high`. V5 showed the share of
  `high` fell with activity (94% / 78% / 64% for 10-19 / 20-49 / 50+ tweets): the share favours light users.
  Replaced by the absolute count the same day.
- **Status:** decided 2026-11-12 (see Result)
- **Check (no ground truth, so consistency):** (a) temporal split: detect on 2013-2015 and 2016-2017 separately;
  share of users with the same cell, by tier (should rise from low to high); (b) nesting: res 10 home lies inside the
  res 8 home; (c) window: same cell under 20-08 and 22-07 (V4). Tiers are tuned so `high` is stable on (a). Planned
  in `05_diagnostics.sql`.
- **Result (2026-11-12):** settled. Week split (05 V8): same cell 88-91% overall, 92-94% with >= 5 nights, 95-97%
  with >= 10 (after D18, 2026-11-13: 89-93% / 92-95% / 96-97%); `high` more stable than `medium` across periods in every city (05 V3). 10 / 3 / 5 kept.

## D17. Final home table
- **Table:** `revised.home_final` (`06_home_final.sql`), one row per (city, user_id, res), res 10 and 9. Method
  `nights`, window 20-08, D05 gate, D16 tiers.
- **Res:** both kept. Week-split reliability differs by ~1 point (05 V8) and res 10 sits inside res 9 for 99% of
  users (05 V4), so res 10 is as good as 9.
- **Kept alongside:** night-tweet counts in the home cell and for the user, and the home under the `night_tweets`
  ranking (`cell_night_tweets`) for sensitivity.
- **Flags, nothing dropped:** `moved` (gated 2013-15 and 2016-17 homes >= 1 km apart, 05 V7/V8; null where not
  testable, ~95% of homes: only 3-6% have a gated home in both periods), `multi_city` (homes in > 1 city), `suspect_bot` (homes in all three cities, 05 V5; the
  20+ tweets per day group of 05 V6 is not flagged).
- **Ids:** raw user_id, no pseudonymisation: the data stay on the secured server.
- **Status:** decided 2026-11-12.

## D18. Shared points
- **Problem:** the first home_overview run showed single res 10 cells holding 11% / 4% / 6% of all homes
  (ams / lon / pdx). Suspected cause: coordinates posted by apps (venue or default points), identical for many
  users, which pass D07 as "gps".
- **Rule:** drop tweets at an exact (lat, lon) used by >= 100 distinct users in the city (`min_point_users`,
  `01_home_input.sql` S2b). Applied per point, not per cell, so genuine homes in the same cell stay. Device GPS
  fixes of different users almost never coincide exactly.
- **Kept for reuse:** `revised.home_shared_points` lists all points with >= 5 users (n_users, n_tweets); shared
  points are often venues, useful for the third-place step.
- **Check:** 01 V3 (points and tweets removed at 5 / 10 / 20 / 50 / 100 / 200 / 500 users, largest points); 05 V9 before the
  rebuild (top cells and their most used points); hotspots gone in home_overview after the rebuild.
- **Result (2026-11-12):** 01 rebuilt with 100: tweets ams 3,185,653 -> 2,772,313 (-13%), lon 35,945,546 ->
  32,695,037 (-9%), pdx 4,527,650 -> 4,259,157 (-6%); users 238,484 -> 181,300 (-24%), 962,934 -> 823,414 (-14%),
  112,699 -> 96,664 (-14%). The largest shared points are city / landmark default coordinates, not homes: London
  51.507114, -0.127318 (Trafalgar Square / Charing Cross, the generic "London" point), Heathrow 51.471710, -0.468103,
  Tower Bridge 51.505150, -0.075585; Amsterdam 52.373100, 4.892200 (Dam, the generic "Amsterdam" point), Schiphol
  52.309238, 4.762187; Portland 45.520000, -122.682000 (the generic "Portland" point).
- **Largest points (01 V3, users / tweets):** ams Dam 41,456 / 103,023, Schiphol 19,237 / 40,440 (+ a second
  Schiphol point 3,914), two Amsterdam Centraal / centre points ~4,000 each; lon Trafalgar Square 75,534 / 416,277,
  Heathrow 21,714, Tower Bridge 20,830, a second generic London point 20,561, Soho 16,508; pdx generic Portland point
  13,485 / 63,005, three PDX airport points 6,062 / 2,084 / 1,937, downtown 1,703. Tens of thousands of users per
  point: far above any plausible home, so 100 is a safe cut.
- **Precision note:** `revised.tweet.lat/lon` are double precision but hold float32 values (e.g. 51.50711441040039
  = float32 of 51.507114): the coordinates passed through a 32-bit float in the build. Resolution ~0.4 m (lat) to
  ~0.6 m (Portland lon), so chance collisions of 100 users are impossible; the rule is unaffected. Flag to the
  table build (Spark FloatType).
- **Status:** decided 2026-11-13 (01 V3, 03 / 05 / 06 reruns, home_overview v2: hotspots gone). Threshold 100 (user: the hotspots hold 500+ homes even in Portland, so only
  points used by very many users are the problem; 10 would also cut ordinary venues); confirm with 01 V3.

## D19. Work place (minimal label)
- **Purpose:** only to keep work out of the third-place visits (D20), not an analysis target. People work in
  many ways (shifts, several sites, no fixed place), so a label is set only where it is clear, and most users
  get none.
- **Rule (`07_work.sql`, `revised.work_final`):** res 10 only. Evidence = distinct Mon-Fri dates with a tweet at
  09-16h local in the cell. Candidates exclude the home area (home res 10 cell + ring 1; res 9-only homes: the
  7 res 10 children). Work = best cell with >= 3 such dates (`min_work_days`) and strictly more than the second
  cell. No tiers, no res 9, no sensitivity runs.
- **Input:** `revised.visit_stay` (D20), so shared points are kept: airports, stations, campuses can be work.
- **Check:** 07 V1 only (share of home users with work, commute distance, top work cells).
- **Status:** decided 2026-11-13 (user: keep it minimal).

## D20. Visits (third-place candidates)
- **Unit:** a stay = (city, user_id, local date, res 10 cell), `revised.visit_stay` (07 S2a); n_tweets, first /
  last local time, `max_point_users` kept. Only users with a home (`home_final`, any res).
- **Input:** as `home_input` (D04, D07, D08, D11, D03) except D18: shared points are kept, since check-in venues
  are third-place visits; only generic city points (the city's default coordinate, no venue) are dropped:
  London 51.507114, -0.127318 (75,534 users) and 51.507198, -0.127500 (20,561, the Wikipedia London point),
  Amsterdam 52.373100, 4.892200 (41,456), Portland 45.520000, -122.682000 (13,485); dropped as shared points (>= 100 users)
  within ~30 m of these centres, so app variants of the same default go too (London 51.507195 / 51.507221 /
  51.507301, Portland 45.52, -122.681946). First S2a run (2026-11-13) still had the Wikipedia London and the
  Portland point (they topped the work cells: 123 / 276 users) -> widened and rerun. Reviewed with 07 V0 (2026-11-13): the other top points are venues or areas and stay
  (Schiphol, Amsterdam Centraal, Rijksmuseum, Heathrow, Tower Bridge, Trafalgar Square, Westminster, London Eye,
  PDX airport; neighbourhood points Soho 16,508 and Shoreditch 7,868 also stay, flagged by `max_point_users`).
- **Visit (`08_visits.sql`, `revised.visit`):** stays outside the home area (home cell + ring 1, ~200 m: GPS
  jitter at home) and outside the work cell (D19). With sparse Twitter activity every such stay is a potential
  third place; POI matching is done on top (student). Home and income join back on (city, user_id).
- **Caveat for analysis:** places visited grow with activity; per-user counts need normalising by active days
  or a fixed subsample of days (08 V2 shows the size of the effect).
- **Automated accounts (08 S3, `revised.visit_user`):** per-user activity (d_active, d_visit, n_visits, n_cells,
  cells_per_10_days, median_dist_m) and `automated` = on average >= 10 visits per visit day (`max_visits_per_day`).
  Flag, not drop; the student filters `not automated`. Threshold 10 confirmed with 08 V4 (2026-11-13).
- **Status:** decided 2026-11-13.

---

## Open questions waiting for check results
| Check | Decides | Result |
|---|---|---|
| C02 | h3 available on v2? | Installed in schema `public`: h3 ("unreleased" build), h3_postgis 4.2.3, postgis 3.6.2; call as `public.h3_...`. Smoke test OK: cell_10 = 8a1969c9b277fff, parent_9 = direct_9 = 891969c9b27ffff. Notice: `h3_lat_lng_to_cell` to be renamed `h3_latlng_to_cell` in next major h3 release; `public.h3_latlng_to_cell` already exists and gives the same cell, so the pipeline uses the new name. 2026-11-07 |
| C03 | `created_at` type (D03) | `revised.tweet.created_at` is `timestamp without time zone` (UTC by convention); 2026-11-07 |
| C05 | unit of `place.err` (D07) | Metres (Portland city 17.8 km, London admin 36.9 km). All 32,114 POIs have err = 0 (point places); only 12 neighborhoods and 3 cities pass err < 200, the 3 cities (and some neighborhoods) with err = 0 look like broken bboxes. So `err < 200` = POIs + 15 others. 2026-11-07 |
| C06 | input size, gps vs place (D04, D05, D07) | 2013-2017 in bbox: amsterdam gps 3,191,990 tweets / 238,514 users, place 40; london gps 35,960,332 / 963,010, place 0; portland gps 4,528,967 / 112,710, place_poi 57,282 / 19,153, place_other 20. Ran in ~4 min. 2026-11-07 |
| C07 | `tweet_id` unique across cities? (D13) | Yes: 0 tweet_ids appear in more than one city. 2026-11-07 |
| C08 | users in more than one city (D09) | 1% user sample (`user_id % 100 = 0`), all years: 34,378 users, 2,415 (7.0%) in more than one city (collection label). 2026-11-07 |
| C09 | tweet types in window (D11) | 2013-2017, n / with gps: original 65,736,952 / 33,825,375; reply 33,332,386 / 12,893,486; quote 3,584,424 / 47,838; retweet 69,269 / 33,119. Total gps 46.8M, of which 43.7M inside the bboxes (C06). 2026-11-07 |
| 01 | `home_input` built (D03, D04, D07, D08, D11) | tweets / users: amsterdam 3,185,653 / 238,484; london 35,945,546 / 962,934; portland 4,527,650 / 112,699 (vs C06: -0.2% / -0.04% / -0.03% tweets, retweets and label mismatches). cell_10 never null. Users with >= 20 tweets: 15,792 (6.6%, 77% of tweets) / 184,705 (19.2%, 91%) / 16,036 (14.2%, 92%). 3.2 GB table + 1.4 GB PK. 2026-11-07 |
| 02 | `home_user_cell` built | n_all and n_users identical at res 10/9/8 and equal to 01 in every city. Rows res 10/9/8: amsterdam 942,648 / 818,534 / 671,205; london 8,973,743 / 7,457,721 / 5,800,036; portland 884,660 / 695,922 / 530,134. Night share of gps tweets 20-08 / 22-07: ams 36.1 / 21.4%, lon 39.3 / 22.3%, pdx 38.5 / 23.8% (close to C10 for all tweets). 2.2 GB table + 1.3 GB PK. 2026-11-07 |
| 03 (v1) | first `home_location`, ratio only, users >= 20 tweets (D10) | Build 1m46s. 20-08: homes res 10/9/8 ams 13,412 / 13,735 / 14,047; lon 164,458 / 167,008 / 169,973; pdx 14,049 / 14,322 / 14,602 = 85 / 89 / 88% of 20+ users at res 10. 22-07 res 10: 10,775 / 139,680 / 11,328. Res 10, 20-08: avg share of user tweets in home 0.235 / 0.212 / 0.191, of night tweets 0.374 / 0.328 / 0.315; avg ratio 0.79 / 0.81 / 0.81; single candidate 4,625 / 48,847 / 3,991; ratio tied with second 3,767 / 53,643 / 4,871. Led to D05 / D10 change, D15, D16. 2026-11-11 |
| 03 (v2) V1 | coverage and tiers per method, 20-08 (D05, D10, D16) | S2b 3m 8s + PK 52s. `ratio` reproduces 03 (v1) exactly. `nights`: homes ams 127,636 / lon 614,104 / pdx 64,191 = 53.5 / 63.8 / 57.0% of users in home_input (the rest have no night tweet), same at every res; 20+ users with a home 15,320 / 181,737 / 15,712 = 97.0 / 98.4 / 98.0% (ratio: 85-89%). Tiers res 9 high / medium / low: ams 9,801 / 15,791 / 102,044; lon 112,868 / 101,523 / 399,713; pdx 8,340 / 9,618 / 46,233, so high + medium alone (25.6k / 214.4k / 18.0k) exceeds all ratio homes (13.7k / 167.0k / 14.3k). Ratio homes: only ~20% high. `night_tweets` aggregates within 1-2% of `nights`. avg shares not comparable across methods (nights includes 1-tweet users, share = 1). 2026-11-11 |
| 03 (v3) V1 | gated: min_user_tweets 10, min_home_nights 3, strict lead (D05, D16), 20-08 | `ratio` unchanged. `nights` homes res 10 / 9 / 8: ams 10,102 / 10,872 / 12,073; lon 134,038 / 140,959 / 149,822; pdx 10,536 / 11,174 / 12,195 (now rises with coarser res: nights pool in larger cells). Res 9 = 79 / 84 / 78% of ratio's count; users with 10-19 tweets 22 / 14 / 12% of homes; 20+ users with a home 54 / 66 / 61% (ratio 87 / 90 / 89%: the difference is 20+ users with < 3 nights or a tie in their best cell). Tiers res 9: high 75 / 74 / 69% (ratio ~22%), low 0. Home holds on average 53 / 52 / 50% of the user's tweets and 69 / 67 / 63% of their nights (ratio: 26 / 24 / 22% and 42 / 35 / 34%). `night_tweets` 3-4% fewer homes, same profile. 2026-11-11 |
| 03 (v3) V5 | homes by user activity, nights, 20-08, res 9 (D05, D16) | Users with a home by tweets in city: 10-19: ams 2,385 of 16,545 (14%), lon 19,038 of 99,803 (19%), pdx 1,379 of 9,790 (14%); 20-49: 37 / 45 / 39%; 50+: 78 / 84 / 81%. Users with < 10 tweets (ams 206k, lon 678k, pdx 87k) get none by design. Share `high` falls with activity: 10-19 ~94%, 20-49 ~78%, 50+ ~64%: the 50%-of-nights condition is easy for light users (3 of few nights) and hard for heavy users with many places, so tiers are not comparable across activity levels. Revisit D16 with the stability check by bucket (e.g. absolute night count instead of share). 2026-11-11 |
| 03 (v4) V1 | tiers with `high` = >= 5 nights (D16) | Homes identical to v3. `nights` res 9 high / medium: ams 6,386 / 4,486 (59% high); lon 100,647 / 40,312 (71%); pdx 7,800 / 3,374 (70%). Ratio homes reaching `high`: 17 / 21 / 18%. V5 share `high` by tweets 10-19 / 20-49 / 50+: ams 24 / 47 / 84%, lon 28 / 56 / 89%, pdx 27 / 51 / 86%: now rises with activity, as it should. 2026-11-11 |
| 03 (v4) V2 | method agreement, users with a home under all three methods, 20-08 (D10) | Users res 10 / 9 / 8: ams 7,627 / 8,123 / 8,818; lon 111,519 / 116,852 / 123,216; pdx 8,819 / 9,325 / 10,075. Same cell nights vs ratio: ams 42 / 44 / 47%, lon 38 / 40 / 42%, pdx 34 / 37 / 38%. Same cell nights vs night_tweets: 99.7-99.9% everywhere. The ratio home has on average 48-61% of the nights of the nights home. So for well-evidenced users the legacy method picks a different cell in 53-66% of cases, typically one with about half the night evidence; once gated, counting nights or night tweets makes no practical difference. 2026-11-11 |
| 03 (v4) V3 | users with homes in more than one city, nights, 20-08 (D09) | Users with a home res 10 / 9 / 8: 154,089 / 162,324 / 173,215; in more than one city: 569 / 661 / 855 (0.37 / 0.41 / 0.49%); of those, primary home `high`: 422 / 506 / 643. C08's 7% multi-city users are almost all visitors with little evidence; with the D05 gate multi-city homes are negligible (movers within 2013-17, or bots; profile in 05). 2026-11-12 |
| 03 (v4) V4 | same cell under 20-08 and 22-07, res 10 (D02) | Users with a home in both windows / share same cell: nights ams 6,545 / 96.3%, lon 98,173 / 97.0%, pdx 7,314 / 95.4%; night_tweets 97.3 / 97.9 / 96.6%; ratio 10,775 / 65.1%, 139,680 / 61.6%, 11,328 / 59.8%. The nights home barely depends on the window, the ratio home changes for ~40%. 22-07 gives homes to ~65-73% as many users as 20-08 (fewer nights pass the gate). 2026-11-12 |
| 05 V1 | temporal stability 2013-15 vs 2016-17, nights, no gate (D05, D16) | Users with a night cell in both periods are few (lon ~61k of 141k homes; ams ~7.5k; pdx ~5.5k); most users' evidence sits in one period. Share with the same cell, by weaker-period nights 1 / 2 / 3-4 / 5-9 / 10+, res 10: ams 0.11 / 0.24 / 0.32 / 0.38 / 0.46; lon 0.04 / 0.12 / 0.19 / 0.26 / 0.38; pdx 0.08 / 0.18 / 0.30 / 0.39 / 0.50; res 9 a few points higher (lon 10+: 0.40). Rises steadily with evidence, no plateau; even 10+ nights only 38-52%. Gate (strict lead, >= 10 tweets) changes little. Open: real moves over a ~2.5-year gap vs. measurement noise -> V7 distance and an interleaved split. 2026-11-12 |
| 05 V7 | distance between the 2013-15 and 2016-17 homes, gated pairs (>= 3 nights, strict lead, >= 10 tweets both) | Users res 10 / 9: ams 556 / 633, lon 5,681 / 6,212, pdx 675 / 723. Res 10 same / < 300 m / 300 m-1 km / 1-5 km / 5 km+: ams 0.37 / 0.09 / 0.10 / 0.30 / 0.15; lon 0.26 / 0.07 / 0.10 / 0.23 / 0.34; pdx 0.40 / 0.06 / 0.08 / 0.22 / 0.24. Res 9 same 0.42 / 0.28 / 0.43 (< 300 m is 0 by construction: res 9 neighbour centroids are ~300 m apart). About 3/4 of differing homes are >= 1 km apart, so V1's low stability is not jitter or cell borders, and coarser res barely helps: the method picks a different place, either a real move or a competing night place (partner, friends). Period split cannot separate the two -> S2c interleaved week split, V8. 2026-11-12 |
| 05 V8 | reliability vs moves: period split next to interleaved week split (S2c, alternate Mon-Sun weeks), gated pairs as V7 | Week split users res 10 / 9: ams 3,814 / 4,105, lon 67,696 / 71,676, pdx 5,273 / 5,622. Week split same cell res 10: ams 0.90, lon 0.91, pdx 0.88 (res 9: 0.90 / 0.91 / 0.89); >= 1 km apart only 5-7%; with >= 5 nights in both halves 0.92-0.94, >= 10 nights 0.95-0.97. Period split 0.26-0.40 (V7). The method is reliable: given the same time span it finds the same cell ~9 times in 10, and the gate (3 nights) and `high` tier (5) sit where agreement is already ~90% / ~94%. The low period agreement is therefore mostly real change of night place over time (moves; also partners etc.), not measurement noise: about half of users observable in both periods change home by >= 1 km. Caveat: reliability is not validity; a place visited every week (partner) would be picked consistently too. Consequences: keep 10 / 3 / 5; the 2013-17 home is the dominant night place over the period; flag users whose period homes differ in the final table. Res 9 vs 10 differ by ~1 point, so res is a privacy choice. 2026-11-12 |
| 05 V2 | period stability by activity (tweets in the weaker period), gated pairs with >= 3 nights | Same cell by tweets 01-09 / 10-19 / 20-49 / 50+, res 10: ams 0.59 / 0.52 / 0.41 / 0.31; lon 0.41 / 0.30 / 0.26 / 0.25; pdx 0.56 / 0.45 / 0.40 / 0.40 (res 9 similar, 1-6 points higher). Small cells for 01-09 (ams 29, lon 241, pdx 27). Period stability falls with activity: more tweets do not make the home more stable; heavy users have more places and more chances that another night place takes over. Evidence that matters is nights (V1, V8), not tweets, so no reason to raise min_user_tweets above 10. Period split mixes moves with reliability -> V2b on the week split. 2026-11-12 |
| 05 V2b | V2 at res 10 with period and week split side by side | `share_period` reproduces V2. Week split same cell by tweets in the weaker half 01-09 / 10-19 / 20-49 / 50+: ams 0.98 / 0.92 / 0.90 / 0.90 (n 247 / 587 / 1,192 / 2,035); lon 0.95 / 0.93 / 0.90 / 0.90 (2,689 / 8,144 / 19,532 / 40,020); pdx 0.93 / 0.91 / 0.88 / 0.88 (192 / 549 / 1,419 / 3,305). Reliability is high at every activity level and drops only ~5 points from light to heavy users; the steep fall in V2 is change over time (heavy users move / switch night places more), not method noise. min_user_tweets = 10 is not needed for reliability (3 nights + strict lead carry it); kept as a sample choice. 2026-11-12 |
| 05 V3 | period stability by tier of the full-period home, and full home = 2016-17 home (nights, 20-08) | Homes with a period home in both periods (ungated period homes, so shares sit below V7): high / medium res 10 ams 1,611 of 5,940 / 894 of 4,162; lon 18,963 of 95,411 / 7,122 of 38,627; pdx 1,802 of 7,375 / 651 of 3,161 (~20-27%). Same cell across periods, high vs medium, res 10: ams 0.29 vs 0.24, lon 0.16 vs 0.10, pdx 0.26 vs 0.17 (res 9 2-4 points higher). Full home = 2016-17 home: high 0.46-0.60, medium 0.60-0.74 (res 10; medium users have few nights, often mostly in one period, so the full home is that period's home). `high` is more stable than `medium` in every city: tiers order as intended. The full-period home is not simply the latest home; it is the dominant night place over 2013-17 (V8). Only ~1/4 of homes can be checked for a move (night evidence in both periods), so a `moved` flag will be missing for most users. 2026-11-12 |
| 05 V4 | nesting: res 10 home inside the res 9 / res 8 home (nights, 20-08) | Users with a home at all three res: ams 9,708, lon 129,976, pdx 10,140. Res 10 home inside res 9 home 0.991 / 0.990 / 0.988, inside res 8 home 0.981 / 0.982 / 0.973. Homes are consistent across resolutions; picking a res does not pick a different place. 2026-11-12 |
| 05 V5 | users with homes in more than one city (nights, 20-08, res 9) | 661 users (matches 03 V3): ams + lon 554 (148 all `high`, median 159 tweets / 29 nights), lon + pdx 64 (19), ams + pdx 23 (7), all three 20 (14; median 506 tweets / 158 nights). Multi-city users are heavy users with real night evidence in each city: movers, commuters, expats, plus some automated accounts. Three-city homes with 150+ nights are implausible for a person -> suspect bots. Homes stay per (city, user): flag `n_home_cities > 1`, flag 3-city users as suspect, do not drop. 2026-11-12 |
| 05 V6 | tweets per active day of users with a home, nights, 20-08, res 9 (bots) | Homes by tweets/day 0-2 / 2-5 / 5-20 / 20+: ams 6,314 / 3,222 / 1,175 / 161; lon 75,375 / 49,084 / 15,075 / 1,425; pdx 6,579 / 3,407 / 1,077 / 111 (totals match 03). 20+ is 1.0-1.5% of homes, 5-20 ~10%. Heavier users have more concentrated homes: avg share of user tweets in the home cell rises from 0.46-0.49 (0-2) to 0.67-0.75 (20+), and more of them are `high` (lon 68% -> 80%, pdx 66% -> 83%). 20+ fits stationary automated accounts (feeds, cross-posting) as well as very heavy home tweeters. Small group: flag, don't drop. 2026-11-12 |
| 06 V1 | `home_final` contents per city and res (D17) | 317,681 rows = 03 `nights` 20-08 homes res 10 + 9. Res 10 / 9 homes: ams 10,102 / 10,872, lon 134,038 / 140,959, pdx 10,536 / 11,174; high 5,940 / 6,386, 95,411 / 100,647, 7,375 / 7,800. Same cell as `night_tweets` 0.998-0.999. `moved` known for only ams 529 / 598, lon 5,346 / 5,887, pdx 642 / 686 (4-6% of homes; not ~1/4 as estimated from V3, which used ungated period homes); moved share 0.43 / 0.42, 0.57 / 0.55, 0.44 / 0.45 (matches V7). multi_city rows res 9 597 / 638 / 107 (matches V5), suspect_bot 20 per city at res 9, 19 at res 10. 2026-11-12 |
| home_overview | first run of the overview notebook (maps, population) | Hotspots: one res 10 cell holds 1,132 of 10,102 Amsterdam homes (11%), 5,474 of 134,038 London (4%), 587 of 10,536 Portland (6%); also visible as outliers in the homes vs population scatter. Suspected default / venue coordinates shared by many users (app-generated points, not device GPS), which D07 does not catch. -> 05 V9 (top cells, most used exact points). Population (GHS-POP 2015): Spearman homes vs residents per cell, res 8 / 9 / 10: ams 0.82 / 0.71 / 0.46, lon 0.88 / 0.78 / 0.45, pdx 0.65 / 0.53 / 0.26; ~10-14 homes per 1,000 residents. Funnel res 9: users -> >= 10 tweets -> >= 3 nights -> home: ams 238,484 / 32,337 / 11,332 / 10,872; lon 962,934 / 284,508 / 145,895 / 140,959; pdx 112,699 / 25,826 / 11,642 / 11,174 (strict lead removes only ~4%). 2026-11-12 |
| 03 (v5, D18) V1 | homes after dropping shared points (D18), 20-08 | `nights` homes res 10 / 9 / 8: ams 8,078 / 8,646 / 9,453; lon 124,193 / 130,174 / 137,040; pdx 9,521 / 10,087 / 10,845. Res 9 vs before D18 (10,872 / 140,959 / 11,174): -20% / -8% / -10%, more than the hotspot cells alone held at res 9 (1,274 / 5,797 / 673): also users who drop below 10 tweets or 3 nights once their shared-point tweets are gone. Remaining homes are stronger: `high` res 9 63 / 73 / 71% (was 59 / 71 / 70%); home holds 71 / 70 / 65% of the user's nights (was 69 / 67 / 63%). `night_tweets` 3-4% fewer homes, same profile. `ratio` res 9: 10,874 / 146,389 / 12,652. 2026-11-12 |
| 05 V8 (v2, D18) | V8 rerun after dropping shared points (D18) | Users res 10 / 9: week split ams 3,390 / 3,640, lon 64,283 / 67,971, pdx 4,907 / 5,228; period split ams 330 / 382, lon 3,656 / 4,008, pdx 475 / 516 (period pairs -30 to -41% vs V7: shared points were common in 2016-17). Week split same cell res 10: ams 0.914, lon 0.916, pdx 0.889 (res 9: 0.922 / 0.927 / 0.902); >= 1 km apart 4-6%; >= 5 nights 0.92-0.95, >= 10 nights 0.96-0.97. All 1-2 points above v1. Period split same cell res 10: ams 0.36, lon 0.36, pdx 0.43 (v1 0.37 / 0.26 / 0.40); >= 1 km apart 0.40-0.45. London's period agreement rose by 10 points: part of the apparent moves were users whose home in one period was a shared point. Conclusions of V8 unchanged: method reliable (~9 in 10), period gap mostly real change. 2026-11-13 |
| 06 V1 (v2, D18) | `home_final` rebuilt after D18 | 290,699 rows; homes res 10 / 9 match 03 (v5): ams 8,078 / 8,646, lon 124,193 / 130,174, pdx 9,521 / 10,087; high 5,104 / 5,455, 90,280 / 95,008, 6,793 / 7,181. Same cell as `night_tweets` 0.998-0.999. `moved` known for ams 317 / 362, lon 3,494 / 3,828, pdx 461 / 495 (3-5% of homes, was 4-6%); moved share 0.41 / 0.42, 0.44 / 0.43, 0.39 / 0.40 (London was 0.57 / 0.55: shared points inflated moves, cf. 05 V8 v2). multi_city rows res 9 317 / 350 / 67 (was 597 / 638 / 107, -45%): many multi-city homes were shared-point artefacts. suspect_bot 12 / 13 / 13 at both res (was 20 / 19): flag is per user at either res, so a user with three cities at only one res is flagged in all its rows, and city counts need not be equal. 2026-11-13 |
| home_overview (v2, D18) | overview notebook rerun after D18 | Hotspots gone: max homes in one res 10 cell ams 39, lon 93, pdx 85 (was 1,132 / 5,474 / 587); res 9 max 109 / 402 / 107. Funnel res 9 users -> >= 10 tweets -> >= 3 nights -> home -> high: ams 181,300 / 24,422 / 8,959 / 8,646 / 5,455; lon 823,414 / 241,992 / 133,861 / 130,174 / 95,008; pdx 96,664 / 22,346 / 10,476 / 10,087 / 7,181. Spearman homes vs population res 8 / 9 / 10: ams 0.82 / 0.71 / 0.46, lon 0.89 / 0.79 / 0.45, pdx 0.65 / 0.53 / 0.26 (unchanged: hotspots were few cells); homes per 1,000 residents res 9: 8.5 / 13.3 / 9.3. Median home nights 6 / 8 / 8, median user tweets (res 9) 48 / 64 / 73. 2026-11-13 |
| 07 V1 (D19, D20) | stays, work places, generic points | `visit_stay`: stays ams 954,349 / lon 13,571,341 / pdx 2,365,672, tweets 2,087,832 / 29,302,070 / 3,825,327, 3.4 / 4.2 / 2.5% at shared points with >= 100 users (generic rule removed 0.8k / 30k / 29k tweets vs the first run); users 8,788 / 131,803 / 10,246 (= home users). First run kept two generic points (Wikipedia London 20,561, Portland 13,485: they topped the work cells with 123 / 276 users); after the ~30 m rule (V0b: 4 / 9 / 2 points dropped) their cells fell to max_point_users 216 / 72. Work: ams 2,710 of 8,788 (31%), lon 47,366 of 131,803 (36%), pdx 3,961 of 10,246 (39%); median 6 / 6 / 7 work days; distance < 1 / 1-5 / 5+ km: ams 18 / 51 / 31%, lon 16 / 33 / 50%, pdx 20 / 40 / 39%. Top work cells: Schiphol, Amsterdam Centraal; Soho (267, the neighbourhood check-in point), Oxford Circus, Canary Wharf, Heathrow; PDX airport, downtown Portland. The < 1 km work places (~1 in 6) may partly be regular weekday spots near home; accepted (costs one cell per user in `visit`). 2026-11-13 |
| 08 V1 (D20) | `visit` size | Visits (stays outside home area and work cell) ams 607,958 / lon 7,664,317 / pdx 1,832,144 from 0.95M / 13.6M / 2.37M stays; share of stays removed as home / work 0.36 / 0.44 / 0.23 (lower than expected: home cells hold most nights, not most days). Users with a visit 8,232 / 125,969 / 9,862 (94-96%); visits per user 74 / 61 / 186; visit tweets 0.88M / 10.8M / 2.30M; visits at a shared point (>= 5 users) 23 / 23 / 30%. Portland: 3x the visits per user and the lowest home share -> V3 (heavy / automated accounts). 2026-11-13 |
| 08 V1b, V2 (D20) | distance from home; activity confound | Distance of visits < 1 / 1-5 / 5-10 / 10+ km: ams 18 / 56 / 20 / 6%, median 2.9 km; lon 18 / 35 / 23 / 24%, median 4.5 km; pdx 11 / 32 / 34 / 23%, median 6.1 km. V2 by active days 01-09 / 10-19 / 20-49 / 50-99 / 100+: distinct visited cells grow ~linearly (ams 5 / 8 / 16 / 35 / 101; lon 4 / 8 / 19 / 41 / 114; pdx 5 / 8 / 18 / 37 / 136), while cells per 10 active days is nearly flat (lon 6.6 / 5.7 / 5.8 / 5.8 / 5.7; ams 8.8 / 5.5 / 5.0 / 5.0 / 4.8; pdx 8.1 / 5.6 / 5.6 / 5.3 / 5.8): raw place counts are an activity measure; per-active-day rates are comparable across activity levels (except < 10 days). Visits per day ~0.7-1.0 everywhere except Portland 100+ days: 1.67 (heavy / automated accounts, V3). 2026-11-13 |
| work_overview, visits_overview | notebooks after 07 / 08 | Median commute ams 3.1 / lon 5.1 / pdx 3.7 km. Timing of stays (first tweet hour): work cells peak 09-15 on weekdays, home peaks late evening / night, other places show commute peaks (08, 18) on weekdays and a midday peak at weekends: the work label behaves like work. Work users' homes spread over the city, their work places concentrate in the centre (West End, City, Canary Wharf). Visits: Friday / Saturday busiest; median distinct visitors per visited res 9 cell 14 / 46 / 19. Res 10 visitor map of central London traces roads and rail lines: part of `visit` is tweeting in transit, not stays at places (cells without amenities drop out at POI labelling; flag for the student). Most visited cells are 50-85% shared-point visits (check-in venues). Concentration: in Portland a handful of users hold ~60% of all visits (Amsterdam ~30%, London smooth) -> automated accounts, decide with 08 V3. Places per 10 active days flat (~4-5.5) above ~10 active days. Example London user: 51 home nights, 20 work days, 340 visits on 54 cells, 148 days, mostly within a few km of home and work. 2026-11-13 |
| 08 V3 | heaviest visitors, concentration | Top 1% / 10% of users hold ams 47 / 72%, lon 19 / 56%, pdx 69 / 83% of visits. Top accounts are automated: pdx 618,017 visits on 1,168 days (529 a day, 17,890 cells), 246,345, 114,188, 94,971, 38,926 (five accounts ~61% of Portland's visits); ams 171,310 on 1,420 days (121 a day), 17,688 (123 a day); lon 25,616 on 169 days (152), 25,371 on 86 days (295), 14,523 on 99 days (147). People average ~1-2 visits per visit day; heavy humans in the top 10 sit at ~4-7 (often with high shared-point shares: check-in users). -> automated flag in `visit_user` (08 S3), threshold calibrated with V4. 2026-11-13 |
| 08 V4 | threshold for `automated` (visits per visit day) | Users / share of visits at >= 3 / 5 / 10 / 20 / 50: ams 379 / 79 / 10 / 3 / 2 users, 41.8 / 35.6 / 34.1 / 31.2 / 31.1%; lon 4,287 / 801 / 69 / 12 / 4, 14.9 / 5.6 / 2.0 / 1.2 / 0.9%; pdx 302 / 65 / 16 / 7 / 5, 68.0 / 64.9 / 63.1 / 61.5 / 60.7%. A few accounts carry almost all the excess (ams 2 users = 31%, pdx 5 = 61%). Between 5 and 10 the share barely moves in ams / pdx (+1.5 / +1.8 points) but adds 732 London users (heavy check-in humans, V3). -> 10 kept: flags 10 / 69 / 16 users, 34 / 2 / 63% of visits. 2026-11-13 |
| 08 S3 | `visit_user` built | 8,788 / 131,803 / 10,246 users (= visit_stay users); automated 10 / 69 / 16, holding 207,157 / 154,641 / 1,156,852 visits (34.1 / 2.0 / 63.1%, matches V4). Visits left for analysis: ams 400,801, lon 7,509,676, pdx 675,292. 2026-11-13 |
| C10 | hour-of-day profile, local vs UTC (D02, D03) | All tweets 2013-2017 by local hour. All three cities: low at 04-05h, peak at 20-21h. Share of tweets in window 20-08: ams 38.2%, lon 37.4%, pdx 36.2%; 22-07: 22.6 / 21.1 / 21.2%; 00-06: 9.4 / 8.4 / 9.4%. Legacy UTC 20-08 is ~12:00-00:00 local in Portland (69% of its tweets). 2026-11-07 |

## Change log
| Date | Change | Evidence |
|---|---|---|
| 2026-11-11 | 03: D16 `high` = >= 5 nights; dropped the 50%-of-nights condition | 03 (v3) V5 |
| 2026-11-11 | 03: added `min_user_tweets` = 10 on top of the night gate (3 tweets on 3 nights must not make a home) | user review |
| 2026-11-11 | 03: gate `min_home_nights` = 3 plus strict lead for nights / night_tweets (no gate gave 1-night homes) | D05 evidence |
| 2026-11-11 | 03 rewritten: methods nights / night_tweets / ratio, distinct nights, no user minimum, confidence tiers; new tables `home_user_cell_nights`, `home_user` | 03 (v1) row in check table |
| 2026-11-07 | Target switched to schema `revised` (same columns as `public` plus 5 provenance/repair columns: conversation_id_status, conversation_id_candidate, source_file_id, source_record, source_fragments; more users) | `select * from revised.tweet limit 100` |
| 2026-10-08 | Initial skeleton from review of `TWITTER_FINAL.ipynb` and `home_location_inference_tables.ipynb` | n/a |
