from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType, StructField, StringType, ArrayType,
    LongType, BooleanType, FloatType, IntegerType
)
from pyspark.sql.functions import (
    col, lit, size, udf, substring, to_timestamp,
    split, regexp_replace
)

import ujson as json
import ast
import re
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


# ============================================
# Logging
# ============================================

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def format_minutes(seconds):
    return f"{seconds / 60:.1f} min"


# ============================================
# Parser helpers (from Virag's new_tables.py)
# ============================================

def parse_nested_string(x):
    if x is None or x == "":
        return {}
    if isinstance(x, (dict, list)):
        return x
    x = str(x)
    try:
        return json.loads(x)
    except Exception:
        pass
    try:
        x = x.replace("nan", "None")
        return ast.literal_eval(x)
    except Exception:
        return {}


def get_tweet_type_from_ref(ref):
    if ref is None or str(ref).strip() in ["", "nan", "None"]:
        return "original"
    types = re.findall(r"type=([a-zA-Z_]+)", str(ref))
    if "replied_to" in types:
        return "reply"
    elif "quoted" in types:
        return "quote"
    elif "retweeted" in types:
        return "retweet"
    else:
        return "original"


def count_hashtags(x):
    obj = parse_nested_string(x)
    hashtags = obj.get("hashtags", []) if isinstance(obj, dict) else []
    return len([ht for ht in hashtags if isinstance(ht, dict) and ht.get("tag") is not None])


def check_entity_annotations(x):
    obj = parse_nested_string(x)
    if not isinstance(obj, dict):
        return False
    return any(
        isinstance(ann, dict) and ann.get("normalized_text") is not None
        for ann in obj.get("annotations", [])
    )


def check_context_annotations(x):
    obj = parse_nested_string(x)
    return isinstance(obj, list) and len(obj) > 0


# ============================================
# UDFs
# ============================================

tweet_type_udf        = udf(get_tweet_type_from_ref,       StringType())
count_hashtags_udf    = udf(count_hashtags,                 IntegerType())
has_entities_udf      = udf(check_entity_annotations,      BooleanType())
has_context_ann_udf   = udf(check_context_annotations,     BooleanType())


# ============================================
# Input schema
# There are two otherwise identical raw tweet schemas.
# Newer files contain tweet_pm_impression_count.
# ============================================

def make_tweets_schema(include_impression_count=True):
    fields = [
        StructField("attachments",              StringType(),  True),
        StructField("author_created_at",        StringType(),  True),
        StructField("author_description",       StringType(),  True),
        StructField("author_entities",          StringType(),  True),
        StructField("author_id",                LongType(),    True),
        StructField("author_location",          StringType(),  True),
        StructField("author_name",              StringType(),  True),
        StructField("author_pinned_tweet_id",   LongType(),    True),
        StructField("author_pm_followers_count",LongType(),    True),
        StructField("author_pm_following_count",LongType(),    True),
        StructField("author_pm_listed_count",   LongType(),    True),
        StructField("author_pm_tweet_count",    LongType(),    True),
        StructField("author_profile_image_url", StringType(),  True),
        StructField("author_protected",         BooleanType(), True),
        StructField("author_url",               StringType(),  True),
        StructField("author_username",          StringType(),  True),
        StructField("author_verified",          BooleanType(), True),
        StructField("author_withheld",          StringType(),  False),
        StructField("context_annotations",      StringType(),  True),
        StructField("conversation_id",          LongType(),    True),
        StructField("created_at",               StringType(),  False),
        StructField("edit_controls",            StringType(),  False),
        StructField("edit_history_tweet_ids",   StringType(),  True),
        StructField("entities",                 StringType(),  True),
        StructField("geo_coo_coordinates",      StringType(),  True),
        StructField("geo_coo_type",             StringType(),  True),
        StructField("geo_loc_name",             StringType(),  True),
        StructField("geo_place_id",             StringType(),  True),
        StructField("id",                       LongType(),    False),
        StructField("in_reply_to_user_id",      LongType(),    True),
        StructField("lang",                     StringType(),  True),
        StructField("possibly_sensitive",       BooleanType(), True),
        StructField("referenced_tweets",        StringType(),  True),
        StructField("reply_settings",           StringType(),  True),
        StructField("source",                   StringType(),  True),
        StructField("text",                     StringType(),  False),
    ]
    if include_impression_count:
        fields.append(StructField("tweet_pm_impression_count", LongType(), False))
    fields.extend([
        StructField("tweet_pm_like_count",    LongType(), False),
        StructField("tweet_pm_quote_count",   LongType(), False),
        StructField("tweet_pm_reply_count",   LongType(), False),
        StructField("tweet_pm_retweet_count", LongType(), False),
        StructField("withheld",               StringType(), False),
    ])
    return StructType(fields)


