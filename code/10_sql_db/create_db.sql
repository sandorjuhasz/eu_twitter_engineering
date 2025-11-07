-- Active: 1757665099998@@localhost@5432@twitter_cities_test

CREATE DATABASE twitter_cities_test
    WITH 
    OWNER = bokanyie    
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE = 'en_US.UTF-8'
    CONNECTION LIMIT = -1;

DROP TABLE IF EXISTS tweet_test;

CREATE TABLE tweet_test
(
    city VARCHAR(10) NOT NULL,
    tweet_id bigint NOT NULL,
    user_id bigint NOT NULL,
    created_at timestamp without time zone NOT NULL,
    place_id VARCHAR(50),
    lat FLOAT,
    lon FLOAT
);

# bulk insert test_tweet_table.csv
COPY tweet_test(tweet_id, user_id, created_at, place_id, lat, lon)
FROM '/home/bokanyie/urban_interactions/test_tweet_table.csv'
DELIMITER ','
CSV HEADER;