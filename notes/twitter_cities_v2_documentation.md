# twitter_cities_v2 — Database Documentation

**Database:** `twitter_cities_v2`  
**Built:** 2026-07-17  
**Coverage:** Amsterdam, London (Greater London), Portland (US) · 2012–2023  
**Source data:** ~162M geo-located tweets collected via Twitter/X Academic Research API  

---

## 1. Overview

`twitter_cities_v2` is the current production database. It replaces `twitter_cities_test`, which had a narrower tweet schema and some pipeline issues that dropped rows during ingestion.

All tables are owned by the shared role `twitter_project`. All DDL must be wrapped in `SET ROLE twitter_project; ... RESET ROLE;`.

### City naming

| Raw CSV directory | `city` column in DB |
|---|---|
| `amsterdam` | `amsterdam` |
| `Greater-London` | `london` |
| `portland` | `portland` |

---

## 2. Tables

### 2.1 `tweet` — core tweet table

Built by `code/03_database_setup/01_tweet_table.py`. One row per unique tweet.

| Column | Type | Description |
|---|---|---|
| `city` | VARCHAR(10) | City the tweet was collected for (`amsterdam`, `london`, `portland`) |
| `tweet_id` | BIGINT | Twitter tweet ID |
| `user_id` | BIGINT | Author's Twitter user ID |
| `created_at` | TIMESTAMP | When the tweet was posted (UTC) |
| `place_id` | VARCHAR(50) | Twitter Place ID attached to tweet (FK → `place.place_id`); NULL if none |
| `lat` | FLOAT | Latitude from exact coordinates (NULL if only a Place was attached) |
| `lon` | FLOAT | Longitude from exact coordinates |
| `conversation_id` | BIGINT | Thread root tweet ID |
| `text` | TEXT | Tweet text |
| `lang` | VARCHAR(10) | Language detected by Twitter |
| `tweet_type` | VARCHAR(20) | `original` / `reply` / `quote` / `retweet` — derived from `referenced_tweets` |
| `n_hashtags` | INTEGER | Number of hashtags in the tweet |
| `has_entities` | BOOLEAN | True if tweet has entity annotations (named entities) |
| `has_context_annotations` | BOOLEAN | True if tweet has context annotations (topic/domain labels) |
| `possibly_sensitive` | BOOLEAN | Twitter's own flag |
| `withheld` | TEXT | Geo-withholding info (rare; mostly NULL) |

**Primary key:** `(city, tweet_id)`  
**Indices:** `user_id`, `created_at`, `(city, created_at)`, `place_id`

**Row count:** 162,722,050

---

### 2.2 `twitter_user` — user profile table

Built by `code/03_database_setup/06_user_table.py`. One row per unique user (deduplicated across all cities and all tweet files).

| Column | Type | Description |
|---|---|---|
| `user_id` | BIGINT | Twitter user ID |
| `username` | VARCHAR(100) | **Twitter @handle** (e.g. `sandor_juhasz`) — from `author_username` in raw data |
| `account_created_at` | TIMESTAMP | When the Twitter account was created |
| `description` | TEXT | Profile bio text |
| `pm_tweet_count` | BIGINT | Number of tweets posted — snapshot at collection time (see note on `pm_`) |
| `pm_following_count` | BIGINT | Number of accounts followed — snapshot at collection time |
| `pm_followers_count` | BIGINT | Number of followers — snapshot at collection time |
| `verified` | BOOLEAN | Whether account was verified at collection time |
| `protected` | BOOLEAN | Whether account was protected at collection time |
| `withheld` | TEXT | Account withholding info (rare) |

**Primary key:** `user_id`  
**Index:** `username`

**Note — display name vs. handle:** `username` is the @handle used to log in. The display name (e.g. "Sandor Juhasz") was not stored in this table — it is available in the raw CSVs as `author_name`.

**Row count:** 2,846,531

---

### 2.3 `mention_network` — mention edges

Built by `code/03_database_setup/03_interaction_networks.py`. One row per (tweet, mentioned user) pair. A tweet mentioning 3 users produces 3 rows.

| Column | Type | Description |
|---|---|---|
| `city` | VARCHAR(10) | City |
| `tweet_id` | BIGINT | Tweet containing the mention |
| `created_at` | TIMESTAMP | Tweet timestamp |
| `user_id1_source` | BIGINT | Author of the tweet (the one doing the mentioning) |
| `user_id2_interaction` | BIGINT | User who was mentioned |

