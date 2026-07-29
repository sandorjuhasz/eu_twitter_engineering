from pyspark.sql import SparkSession
from pyspark.sql.types import (
    StructType, StructField, StringType, ArrayType,
    LongType, BooleanType, FloatType
)
from pyspark.sql.functions import (
    col, lit, explode, udf, when, trim, regexp_replace
)
from pyspark import StorageLevel

import ujson as json
import ast
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
POSTGRES_JAR = "/mnt/common-hdd/ilyesvirag/postgresql-42.7.8.jar"
PG_DATABASE = "twitter_cities_v2"

TWEET_HASHTAG_TABLE = "tweet_hashtag"
TWEET_ENTITY_TABLE  = "tweet_entity_annotation"
TWEET_CONTEXT_TABLE = "tweet_context_annotation"


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
    """
    Convert an integer-like string column to Spark LongType.

    Accepted:
        123        -> 123
        123.0      -> 123
        123.000    -> 123
        empty/NULL -> NULL

    Rejected as NULL:
        non-integral decimals
        scientific notation
        non-numeric strings
    """
    value = trim(col(colname))

    return (
        when(value.isNull() | (value == ""), lit(None).cast("long"))
        .when(value.rlike(r"^[+-]?\d+$"), value.cast("long"))
        .when(
            value.rlike(r"^[+-]?\d+\.0+$"),
            regexp_replace(value, r"\.0+$", "").cast("long"),
        )
        .otherwise(lit(None).cast("long"))
    )


SAFE_LONG_COLUMNS = [
    "author_pinned_tweet_id",
    "author_pm_listed_count",
    "conversation_id",
    "in_reply_to_user_id",
    "tweet_pm_impression_count",
]


def normalize_and_convert_long_columns(df):
    """
    Harmonize the old and new raw schemas, then safely convert the selected
    integer-like string fields to LongType.

    The old schema lacks tweet_pm_impression_count, so the missing field is
    introduced as a typed NULL before applying the common conversion logic.
    """
    for column_name in SAFE_LONG_COLUMNS:
        if column_name not in df.columns:
            df = df.withColumn(column_name, lit(None).cast("string"))
        df = df.withColumn(column_name, safe_long(column_name))
    return df


# ============================================
# Parser helpers
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


def extract_hashtags(x):
    obj = parse_nested_string(x)
    hashtags = obj.get("hashtags", []) if isinstance(obj, dict) else []
    out = []
    for ht in hashtags:
        if isinstance(ht, dict):
            tag = ht.get("tag")
            if tag is not None:
                out.append(str(tag))
    return out


def extract_entities(x):
    obj = parse_nested_string(x)
    annotations = obj.get("annotations", []) if isinstance(obj, dict) else []
    out = []
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        entity_type = ann.get("type")
        entity_text = ann.get("normalized_text")
        if entity_text is None:
            continue
        out.append((
            str(entity_type) if entity_type is not None else "",
            str(entity_text)
        ))
    return out


def extract_context_annotations(x):
    obj = parse_nested_string(x)
    if not isinstance(obj, list):
        return []
    out = []
    for ca in obj:
        if not isinstance(ca, dict):
            continue
        domain = ca.get("domain", {})
        entity = ca.get("entity", {})
        if not isinstance(domain, dict) or not isinstance(entity, dict):
            continue
        out.append((
            str(domain.get("id")) if domain.get("id") is not None else None,
            domain.get("name"),
            domain.get("description"),
            str(entity.get("id")) if entity.get("id") is not None else None,
            entity.get("name"),
            entity.get("description"),
        ))
    return out


# ============================================
# UDFs
# ============================================

hashtags_udf = udf(extract_hashtags, ArrayType(StringType()))

entity_schema = ArrayType(StructType([
    StructField("entity_type", StringType(), True),
    StructField("entity_text", StringType(), True),
]))
entities_udf = udf(extract_entities, entity_schema)

context_schema = ArrayType(StructType([
    StructField("domain_id",          StringType(), True),
    StructField("domain_name",        StringType(), True),
    StructField("domain_description", StringType(), True),
    StructField("entity_id",          StringType(), True),
    StructField("entity_name",        StringType(), True),
    StructField("entity_description", StringType(), True),
]))
context_udf = udf(extract_context_annotations, context_schema)


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
        StructField("text",                      StringType(),  False),
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

