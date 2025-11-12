#!/mnt/common-hdd/bokanyie/anaconda3/bin/python

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
conn = psql.connect(
    **json.load(open("connection.json"))
)
cur = conn.cursor()

# creating follower network table
create_follower_network_table = """
DROP TABLE IF EXISTS follower_network;

CREATE TABLE follower_network
(
    user_id1_source      BIGINT      NOT NULL, -- follower
    user_id2_target      BIGINT      NOT NULL  -- following
);

"""

# run above commands
cur.execute(create_follower_network_table)
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

# setting up postgres connection for spark
pg_url = "jdbc:postgresql://localhost:5432/twitter_cities_test"
pg_props = {
    "user": json.load(open("connection.json"))["user"],
    "password": json.load(open("connection.json"))["password"],
    "driver": "org.postgresql.Driver"
}

# schema for Amsterdam follower data
amsterdam_follower_schema = StructType([
    StructField("index", IntegerType(), True),  # The unnamed index column
    StructField("created_at", StringType(), True),
    StructField("description", StringType(), True),
    StructField("entities", StringType(), True),  # JSON string, can be parsed separately
    StructField("follower", StringType(), True),  # Appears to be empty/null in sample
    StructField("following", StringType(), True),  # Appears to be empty/null in sample
    StructField("id", LongType(), True),  # User ID
    StructField("location", LongType(), True),  # Appears to be a location ID
    StructField("name", StringType(), True),
    StructField("pinned_tweet_id", StringType(), True),
    StructField("profile_image_url", StringType(), True),
    StructField("protected", BooleanType(), True),
    StructField("public_metrics", StringType(), True),  # JSON string with dict
    StructField("url", StringType(), True),
    StructField("username", StringType(), True),
    StructField("verified", BooleanType(), True)
])

# schema for London follower data
london_follower_schema = StructType([
    StructField("protected", BooleanType(), True),
    StructField("verified", BooleanType(), True),
    StructField("username", StringType(), True),
    StructField("public_metrics", StringType(), True),  # JSON string with dict
    StructField("description", StringType(), True),
    StructField("name", StringType(), True),
    StructField("created_at", StringType(), True),
    StructField("profile_image_url", StringType(), True),
    StructField("id", LongType(), True),  # User ID
    StructField("url", StringType(), True),
    StructField("entities", StringType(), True),  # JSON string, can be parsed separately
    StructField("pinned_tweet_id", StringType(), True),
    StructField("location", LongType(), True),  # Appears to be a location ID
    StructField("following", StringType(), True)  # Appears to be empty/null in sample
])

schema_dict = {
    "amsterdam": amsterdam_follower_schema,
    "Greater-London": london_follower_schema
}

# processing each city's tweets
for city in ["amsterdam", "Greater-London"]:
    followers = (spark.read
        .option("multiline", "true")
        .option("quote", '"')
        .option("escape", "\\")
        .option("escape", '"')
        .csv(
            f'../../data/{city}/follower/',
            header="True",
            schema=schema_dict[city],
            mode="DROPMALFORMED",
        )
        # removing duplicates to allow for PK creation later
        .dropDuplicates(["user_id1_source", "user_id2_target"])
        .take(5)
    )
    print(followers)

