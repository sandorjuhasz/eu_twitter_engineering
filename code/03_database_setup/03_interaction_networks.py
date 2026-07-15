from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, LongType, BooleanType, DateType, MapType, FloatType, ArrayType
from pyspark.sql.functions import from_json, get_json_object, col, unix_timestamp, substring, udf, floor, collect_list, lit, explode
from pyspark.sql.functions import max as pyspark_max, to_timestamp, get_json_object
from pyspark.sql.functions import min as pyspark_min

import psycopg2 as psql

from ast import literal_eval
import ujson as json

# ============================================
# Setting up Postgres tables
# ============================================

# initializing tables with psycopg2
conn = psql.connect(**json.load(open("connection.json")))
cur = conn.cursor()

# creating mention network table
create_mention_network_table = """
DROP TABLE IF EXISTS mention_network;

SET ROLE twitter_project;

CREATE TABLE mention_network
(
    city                 VARCHAR(10) NOT NULL,
    tweet_id             BIGINT      NOT NULL,
    created_at           TIMESTAMP   NOT NULL,
    user_id1_source      BIGINT      NOT NULL,  -- author
    user_id2_interaction BIGINT      NOT NULL  -- mentioned user
);

RESET ROLE;
"""

create_reply_network_table = """
DROP TABLE IF EXISTS reply_network;

SET ROLE twitter_project;

CREATE TABLE reply_network
(
    city                 VARCHAR(10) NOT NULL,
    tweet_id             BIGINT      NOT NULL,
    conversation_id      BIGINT,
    created_at           TIMESTAMP   NOT NULL,
    user_id1_source      BIGINT      NOT NULL,  -- author
    user_id2_interaction BIGINT      NOT NULL  -- replied user
);  

RESET ROLE;
"""

# run above commands
cur.execute(create_mention_network_table)
cur.execute(create_reply_network_table)
conn.commit()
cur.close()
conn.close()


# ============================================
# Spark part to populate tables from data
# ============================================

# initializing Spark session
spark = SparkSession \
    .builder\
    .config("spark.driver.memory", "50g")\
    .config("spark.jars","/mnt/common-hdd/sandorjuhasz-ab/postgresql-42.7.8.jar")\
    .appName("Python Spark SQL") \
    .getOrCreate()

# setting up postgres connection for spark
pg_url = "jdbc:postgresql://localhost:5432/twitter_cities_v2"
pg_props = {
    "user": json.load(open("connection.json"))["user"],
    "password": json.load(open("connection.json"))["password"],
    "driver": "org.postgresql.Driver",
    "batchsize": "300000"
}

# structure of tweets saved by Bence after pre-processing
tweets_schema = StructType(
    [
    StructField("attachments", StringType(), True),
    StructField("author_created_at", StringType(), True),
    StructField("author_description", StringType(), True),
    StructField("author_entities", StringType(), True),
    StructField("author_id", LongType(), True),
    StructField("author_location", StringType(), True),
    StructField("author_name", StringType(), True),
    StructField("author_pinned_tweet_id", LongType(), True),
    StructField("author_pm_followers_count", LongType(), True),
    StructField("author_pm_following_count", LongType(), True),
    StructField("author_pm_listed_count", LongType(), True),
    StructField("author_pm_tweet_count", LongType(), True),
    StructField("author_profile_image_url", StringType(), True),
    StructField("author_protected", BooleanType(), True),
    StructField("author_url", StringType(), True),
    StructField("author_username", StringType(), True),
    StructField("author_verified", BooleanType(), True),
    StructField("author_withheld", StringType(), False),
    StructField("context_annotations", StringType(), True),
    StructField("conversation_id", LongType(), True),
    StructField("created_at", StringType(), False),
    StructField("edit_controls", StringType(), False),
    StructField("edit_history_tweet_ids", StringType(), True),
    StructField("entities", StringType(), True),
    StructField("geo_coo_coordinates", StringType(), True),
    StructField("geo_coo_type", StringType(), True),
    StructField("geo_loc_name", StringType(), True),
    StructField("geo_place_id", StringType(), True),
    StructField("id", LongType(), False),
    StructField("in_reply_to_user_id", StringType(), True),
    StructField("lang", StringType(), True),
    StructField("possibly_sensitive", BooleanType(), True),
    StructField("referenced_tweets", StringType(), True),
    StructField("reply_settings", StringType(), True),
    StructField("source", StringType(), True),    
    StructField("text", StringType(), False),
    StructField("tweet_pm_like_count", LongType(), False),
    StructField("tweet_pm_quote_count", LongType(), False),
    StructField("tweet_pm_reply_count", LongType(), False),
    StructField("tweet_pm_retweet_count", LongType(), False),
    StructField("withheld", StringType(), False)
    # StructField("corrupt_record", StringType(), True)
    ]
)

