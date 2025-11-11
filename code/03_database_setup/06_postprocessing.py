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
query = """
-- add PK to tweet table on city, tweet_id
ALTER TABLE tweet ADD PRIMARY KEY (city, tweet_id);

-- add index to tweet table on user_id
CREATE INDEX idx_user_id ON tweet (user_id);

-- add PK to place table on place_id
ALTER TABLE place ADD PRIMARY KEY (place_id);

-- add PK to mention network user_id1_source, user_id2_interaction
ALTER TABLE mention_network ADD PRIMARY KEY (city, user_id1_source, user_id2_interaction);
-- add PK to reply network user_id1_source, user_id2_interaction
ALTER TABLE reply_network ADD PRIMARY KEY (city, user_id1_source, user_id2_interaction);

-- add index to reply network on tweet_id
CREATE INDEX idx_reply_tweet_id ON reply_network (city, tweet_id);

-- add index to mention network on tweet_id
CREATE INDEX idx_mention_tweet_id ON mention_network (city, tweet_id);

-- add index to reply network on conversation_id
CREATE INDEX idx_reply_conversation_id ON reply_network (city, conversation_id);


"""

# run above commands
cur.execute(query)
conn.commit()
cur.close()
conn.close()