cur.execute(f"""
DROP TABLE IF EXISTS {TWEET_HASHTAG_TABLE};
DROP TABLE IF EXISTS {TWEET_ENTITY_TABLE};
DROP TABLE IF EXISTS {TWEET_CONTEXT_TABLE};

SET ROLE twitter_project;

CREATE TABLE {TWEET_HASHTAG_TABLE} (
    city     VARCHAR(10) NOT NULL,
    tweet_id BIGINT      NOT NULL,
    hashtag  TEXT        NOT NULL
);

CREATE TABLE {TWEET_ENTITY_TABLE} (
    city        VARCHAR(10) NOT NULL,
    tweet_id    BIGINT      NOT NULL,
    entity_type VARCHAR(50),
    entity_text TEXT
);

CREATE TABLE {TWEET_CONTEXT_TABLE} (
    city               VARCHAR(10) NOT NULL,
    tweet_id           BIGINT      NOT NULL,
    domain_id          TEXT,
    domain_name        TEXT,
    domain_description TEXT,
    entity_id          TEXT,
    entity_name        TEXT,
    entity_description TEXT
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
    .appName("text_extras_v2")
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

    # Apply the same schema harmonization and safe long conversion used by
    # the corrected tweet-table pipeline.
    tweets_typed = normalize_and_convert_long_columns(tweets_raw)

    tweets = (
        tweets_typed
        .withColumn("city", lit(rename_city.get(city)))
        .dropDuplicates(["city", "id"])
        .select("city", "id", "entities", "context_annotations")
    )

    parsed = (
        tweets
        .withColumn("hashtags_array", hashtags_udf(col("entities")))
        .withColumn("entity_array",   entities_udf(col("entities")))
        .withColumn("context_array",  context_udf(col("context_annotations")))
    )

    parsed.persist(StorageLevel.MEMORY_AND_DISK)

    # tweet_hashtag
    (
        parsed
        .withColumn("hashtag", explode(col("hashtags_array")))
        .select(col("city"), col("id").alias("tweet_id"), col("hashtag"))
        .dropDuplicates(["city", "tweet_id", "hashtag"])
        .write.mode("append").jdbc(url=pg_url, table=TWEET_HASHTAG_TABLE, properties=pg_props)
    )

    # tweet_entity_annotation
    (
        parsed
        .withColumn("entity", explode(col("entity_array")))
        .select(
            col("city"),
            col("id").alias("tweet_id"),
            col("entity.entity_type").alias("entity_type"),
            col("entity.entity_text").alias("entity_text"),
        )
        .dropDuplicates(["city", "tweet_id", "entity_type", "entity_text"])
        .write.mode("append").jdbc(url=pg_url, table=TWEET_ENTITY_TABLE, properties=pg_props)
    )

    # tweet_context_annotation
    (
        parsed
        .withColumn("context", explode(col("context_array")))
        .select(
            col("city"),
            col("id").alias("tweet_id"),
            col("context.domain_id").alias("domain_id"),
            col("context.domain_name").alias("domain_name"),
            col("context.domain_description").alias("domain_description"),
            col("context.entity_id").alias("entity_id"),
            col("context.entity_name").alias("entity_name"),
            col("context.entity_description").alias("entity_description"),
        )
        .dropDuplicates(["city", "tweet_id", "domain_id", "entity_id"])
        .write.mode("append").jdbc(url=pg_url, table=TWEET_CONTEXT_TABLE, properties=pg_props)
    )

    parsed.unpersist()

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

-- tweet_hashtag
DELETE FROM tweet_hashtag a
USING tweet_hashtag b
WHERE a.ctid < b.ctid
  AND a.city = b.city
  AND a.tweet_id = b.tweet_id
  AND a.hashtag = b.hashtag;

-- tweet_entity_annotation
DELETE FROM tweet_entity_annotation a
USING tweet_entity_annotation b
WHERE a.ctid < b.ctid
  AND a.city = b.city
  AND a.tweet_id = b.tweet_id
  AND a.entity_type IS NOT DISTINCT FROM b.entity_type
  AND a.entity_text IS NOT DISTINCT FROM b.entity_text;

-- tweet_context_annotation
DELETE FROM tweet_context_annotation a
USING tweet_context_annotation b
WHERE a.ctid < b.ctid
  AND a.city = b.city
  AND a.tweet_id = b.tweet_id
  AND a.domain_id IS NOT DISTINCT FROM b.domain_id
  AND a.entity_id IS NOT DISTINCT FROM b.entity_id;

RESET ROLE;
""")

conn.commit()
cur.close()
conn.close()


# ============================================
# Indices
# ============================================

log("Adding indices")

conn = psql.connect(**json.load(open(CONNECTION_FILE)))
cur = conn.cursor()

cur.execute(f"""
SET ROLE twitter_project;

ALTER TABLE {TWEET_HASHTAG_TABLE} ADD PRIMARY KEY (city, tweet_id, hashtag);
CREATE INDEX idx_{TWEET_HASHTAG_TABLE}_tweet_id ON {TWEET_HASHTAG_TABLE} (tweet_id);
CREATE INDEX idx_{TWEET_HASHTAG_TABLE}_hashtag  ON {TWEET_HASHTAG_TABLE} (hashtag);

ALTER TABLE {TWEET_ENTITY_TABLE} ADD PRIMARY KEY (city, tweet_id, entity_type, entity_text);
CREATE INDEX idx_{TWEET_ENTITY_TABLE}_tweet_id ON {TWEET_ENTITY_TABLE} (tweet_id);
CREATE INDEX idx_{TWEET_ENTITY_TABLE}_type     ON {TWEET_ENTITY_TABLE} (entity_type);

CREATE INDEX idx_{TWEET_CONTEXT_TABLE}_tweet_id ON {TWEET_CONTEXT_TABLE} (tweet_id);
CREATE INDEX idx_{TWEET_CONTEXT_TABLE}_domain   ON {TWEET_CONTEXT_TABLE} (domain_id);
CREATE INDEX idx_{TWEET_CONTEXT_TABLE}_entity   ON {TWEET_CONTEXT_TABLE} (entity_id);

RESET ROLE;
""")

conn.commit()
cur.close()
conn.close()

log("All done")
