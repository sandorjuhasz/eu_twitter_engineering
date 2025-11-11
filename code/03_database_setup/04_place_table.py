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
    database = "twitter_cities_test",
    user = "bokanyie", 
    host= 'localhost',
    password = open("password.txt", "r").read().strip(),
    port = 5432
)
cur = conn.cursor()

# creating place table
# header place_id,place_name,full_name,country_code,place_type,lon_min,lon_max,lat_min,lat_max,centroid_lon,centroid_lat,err
create_place_table = """
DROP TABLE IF EXISTS place;

CREATE TABLE place
(
    place_id            VARCHAR(50) NOT NULL,
    place_name         VARCHAR(200),
    full_name          VARCHAR(400),
    country_code       VARCHAR(10),
    place_type         VARCHAR(50),
    lon_min            FLOAT,
    lon_max            FLOAT,
    lat_min            FLOAT,
    lat_max            FLOAT,
    centroid_lon      FLOAT,
    centroid_lat      FLOAT,
    err               FLOAT
);

"""

# run above commands
cur.execute(create_place_table)
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
    "user": "bokanyie",
    "password": open("password.txt", "r").read().strip(),
    "driver": "org.postgresql.Driver"
}

place_schema = StructType([
    StructField("place_id", StringType(), True),
    StructField("place_name", StringType(), True),
    StructField("full_name", StringType(), True),
    StructField("country_code", StringType(), True),
    StructField("place_type", StringType(), True),
    StructField("lon_min", FloatType(), True),
    StructField("lon_max", FloatType(), True),
    StructField("lat_min", FloatType(), True),
    StructField("lat_max", FloatType(), True),
    StructField("centroid_lon", FloatType(), True),
    StructField("centroid_lat", FloatType(), True),
    StructField("err", FloatType(), True)
])

place = (
    spark.read
    .csv(
        '../../tables/place.csv',
        header=True,
        schema=place_schema
    )
    # filter if place_id = 'Portland' or 'suite 330' (checked database and these are invalid rows)
    .filter(~col("place_id").isin("Portland", "suite 330"))
    # removing duplicates to allow for PK creation later
    .dropDuplicates(["place_id"])
    .write
    .mode('append')
    .jdbc(
        url=pg_url,
        table='place',
        properties=pg_props
    )
)

spark.stop()