**Primary key:** `(city, user_id1_source, user_id2_interaction, tweet_id)`  
**Indices:** `tweet_id`, `user_id1_source`, `user_id2_interaction`

**Row count:** 124,420,664  
*(Much larger than old DB's 52.8M — the old pipeline dropped rows when processing files with the wrong column count.)*

**Important — what `mention_network` contains:** it captures ALL @mentions from ALL tweet types, extracted from `entities.mentions[*].id`. This means it includes mentions in retweets (`RT @username ...`), quote tweets, replies, and original tweets alike. It is a broad, noisy signal — not a proxy for direct conversations.

**Filtering to direct interactions:** use `reply_network` (direct replies only) or the `tweet` table filtered on `tweet_type = 'reply'` grouped by `conversation_id` for full thread reconstruction. The `tweet` table's `tweet_type` column (`original` / `reply` / `quote` / `retweet`) is the key to separating interaction types.

**Note on old DB:** the extraction logic in `twitter_cities_test` was identical — same `entities.mentions` source. The 52.8M vs 124.4M difference is entirely due to the old pipeline silently dropping ~half the raw files (41-column files failed against a 42-column schema).

---

### 2.4 `reply_network` — reply edges

Built by `code/03_database_setup/03_interaction_networks.py`. One row per tweet that is a direct reply.

| Column | Type | Description |
|---|---|---|
| `city` | VARCHAR(10) | City |
| `tweet_id` | BIGINT | ID of the reply tweet |
| `conversation_id` | BIGINT | Thread root tweet ID (links all tweets in a thread) |
| `created_at` | TIMESTAMP | Reply tweet timestamp |
| `user_id1_source` | BIGINT | Author of the reply |
| `user_id2_interaction` | BIGINT | User being replied to (`in_reply_to_user_id`) |

**Primary key:** `(city, user_id1_source, user_id2_interaction, tweet_id)`  
**Indices:** `tweet_id`, `user_id1_source`, `user_id2_interaction`

**Row count:** 69,370,856

---

### 2.5 `place` — Twitter Places reference table

Built by `code/03_database_setup/04_place_table.py`. Populated from `tables/place.csv`, which was itself constructed by `code/02_place_id_parsing/convert_places.py` from the raw Place JSON files.

| Column | Type | Description |
|---|---|---|
| `place_id` | VARCHAR(50) | Twitter Place ID |
| `place_name` | VARCHAR(200) | Short name (e.g. "Amsterdam") |
| `full_name` | VARCHAR(400) | Full name (e.g. "Amsterdam, Netherlands") |
| `country_code` | VARCHAR(10) | ISO country code |
| `place_type` | VARCHAR(50) | e.g. `city`, `neighborhood`, `poi` |
| `lon_min/max` | FLOAT | Bounding box longitude extents |
| `lat_min/max` | FLOAT | Bounding box latitude extents |
| `centroid_lon` | FLOAT | Centroid longitude |
| `centroid_lat` | FLOAT | Centroid latitude |
| `err` | FLOAT | Half-diameter of the bounding box in meters — proxy for spatial precision |

**Primary key:** `place_id`

**Row count:** 33,983  
**Note:** `err < 200` is used as a quality threshold in home location processing — tweets with only a Place attached (no exact coordinates) borrow the centroid if `err` is small enough.

---

### 2.6 `tweet_hashtag` — hashtag occurrences

Built by `code/03_database_setup/05_text_extras.py`. One row per hashtag per tweet.

| Column | Type | Description |
|---|---|---|
| `city` | VARCHAR(10) | City |
| `tweet_id` | BIGINT | Tweet |
| `hashtag` | TEXT | Hashtag text (without `#`, as returned by API) |

**Primary key:** `(city, tweet_id, hashtag)`  
**Indices:** `tweet_id`, `hashtag`

**Row count:** 80,312,536

---

### 2.7 `tweet_entity_annotation` — named entity mentions

Built by `code/03_database_setup/05_text_extras.py`. One row per named entity per tweet (from Twitter's NLP pipeline, e.g. persons, places, products).

| Column | Type | Description |
|---|---|---|
| `city` | VARCHAR(10) | City |
| `tweet_id` | BIGINT | Tweet |
| `entity_type` | VARCHAR(50) | Entity type (e.g. `Person`, `Place`, `Product`) |
| `entity_text` | TEXT | Normalized entity text |

**Primary key:** `(city, tweet_id, entity_type, entity_text)`  
**Indices:** `tweet_id`, `entity_type`

**Row count:** 116,008,810

---

### 2.8 `tweet_context_annotation` — topic/domain labels

Built by `code/03_database_setup/05_text_extras.py`. One row per domain×entity pair per tweet (Twitter's topic classification system, e.g. "Sports → Football").

| Column | Type | Description |
|---|---|---|
| `city` | VARCHAR(10) | City |
| `tweet_id` | BIGINT | Tweet |
| `domain_id` | TEXT | Twitter domain ID |
| `domain_name` | TEXT | Domain label (e.g. `Sports`) |
| `domain_description` | TEXT | Domain description |
| `entity_id` | TEXT | Twitter entity ID within the domain |
| `entity_name` | TEXT | Entity label (e.g. `Football`) |
| `entity_description` | TEXT | Entity description |

**Index:** `tweet_id`, `domain_id`, `entity_id`  
*(No primary key — Twitter does not guarantee uniqueness of domain+entity combinations per tweet.)*

**Row count:** 117,561,600

---

## 3. What `pm_` columns mean

`pm_` stands for **public metrics**. These come from the Twitter API's `public_metrics` field and represent **a snapshot at the time of data collection** (2022–2023 crawl), not at the time the tweet was posted.

| Column prefix | Captures |
|---|---|
| `author_pm_*` (in raw CSVs) | Follower/following/listed/tweet counts of the author at crawl time |
| `tweet_pm_*` (in raw CSVs) | Like/retweet/reply/quote/impression counts of the tweet at crawl time |

The user table stores the author `pm_` columns. Because each user appears in many tweet files (collected at slightly different times), there can be micro-variation in their counts across files. The deduplication step keeps one row per user (`DISTINCT ON (user_id) ORDER BY user_id`) — so the stored value is effectively an arbitrary snapshot from the crawl period.

**There is no time series of these metrics.** Each tweet was crawled once.

---

## 4. What is NOT in v2 (compared to old `twitter_cities_test`)

| Old table | Status in v2 | Reason |
|---|---|---|
| `tweet_extra` | Removed | Its columns (`lang`, `tweet_type`, etc.) were merged into `tweet` |
| `follower_network` | Not built | Follower data is too incomplete across all cities |

---

## 5. Row count comparison

| Table | twitter_cities_test | twitter_cities_v2 | Change |
|---|--:|--:|---|
| tweet | 162,729,490 | 164,241,427 | +1.51M (+0.93%) |
| mention_network | 52,803,620 | 125,375,467 | +137% (pipeline fix) |
| reply_network | 61,289,900 | 61,883,104 | +593K (+0.97%) |
| place | 34,097 | 33,983 | -114 (cleaner dedup) |
| tweet_context_annotation | 117,561,600 | 117,561,599 | -1 |
| tweet_entity_annotation | 116,008,810 | 116,008,811 | +1 |
| tweet_hashtag | 80,312,536 | 80,312,534 | -2 |
| tweet_extra | 164,241,420 | — | merged into tweet |
| follower_network | (partial) | — | not built |
| twitter_user | — | 2,847,711 | new table |

The large jump in `mention_network` is expected: the old pipeline used `inferSchema` and dropped rows whenever files had 41 vs. 42 columns. The v2 pipeline handles both schemas explicitly.

---

## 6. Build scripts

All scripts live in `code/03_database_setup/` and must be run from that directory.

| Step | Script | What it builds | Runtime |
|---|---|---|---|
| 00 | `00_database.py` | Creates the database | seconds |
| 01 | `01_tweet_table.py` | `tweet` | ~6h |
| 03 | `03_interaction_networks.py` | `mention_network`, `reply_network` | ~1–2h |
| 04 | `04_place_table.py` | `place` | minutes |
| 05 | `05_text_extras.py` | `tweet_hashtag`, `tweet_entity_annotation`, `tweet_context_annotation` | ~1–2h |
| 06 | `06_user_table.py` | `twitter_user` | ~1h |

`02_follower_table.py` is skipped — follower data incomplete.  
Launch order and logging handled by `notes/run_v2_build.sh`.

---

## 7. Next steps

- [ ] Investigate the ~1.5M row gap between `tweet_extra` (old DB, 164.2M) and `tweet` (v2, 162.7M) — suspected cause: `DROPMALFORMED` + stricter schema enforcement
- [ ] Rerun home location inference (`05_home_processing/`) against `twitter_cities_v2` — update connection string in notebooks
- [ ] Consider adding `author_name` (display name) to `twitter_user` if needed