tweets_schema_new = make_tweets_schema(include_impression_count=True)
tweets_schema_old = make_tweets_schema(include_impression_count=False)

rename_city = {
    "amsterdam":     "amsterdam",
    "portland":      "portland",
    "Greater-London":"london",
}


# ============================================
# PostgreSQL table setup
# ============================================

log("Setting up PostgreSQL tweet table")

conn = psql.connect(**json.load(open(CONNECTION_FILE)))
cur = conn.cursor()

cur.execute("""
DROP TABLE IF EXISTS tweet;

SET ROLE twitter_project;

CREATE TABLE tweet
(
    city                    VARCHAR(10)                 NOT NULL,
    tweet_id                BIGINT                      NOT NULL,
    user_id                 BIGINT                      NOT NULL,
    created_at              TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    place_id                VARCHAR(50),
    lat                     FLOAT,
    lon                     FLOAT,
    conversation_id         BIGINT,
    text                    TEXT,
    author_username         VARCHAR(100),
    lang                    VARCHAR(10),
    tweet_type              VARCHAR(20),
    n_hashtags              INTEGER,
    has_entities            BOOLEAN,
    has_context_annotations BOOLEAN
);

RESET ROLE;
""")

conn.commit()
cur.close()
conn.close()

log("PostgreSQL tweet table created")


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
    .appName("tweet_table_v2")
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
# File helpers (from Virag's new_tables.py)
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

    # native lat/lon extraction — no Python UDF serialization overhead
    # geo_coo_coordinates format: "[lon, lat]"
    coords = split(regexp_replace(col("geo_coo_coordinates"), r"[\[\] ]", ""), ",")

    tweets = (
        tweets_raw
        .withColumn("city", lit(rename_city.get(city)))
        .dropDuplicates(["city", "id"])
        .withColumn("lat",                    coords.getItem(1).cast(FloatType()))
        .withColumn("lon",                    coords.getItem(0).cast(FloatType()))
        .withColumn("created_at",             to_timestamp(substring(col("created_at"), 1, 19), "yyyy-MM-dd HH:mm:ss"))
        .withColumn("tweet_type",             tweet_type_udf(col("referenced_tweets")))
        .withColumn("n_hashtags",             count_hashtags_udf(col("entities")))
        .withColumn("has_entities",           has_entities_udf(col("entities")))
        .withColumn("has_context_annotations",has_context_ann_udf(col("context_annotations")))
        .select(
            col("city"),
            col("id").alias("tweet_id"),
            col("author_id").alias("user_id"),
            col("created_at"),
            col("geo_place_id").alias("place_id"),
            col("lat"),
            col("lon"),
            col("conversation_id"),
            col("text"),
            col("author_username"),
            col("lang"),
            col("tweet_type"),
            col("n_hashtags"),
            col("has_entities"),
            col("has_context_annotations"),
        )
    )

    tweets.write.mode("append").jdbc(
        url=pg_url,
        table="tweet",
        properties=pg_props,
    )

    batch_elapsed  = time.perf_counter() - batch_start
    city_elapsed   = time.perf_counter() - city_start_time
    avg_per_batch  = city_elapsed / batch_index
    eta_seconds    = avg_per_batch * (n_batches - batch_index)

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
# Primary key and indices
# ============================================

log("Adding primary key and indices")

conn = psql.connect(**json.load(open(CONNECTION_FILE)))
cur = conn.cursor()

cur.execute("""
SET ROLE twitter_project;

ALTER TABLE tweet ADD PRIMARY KEY (city, tweet_id);

CREATE INDEX idx_tweet_user_id          ON tweet (user_id);
CREATE INDEX idx_tweet_created_at       ON tweet (created_at);
CREATE INDEX idx_tweet_city_created_at  ON tweet (city, created_at);
CREATE INDEX idx_tweet_place_id         ON tweet (place_id);

RESET ROLE;
""")

conn.commit()
cur.close()
conn.close()

log("All done")
