# Home location pipeline: decision log

Every choice that can change which hexagon a user gets as "home" is listed here, with its default,
why it matters and how to check it. The parameter names match `config.yaml` (not written yet).

**Status values:** `open` (not decided, needs evidence), `proposed` (default chosen, not yet checked against data),
`settled` (checked and agreed).

**How to use this file:** when you revisit a decision, change the default in `config.yaml`, run with a new
`--run-label`, compare the runs with the diagnostics, then update the entry (date, evidence, status).
Every run stores its parameters in `home_run.params`, so old results stay reproducible.

Origin: the first version of these rules comes from the `_zi` code (`TWITTER_FINAL.ipynb`) and
`home_location_inference_tables.ipynb`. "Legacy" below means what those notebooks do.

---

## D01. Signal: night-time tweets per hexagon
- **What:** a user's home is the hexagon where they tweet at night.
- **Legacy:** night = 20:00 to 08:00; hexagon = H3 at resolutions 10, 9, 8, computed separately.
- **Status:** proposed
- **Check:** `05_diagnostics.sql`, share of users with a home and share of their tweets in that hexagon, per city.

## D02. Night window hours
- **Parameters:** `night_start` = 20, `night_end` = 8
- **Legacy:** `hour < 8 or hour >= 20`
- **Status:** open
- **Check:** hour-of-day histogram of tweets per city (in local time). The night window should sit on the low
  part of the curve.

## D03. Clock for the night window (time zone)
- **Parameter:** `tz_mode` = `local` | `utc`
- **Legacy:** `utc`. `tweet.created_at` is `timestamp` (UTC); the notebooks call `extract(hour ...)` on it directly.
- **Problem:** 20:00-08:00 UTC is about 12:00-00:00 local in Portland (UTC-8 / UTC-7) and 21:00-09:00 or
  22:00-10:00 in Amsterdam. Portland "homes" are mostly picked from daytime tweets.
- **Default:** `local`, using `Europe/London`, `Europe/Amsterdam`, `America/Los_Angeles` (daylight saving handled by
  Postgres). `utc` stays available to reproduce legacy results.
- **Status:** proposed. Check C03 in `00_checks.sql` to confirm the column type.
- **Check:** night-hour histogram per city under both modes; detection rate per city under both modes.

## D04. Time window
- **Parameter:** `window` = 2013-01-01 to 2017-12-31 (inclusive), stored as `window_id = '2013-2017'`
- **Legacy:** `date_trunc('year', created_at) between date '2013-01-01' and date '2017-01-01'`. This works, and
  includes all of 2017, but only by accident of truncation. The new code uses an explicit half-open range
  (`>= 2013-01-01 and < 2018-01-01`).
- **Later:** yearly or rolling windows. The output schema already has `window_id`; the logic does not.
- **Status:** proposed

## D05. Minimum activity per user
- **Parameters:** `min_user_tweets` = 20, `min_night_per_cell` = 2
- **Legacy:** at least 20 located tweets in the window and city bboxes; a hexagon must have at least 2 night tweets
  to be a candidate.
- **Note:** the second threshold is applied per hexagon *after* roll-up to each resolution, so it is not the same
  tweets at res 10 and res 8.
- **Status:** open
- **Check:** how detection rate and home share change with 10 / 20 / 50 tweets and 1 / 2 / 3 night tweets.

## D06. Tweets with coordinates
- **Rule:** tweets with `lat` and `lon` are used as they are. `lat`/`lon` are 32-bit floats from the load
  (about 1 m precision), well below H3 res 10 (about 65 m edge), so no issue.
- **Status:** proposed

## D07. Tweets with only a Place (no coordinates)
- **Parameters:** `use_place_centroids` = true, `place_err_max` = 200
- **Legacy:** tweets without coordinates take the place centroid if `place.err < 200`.
- **Open points:**
  1. Unit of `err`. `twitter_cities_v2_documentation.md` says metres; the old notebooks never state it. If it is km,
     the filter does almost nothing. Check C05.
  2. Many tweets share one centroid, so the centroid's hexagon can win as "home" by sheer count.
