from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType, StructField, StringType,
    LongType, BooleanType
)
from pyspark.sql.functions import (
    col, lit, explode, udf, substring, to_timestamp,
    get_json_object, when, trim, regexp_replace
)
from pyspark import StorageLevel

import psycopg2 as psql
import ujson as json
import os
import csv
import time
from datetime import datetime


# ============================================
# Settings
# ============================================

BATCH_SIZE = 500
CITIES = ["Greater-London", "amsterdam", "portland"]
DATA_ROOT = "/mnt/common-hdd/raw-sources/twitter-data/data/"
CONNECTION_FILE = "connection.json"
POSTGRES_JAR = "/mnt/common-hdd/ilyesvirag/postgresql-42.7.8.jar"
PG_DATABASE = "twitter_cities_v2"


# ============================================
# Logging
# ============================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def format_minutes(seconds):
    return f"{seconds / 60:.1f} min"


# ============================================
# Safe numeric conversion
# ============================================

def safe_long(colname):
    value = trim(col(colname))
    return (
        when(value.isNull() | (value == ""), lit(None).cast("long"))
        .when(value.rlike(r"^[+-]?\d+$"), value.cast("long"))
        .when(value.rlike(r"^[+-]?\d+\.0+$"),
              regexp_replace(value,r"\.0+$","").cast("long"))
        .otherwise(lit(None).cast("long"))
    )

SAFE_LONG_COLUMNS=[
    "author_pinned_tweet_id",
    "author_pm_listed_count",
    "conversation_id",
    "in_reply_to_user_id",
    "tweet_pm_impression_count",
]

def normalize_and_convert_long_columns(df):
    for c in SAFE_LONG_COLUMNS:
        if c not in df.columns:
            df=df.withColumn(c,lit(None).cast("string"))
        df=df.withColumn(c,safe_long(c))
    return df

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
        StructField("author_pinned_tweet_id",    StringType(),  True),
        StructField("author_pm_followers_count", LongType(),    True),
        StructField("author_pm_following_count", LongType(),    True),
        StructField("author_pm_listed_count",    StringType(),  True),
        StructField("author_pm_tweet_count",     LongType(),    True),
        StructField("author_profile_image_url",  StringType(),  True),
        StructField("author_protected",          BooleanType(), True),
        StructField("author_url",                StringType(),  True),
        StructField("author_username",           StringType(),  True),
        StructField("author_verified",           BooleanType(), True),
        StructField("author_withheld",           StringType(),  True),
        StructField("context_annotations",       StringType(),  True),
        StructField("conversation_id",           StringType(),  True),
        StructField("created_at",                StringType(),  True),
        StructField("edit_controls",             StringType(),  True),
        StructField("edit_history_tweet_ids",    StringType(),  True),
        StructField("entities",                  StringType(),  True),
        StructField("geo_coo_coordinates",       StringType(),  True),
        StructField("geo_coo_type",              StringType(),  True),
        StructField("geo_loc_name",              StringType(),  True),
        StructField("geo_place_id",              StringType(),  True),
        StructField("id",                        LongType(),    False),
        StructField("in_reply_to_user_id",       StringType(),  True),
        StructField("lang",                      StringType(),  True),
        StructField("possibly_sensitive",        BooleanType(), True),
        StructField("referenced_tweets",         StringType(),  True),
        StructField("reply_settings",            StringType(),  True),
        StructField("source",                    StringType(),  True),
        StructField("text",                      StringType(),  True),
    ]
    if include_impression_count:
        fields.append(StructField("tweet_pm_impression_count", StringType(), True))
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

