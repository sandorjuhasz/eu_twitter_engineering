#!/mnt/common-hdd/bokanyie/anaconda3/bin/python

from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, LongType, BooleanType, FloatType
from pyspark.sql.functions import col, substring, udf, lit
from pyspark.sql.functions import to_timestamp

import ujson as json

from ast import literal_eval


import psycopg2 as psql


# ============================================
# Setting up Postgres tables
# ============================================

# initializing tables with psycopg2
conn = psql.connect(**json.load(open("connection.json")))
cur = conn.cursor()

# creating tweet table
create_tweet_table = """
DROP TABLE IF EXISTS tweet;

CREATE TABLE tweet
(
    city VARCHAR(10) NOT NULL,
    tweet_id bigint NOT NULL,
    user_id bigint NOT NULL,
    created_at timestamp without time zone NOT NULL,
    place_id VARCHAR(50),
    lat FLOAT,
    lon FLOAT,
    conversation_id   BIGINT,
    text TEXT
);
"""

# run above commands
cur.execute(create_tweet_table)
conn.commit()
cur.close()
conn.close()


# ============================================
# Spark part to populate tables from data
# ============================================


# extracting lat/long coordinates from tweets
@udf(returnType=FloatType())
def get_lat(s):
    if s is not None:
        return float(literal_eval(s)[1])
    else:
        return None

@udf(returnType=FloatType())
def get_lon(s):
    if s is not None:
        return float(literal_eval(s)[0])
    else:
        return None
# initializing Spark session
spark = SparkSession \
    .builder\
    .config("spark.driver.memory", "50g")\
    .config("spark.jars","/mnt/common-hdd/bokanyie/postgresql-42.7.8.jar")\
    .appName("Python Spark SQL") \
    .getOrCreate()

pg_url = "jdbc:postgresql://localhost:5432/twitter_cities_test"
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
    StructField("author_entitites", StringType(), True),
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
    StructField("in_reply_to_user_id", LongType(), True),
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
rename_city = {
    "amsterdam" : "amsterdam",
    "portland" : "portland",
    "Greater-London" : "london"
}

for city in ["amsterdam", "portland", "Greater-London"]:
    tweets = (spark.read
        .option("multiline", "true")
        .option("quote", '"')
        .option("escape", "\\")
        .option("escape", '"')
        .csv(
            f'../../data/{city}/tweets/',
            header="True",
            schema=tweets_schema,
            mode="DROPMALFORMED",
        )
        .withColumn("city", lit(rename_city.get(city)))
        .withColumn("lat",get_lat(col("geo_coo_coordinates")))
        .withColumn("lon",get_lon(col("geo_coo_coordinates")))
        .select(
            col("city"),
            col("id"),
            col("author_id"),
            substring(col("created_at"),1,19).alias("created_at"),
            col("geo_place_id"),
            col("lat"),
            col("lon"),
            col("conversation_id"),
            col("text")
        )
        .withColumn("created_at", to_timestamp(col("created_at"), "yyyy-MM-dd HH:mm:ss"))
        # rename geo_place_id to place_id
        .withColumnRenamed("geo_place_id", "place_id")
        # rename id to tweet_id
        .withColumnRenamed("id", "tweet_id")
        # rename author_id to user_id
        .withColumnRenamed("author_id", "user_id")
        # ensure city, tweet_id is unique to be able to create PK later
        .dropDuplicates(["city", "tweet_id"])
        # take 1000 rows for testing
        .write
        .mode("append")
        .jdbc(
            url=pg_url,
            table="tweet",
            properties=pg_props
        )
    )

spark.stop()

# reopen psql connection to add PK and indices
conn = psql.connect(**json.load(open("connection.json")))
cur = conn.cursor()

query = """
-- add PK to tweet table on city, tweet_id
ALTER TABLE tweet ADD PRIMARY KEY (city, tweet_id);
-- add index to tweet table on user_id
CREATE INDEX idx_user_id ON tweet (user_id);
"""
cur.execute(query)
conn.commit()

cur.close()
conn.close()