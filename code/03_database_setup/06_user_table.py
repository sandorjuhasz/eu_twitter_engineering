from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType, StructField, StringType,
    LongType, BooleanType, FloatType
)
from pyspark.sql.functions import col, substring, to_timestamp, regexp_replace

import ujson as json
import os
import csv
import time
from datetime import datetime
import psycopg2 as psql


# ============================================
# Settings
# ============================================

BATCH_SIZE = 500
CITIES = ["Greater-London", "amsterdam", "portland"]
DATA_ROOT = "/mnt/common-hdd/raw-sources/twitter-data/data/"
CONNECTION_FILE = "connection.json"
POSTGRES_JAR = "/mnt/common-hdd/sandorjuhasz-ab/postgresql-42.7.8.jar"
PG_DATABASE = "twitter_cities_v2"

USER_TABLE         = "twitter_user"
USER_STAGING_TABLE = "twitter_user_staging"


# ============================================
# Logging
# ============================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def format_minutes(seconds):
    return f"{seconds / 60:.1f} min"


# ============================================
# Input schema (two variants: with/without impression count)
# ============================================

def make_tweets_schema(include_impression_count=True):
    fields = [
        StructField("attachments",               StringType(),  True),
        StructField("author_created_at",         StringType(),  True),
        StructField("author_description",        StringType(),  True),
        StructField("author_entities",           StringType(),  True),
        StructField("author_id",                 LongType(),    True),
        StructField("author_location",           StringType(),  True),
        StructField("author_name",               StringType(),  True),
        StructField("author_pinned_tweet_id",    LongType(),    True),
        StructField("author_pm_followers_count", LongType(),    True),
        StructField("author_pm_following_count", LongType(),    True),
        StructField("author_pm_listed_count",    LongType(),    True),
        StructField("author_pm_tweet_count",     LongType(),    True),
        StructField("author_profile_image_url",  StringType(),  True),
        StructField("author_protected",          BooleanType(), True),
        StructField("author_url",                StringType(),  True),
        StructField("author_username",           StringType(),  True),
        StructField("author_verified",           BooleanType(), True),
        StructField("author_withheld",           StringType(),  True),
        StructField("context_annotations",       StringType(),  True),
        StructField("conversation_id",           LongType(),    True),
        StructField("created_at",                StringType(),  True),
        StructField("edit_controls",             StringType(),  True),
        StructField("edit_history_tweet_ids",    StringType(),  True),
        StructField("entities",                  StringType(),  True),
        StructField("geo_coo_coordinates",       StringType(),  True),
        StructField("geo_coo_type",              StringType(),  True),
        StructField("geo_loc_name",              StringType(),  True),
        StructField("geo_place_id",              StringType(),  True),
        StructField("id",                        LongType(),    False),
        StructField("in_reply_to_user_id",       LongType(),    True),
        StructField("lang",                      StringType(),  True),
        StructField("possibly_sensitive",        BooleanType(), True),
        StructField("referenced_tweets",         StringType(),  True),
        StructField("reply_settings",            StringType(),  True),
        StructField("source",                    StringType(),  True),
        StructField("text",                      StringType(),  False),
    ]
    if include_impression_count:
        fields.append(StructField("tweet_pm_impression_count", LongType(), True))
    fields.extend([
        StructField("tweet_pm_like_count",    LongType(), True),
        StructField("tweet_pm_quote_count",   LongType(), True),
        StructField("tweet_pm_reply_count",   LongType(), True),
        StructField("tweet_pm_retweet_count", LongType(), True),
        StructField("withheld",               StringType(), True),
    ])
    return StructType(fields)


tweets_schema_new = make_tweets_schema(include_impression_count=True)
tweets_schema_old = make_tweets_schema(include_impression_count=False)

rename_city = {
    "amsterdam":      "amsterdam",
    "portland":       "portland",
    "Greater-London": "london",
}


# ============================================
# PostgreSQL table setup
# ============================================

log("Setting up PostgreSQL tables")

conn = psql.connect(**json.load(open(CONNECTION_FILE)))
cur = conn.cursor()

cur.execute(f"""
DROP TABLE IF EXISTS {USER_TABLE};
DROP TABLE IF EXISTS {USER_STAGING_TABLE};

SET ROLE twitter_project;

CREATE TABLE {USER_STAGING_TABLE} (
    user_id            BIGINT,
    username           VARCHAR(100),
    account_created_at TIMESTAMP WITHOUT TIME ZONE,
    description        TEXT,
    pm_tweet_count     BIGINT,
    pm_following_count BIGINT,
    pm_followers_count BIGINT,
    verified           BOOLEAN,
    protected          BOOLEAN,
    withheld           TEXT
);

CREATE TABLE {USER_TABLE} (
    user_id            BIGINT      PRIMARY KEY,
    username           VARCHAR(100),
    account_created_at TIMESTAMP WITHOUT TIME ZONE,
    description        TEXT,
    pm_tweet_count     BIGINT,
    pm_following_count BIGINT,
    pm_followers_count BIGINT,
    verified           BOOLEAN,
    protected          BOOLEAN,
    withheld           TEXT
);

RESET ROLE;
""")

conn.commit()
cur.close()
conn.close()

log("PostgreSQL tables created")


# ============================================
# Spark setup
# ============================================

log("Starting Spark session")

spark = (
    SparkSession
    .builder
    .config("spark.driver.memory", "50g")
    .config("spark.sql.shuffle.partitions", "32")
    .config("spark.jars", POSTGRES_JAR)
    .appName("user_table_v2")
    .getOrCreate()
)

pg_url = f"jdbc:postgresql://localhost:5432/{PG_DATABASE}"
cfg = json.load(open(CONNECTION_FILE))
pg_props = {
    "user":     cfg["user"],
    "password": cfg["password"],
    "driver":   "org.postgresql.Driver",
    "batchsize":"300000",
}