cur.execute("""
DROP TABLE IF EXISTS mention_network;
DROP TABLE IF EXISTS reply_network;

SET ROLE twitter_project;

CREATE TABLE mention_network
(
    city                 VARCHAR(10) NOT NULL,
    tweet_id             BIGINT      NOT NULL,
    created_at           TIMESTAMP   NOT NULL,
    user_id1_source      BIGINT      NOT NULL,
    user_id2_interaction BIGINT      NOT NULL
);

CREATE TABLE reply_network
(
    city                 VARCHAR(10) NOT NULL,
    tweet_id             BIGINT      NOT NULL,
    conversation_id      BIGINT,
    created_at           TIMESTAMP   NOT NULL,
    user_id1_source      BIGINT      NOT NULL,
    user_id2_interaction BIGINT      NOT NULL
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
    .appName("interaction_networks_v2")
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
# UDF
# ============================================

def extract_mentions(mentions_json_str):
    if mentions_json_str is None:
        return []
    try:
        parsed = json.loads(mentions_json_str)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x is not None]
        return [str(parsed)]
    except Exception:
        s = str(mentions_json_str).strip().strip('"')
        return [s] if s else []

from pyspark.sql.types import ArrayType
extract_mentions_udf = udf(extract_mentions, ArrayType(StringType()))


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
    tweets_typed = normalize_and_convert_long_columns(tweets_raw)

    tweets = (
        tweets_typed
        .withColumn("city", lit(rename_city.get(city)))
        .select("city", "id", "created_at", "author_id",
                "entities", "in_reply_to_user_id", "conversation_id")
    )

    tweets.persist(StorageLevel.MEMORY_AND_DISK)

    # mention_network
    (
        tweets
        .withColumn("mentions", explode(extract_mentions_udf(get_json_object(col("entities"), "$.mentions[*].id"))))
        .withColumn("user_id2_interaction", col("mentions").cast(LongType()))
        .filter(col("user_id2_interaction").isNotNull())
        .select(
            col("city"),
            col("id").alias("tweet_id"),
            to_timestamp(substring(col("created_at"), 1, 19), "yyyy-MM-dd HH:mm:ss").alias("created_at"),
            col("author_id").alias("user_id1_source"),
            col("user_id2_interaction"),
        )
        .dropDuplicates(["city", "tweet_id", "user_id1_source", "user_id2_interaction"])
        .write.mode("append").jdbc(url=pg_url, table="mention_network", properties=pg_props)
    )

    # reply_network
    (
        tweets
        .select(
            col("city"),
            col("id").alias("tweet_id"),
            col("conversation_id"),
            to_timestamp(substring(col("created_at"), 1, 19), "yyyy-MM-dd HH:mm:ss").alias("created_at"),
            col("author_id").alias("user_id1_source"),
            col("in_reply_to_user_id").alias("user_id2_interaction"),
        )
        .filter(col("user_id2_interaction").isNotNull())
        .dropDuplicates(["city", "tweet_id", "user_id1_source", "user_id2_interaction"])
        .write.mode("append").jdbc(url=pg_url, table="reply_network", properties=pg_props)
    )

    tweets.unpersist()

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
# Global deduplication
# ============================================

log("Removing global duplicates")

conn = psql.connect(**json.load(open(CONNECTION_FILE)))
cur = conn.cursor()

cur.execute("""
SET ROLE twitter_project;

DELETE FROM mention_network a
USING mention_network b
WHERE a.ctid < b.ctid
  AND a.city = b.city
  AND a.tweet_id = b.tweet_id
  AND a.user_id1_source = b.user_id1_source
  AND a.user_id2_interaction = b.user_id2_interaction;

DELETE FROM reply_network a
USING reply_network b
WHERE a.ctid < b.ctid
  AND a.city = b.city
  AND a.tweet_id = b.tweet_id
  AND a.user_id1_source = b.user_id1_source
  AND a.user_id2_interaction = b.user_id2_interaction;

RESET ROLE;
""")

conn.commit()
cur.close()
conn.close()

log("Global deduplication done")


# ============================================
# Primary keys and indices
# ============================================

log("Adding primary keys and indices")

conn = psql.connect(**json.load(open(CONNECTION_FILE)))
cur = conn.cursor()

cur.execute("""
SET ROLE twitter_project;

ALTER TABLE mention_network ADD PRIMARY KEY (city, user_id1_source, user_id2_interaction, tweet_id);
ALTER TABLE reply_network   ADD PRIMARY KEY (city, user_id1_source, user_id2_interaction, tweet_id);

CREATE INDEX idx_mention_network_tweet_id  ON mention_network (tweet_id);
CREATE INDEX idx_mention_network_user1     ON mention_network (user_id1_source);
CREATE INDEX idx_mention_network_user2     ON mention_network (user_id2_interaction);

CREATE INDEX idx_reply_network_tweet_id    ON reply_network (tweet_id);
CREATE INDEX idx_reply_network_user1       ON reply_network (user_id1_source);
CREATE INDEX idx_reply_network_user2       ON reply_network (user_id2_interaction);

RESET ROLE;
""")

conn.commit()
cur.close()
conn.close()

log("All done")