# renaming cities for uniformity
rename_city = {
    "amsterdam" : "amsterdam",
    "portland" : "portland",
    "Greater-London" : "london"
}

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
# UDF for extracting mentions
extract_mentions_udf = udf(extract_mentions, ArrayType(StringType()))

# processing each city's tweets
for city in ["amsterdam", "portland", "Greater-London"]:

    # reading tweets data, common part for both mentions and replies
    tweets = (spark.read
        .option("multiline", "true")
        .option("quote", '"')
        .option("escape", "\\")
        .option("escape", '"')
        .csv(
            f'/mnt/common-hdd/raw-sources/twitter-data/data/{city}/tweets/',
            header="True",
            schema=tweets_schema,
            mode="DROPMALFORMED"
        )
        .withColumn("city", lit(rename_city.get(city)))
    )
   
   # getting mentions in each tweet
   # it's in a JSON field in the "entities" column
    mentions = (tweets
        .withColumn("mentions", explode(extract_mentions_udf(get_json_object(col("entities"), "$.mentions[*].id"))))
        # cast mentions to long
        .withColumn("user_id2_interaction", col("mentions").cast(LongType()))
        .filter(col("user_id2_interaction").isNotNull())
        .select(
            col("city"),
            col("id").alias("tweet_id"),
            substring(col("created_at"),1,19).alias("created_at"),
            col("author_id").alias("user_id1_source"),
            col("user_id2_interaction"),
        )
        .withColumn("created_at", to_timestamp(col("created_at"), "yyyy-MM-dd HH:mm:ss"))
        # remove duplicates to allow for PK creation later
        .dropDuplicates(["city","tweet_id", "user_id1_source", "user_id2_interaction"])
        .write
        .mode("append")
        .jdbc(
            url=pg_url,
            table="mention_network",
            properties=pg_props
        )
    )

    # getting replies
    # in_reply_to_user_id field gives the user being replied to
    # conversation_id groups tweets in the same conversation
    replies = (tweets
        .select(
            col("city"),
            col("id").alias("tweet_id"),
            col("conversation_id"),
            substring(col("created_at"),1,19).alias("created_at"),
            col("author_id").alias("user_id1_source"),
            col("in_reply_to_user_id").cast("double").cast("long").alias("user_id2_interaction"),
        )
        .filter(col("user_id2_interaction").isNotNull())
        .withColumn("created_at", to_timestamp(col("created_at"), "yyyy-MM-dd HH:mm:ss"))
        # remove duplicates to allow for PK creation later
        .dropDuplicates(["city", "tweet_id", "user_id1_source", "user_id2_interaction"])
        .write
        .mode("append")
        .jdbc(
            url=pg_url,
            table="reply_network",
            properties=pg_props
        )
    )

spark.stop()

# reopen psql connection to add PK and indexes
conn = psql.connect(**json.load(open("connection.json")))
cur = conn.cursor()

query = """
-- add PK to mention network user_id1_source, user_id2_interaction
ALTER TABLE mention_network ADD PRIMARY KEY (city, user_id1_source, user_id2_interaction, tweet_id);

-- add PK to reply network user_id1_source, user_id2_interaction
ALTER TABLE reply_network ADD PRIMARY KEY (city, user_id1_source, user_id2_interaction, tweet_id);
"""
cur.execute(query)
conn.commit()

cur.close()
conn.close()