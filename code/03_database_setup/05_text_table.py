#!/mnt/common-hdd/bokanyie/anaconda3/bin/python

from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, LongType, BooleanType, DateType, MapType, FloatType, ArrayType
from pyspark.sql.functions import from_json, get_json_object, col, unix_timestamp, substring, udf, floor, collect_list, lit
from pyspark.sql.functions import max as pyspark_max, to_timestamp
from pyspark.sql.functions import min as pyspark_min

from ast import literal_eval
import ujson as json

import psycopg2 as psql


# ============================================
# Setting up Postgres tables
# ============================================

# initializing tables with psycopg2
conn = psql.connect(
    database = "twitter_cities_test",
    user = "bokanyie", 
    host= 'localhost',
    password = open("password.txt", "r").read().strip(),
    port = 5432
)
cur = conn.cursor()

# creating text table
create_text_table = """
DROP TABLE IF EXISTS text;

CREATE TABLE text
(
    city               VARCHAR(10) NOT NULL,
    tweet_id          BIGINT      NOT NULL,
    user_id           BIGINT      NOT NULL,
    conversation_id   BIGINT,
    created_at        TIMESTAMP   NOT NULL,
    tweet_text        TEXT        NOT NULL
);

"""

# run above commands
cur.execute(create_text_table)
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
    .config("spark.jars","/mnt/common-hdd/bokanyie/postgresql-42.7.8.jar")\
    .appName("Python Spark SQL") \
    .getOrCreate()

pg_url = "jdbc:postgresql://localhost:5432/twitter_cities_test"
pg_props = {
    "user": "bokanyie",
    "password": "eCIt22X9YQHZwrWzw1JjvzB3QAI8iRSe",
    "driver": "org.postgresql.Driver"
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
        .select(
            col("city"),
            col("id").alias("tweet_id"),
            col("author_id").alias("user_id"),
            col("conversation_id"),
            substring(col("created_at"),1,19).alias("created_at"),
            col("text").alias("tweet_text")
        )
        .withColumn("created_at", to_timestamp(col("created_at"), "yyyy-MM-dd HH:mm:ss"))
        .write
        .jdbc(
            url=pg_url,
            table="text",
            mode="append",
            properties=pg_props
        )
    )

spark.stop()