- **Default:** keep them, but store a `src` flag (`gps` / `place_centroid`) so a run can exclude them.
- **Status:** open
- **Check:** share of homes whose winning cell has mostly centroid tweets; compare against a GPS-only run.

## D08. City bounding boxes
- **Rule:** a tweet belongs to a city if its (possibly centroid) coordinates fall inside that city's box:

  | city | lat_min | lat_max | lon_min | lon_max |
  |---|---|---|---|---|
  | london | 51.2867601 | 51.6918741 | -0.5103751 | 0.3340155 |
  | portland | 45.4325360 | 45.6528812 | -122.8367489 | -122.4720252 |
  | amsterdam | 52.2781742 | 52.4310638 | 4.7287776 | 5.0791622 |

- **Note:** these are rectangles. London's covers more than Greater London. The boxes do not overlap.
- **Status:** proposed

## D09. Home scope: per user or per user and city
- **Legacy:** one home per user across all cities (ranking is over all of the user's hexagons).
- **Open:** a user with tweets in two city boxes gets one home in one city. Check C08 for how many users this is.
- **Status:** open

## D10. Ranking of candidate hexagons
- **Parameter:** `ranking` = `ratio` (legacy)
- **Legacy:** `ratio = night tweets in hexagon / all tweets in hexagon`; highest wins; ties go to the hexagon with
  more total tweets. New code adds the cell id as last tie-break so reruns are deterministic.
- **Problem:** a hexagon with 2 of 2 tweets at night (ratio 1.0) beats one with 30 of 40 (0.75). Spots visited briefly at
  night can beat the real home.
- **Alternatives to compare:** most night tweets; ratio with shrinkage (e.g. add pseudo-counts); require a minimum
  share of the user's night tweets.
- **Status:** open
- **Check:** margin between best and second-best hexagon (stored as `ratio_second`), and how often different
  rankings choose different cells.

## D11. Tweet types
- **Parameter:** `tweet_types` = all
- **Legacy:** all rows in `tweet` are used, including retweets and quotes.
- **Open:** whether retweets and quotes carry a location that tells us where the user is. See C09 for the counts.
- **Status:** open

## D12. "No home" rule
- **Rule:** a user has a home at a resolution only if at least one hexagon has `min_night_per_cell` night tweets.
- **Legacy:** this is implicit. The ranking picks a "top" hexagon even when no hexagon qualifies, and the Y/N flag
  only ends up Y because the night count is NULL for it.
- **New code:** explicit. Users without a qualifying hexagon get no `user_home` row at that resolution.
- **Status:** proposed

## D13. Network edges "same home location"
- **Legacy:** `mention_network_same_homeloc_s*_zi` and `reply_network_same_homeloc_s*_zi` keep an edge if both users
  have a home flag in the same city box as the tweet. They do **not** compare hexagons, so the name overstates it.
- **Join key:** the legacy SQL joins `mention_network` / `reply_network` to `tweet` on `tweet_id` only; the key is
  `(city, tweet_id)`. Check C07.
- **New code:** `mention_network_home` / `reply_network_home`, joined on `(city, tweet_id)`. A stricter "same
  hexagon / within distance" variant can be added later and named accordingly.
- **Status:** open

## D14. Technical choices (not methodological)
- H3 computed once at res 10; res 9 and 8 via `h3_cell_to_parent`. Exact, since counts add up under roll-up.
- Intermediates are `UNLOGGED`; the result table `user_home` is a normal table.
- All DDL wrapped in `SET ROLE twitter_project; ... RESET ROLE;`.
- **Status:** proposed

---

## Open questions waiting for check results
| Check | Decides | Result |
|---|---|---|
| C02 | h3 available on v2? | |
| C03 | `created_at` type (D03) | |
| C05 | unit of `place.err` (D07) | |
| C07 | `tweet_id` unique across cities? (D13) | |
| C08 | users in more than one city (D09) | |
| C09 | tweet types in window (D11) | |

## Change log
| Date | Change | Evidence |
|---|---|---|
| 2026-10-08 | Initial skeleton from review of `TWITTER_FINAL.ipynb` and `home_location_inference_tables.ipynb` | n/a |