log("Spark session started")


# ============================================
# File helpers
# ============================================

def get_city_input_paths(city):
    city_tweet_dir = os.path.join(DATA_ROOT, city, "tweets")
    files = [
        os.path.join(city_tweet_dir, f)
        for f in os.listdir(city_tweet_dir)
        if os.path.isfile(os.path.join(city_tweet_dir, f))
    ]
    return sorted(files)


def make_batches(items, batch_size):
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def read_header(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
    return [c.strip().replace("﻿", "") for c in header]


def split_files_by_schema(paths):
    old_files, new_files = [], []
    for path in paths:
        header = read_header(path)
        if "tweet_pm_impression_count" in header:
            new_files.append(path)
        else:
            old_files.append(path)
    return sorted(old_files), sorted(new_files)


def make_schema_labeled_batches(old_files, new_files, batch_size):
    batches = []
    for paths in make_batches(old_files, batch_size):
        batches.append({"schema_name": "old_no_impression", "schema": tweets_schema_old, "paths": paths})
    for paths in make_batches(new_files, batch_size):
        batches.append({"schema_name": "new_with_impression", "schema": tweets_schema_new, "paths": paths})
    return batches


def read_batch(paths, schema):
    return (
        spark.read
        .option("multiline", "true")
        .option("quote", '"')
        .option("escape", '"')
        .option("header", True)
        .option("inferSchema", False)
        .option("mode", "DROPMALFORMED")
        .schema(schema)
        .csv(paths)
    )


# ============================================
# Main transformation
# ============================================

def process_batch(batch, city, batch_index, n_batches, city_start_time):
    batch_start = time.perf_counter()

    tweets_raw = read_batch(batch["paths"], batch["schema"])

    users = (
        tweets_raw
        .filter(col("author_id").isNotNull())
        .select(
            col("author_id").alias("user_id"),
            col("author_username").alias("username"),
            to_timestamp(
                regexp_replace(substring(col("author_created_at"), 1, 19), " ", "T"),
                "yyyy-MM-dd'T'HH:mm:ss"
            ).alias("account_created_at"),
            col("author_description").alias("description"),
            col("author_pm_tweet_count").alias("pm_tweet_count"),
            col("author_pm_following_count").alias("pm_following_count"),
            col("author_pm_followers_count").alias("pm_followers_count"),
            col("author_verified").alias("verified"),
            col("author_protected").alias("protected"),
            col("author_withheld").alias("withheld"),
        )
        .dropDuplicates(["user_id"])
    )

    users.write.mode("append").jdbc(
        url=pg_url,
        table=USER_STAGING_TABLE,
        properties=pg_props,
    )

    batch_elapsed = time.perf_counter() - batch_start
    city_elapsed  = time.perf_counter() - city_start_time
    avg_per_batch = city_elapsed / batch_index
    eta_seconds   = avg_per_batch * (n_batches - batch_index)

    log(
        f"{city}: batch {batch_index}/{n_batches} done"
        f" | schema {batch['schema_name']}"
        f" | files {len(batch['paths'])}"
        f" | batch {format_minutes(batch_elapsed)}"
        f" | elapsed {format_minutes(city_elapsed)}"
        f" | ETA {format_minutes(eta_seconds)}"
    )


# ============================================
# Process all cities
# ============================================

overall_start = time.perf_counter()
log(f"Cities: {CITIES}")
log(f"BATCH_SIZE = {BATCH_SIZE}")

for city in CITIES:
    city_start = time.perf_counter()

    input_paths = get_city_input_paths(city)

    if not input_paths:
        log(f"{city}: no input files found, skipping")
        continue

    old_files, new_files = split_files_by_schema(input_paths)
    batches = make_schema_labeled_batches(old_files, new_files, BATCH_SIZE)
    n_batches = len(batches)

    all_batched_files = [f for b in batches for f in b["paths"]]
    assert len(input_paths) == len(all_batched_files), \
        f"File count mismatch for {city}: input={len(input_paths)}, batched={len(all_batched_files)}"
    assert len(set(all_batched_files)) == len(input_paths), \
        f"Duplicate or missing files in batches for {city}"

    log(
        f"{city}: starting"
        f" | files {len(input_paths):,}"
        f" | old-schema {len(old_files):,}"
        f" | new-schema {len(new_files):,}"
        f" | batches {n_batches:,}"
    )

    for i, batch in enumerate(batches, start=1):
        try:
            process_batch(batch, city, i, n_batches, city_start)
        except Exception as e:
            log(f"{city}: ERROR in batch {i}/{n_batches}: {repr(e)}")
            raise

    log(f"{city}: finished | elapsed {format_minutes(time.perf_counter() - city_start)}")

spark.stop()
log(f"All cities done | total {format_minutes(time.perf_counter() - overall_start)}")


# ============================================
# Deduplicate staging into final table, add index
# ============================================

log("Deduplicating staging into twitter_user")

conn = psql.connect(**json.load(open(CONNECTION_FILE)))
cur = conn.cursor()

cur.execute(f"""
SET ROLE twitter_project;

INSERT INTO {USER_TABLE}
SELECT DISTINCT ON (user_id)
    user_id, username, account_created_at, description,
    pm_tweet_count, pm_following_count, pm_followers_count,
    verified, protected, withheld
FROM {USER_STAGING_TABLE}
ORDER BY user_id;

CREATE INDEX idx_{USER_TABLE}_username ON {USER_TABLE} (username);

DROP TABLE {USER_STAGING_TABLE};

RESET ROLE;
""")

conn.commit()
cur.close()
conn.close()

log("All done")
