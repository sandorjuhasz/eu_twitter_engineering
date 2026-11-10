"""Build a deduplicated tweet-level interaction table from reply and mention networks.

Retweets and unmatched tweet records are excluded. A row represents one
city–tweet–source–target combination, classified as reply only (1),
mention only (2), or both (3). Self-interactions are retained here and
excluded when constructing the user-level networks.
"""

import json
import time
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


# ------------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------------
CONNECTION_PATH = "/home/ilyesvirag/twitter/venv/connection.json"

MENTION_TABLE = "mention_network"
REPLY_TABLE = "reply_network"
TWEET_TABLE = "tweet"

OUTPUT_TABLE = "interaction_table"

TEMP_MENTION_TABLE = "interaction_mentions_deduplicated"
TEMP_REPLY_TABLE = "interaction_replies_deduplicated"


# ------------------------------------------------------------------
# DATABASE CONNECTION
# ------------------------------------------------------------------
with open(CONNECTION_PATH, encoding="utf-8") as f:
    cfg = json.load(f)

engine = create_engine(
    URL.create(
        drivername="postgresql+psycopg2",
        username=cfg["user"],
        password=cfg["password"],
        host=cfg["host"],
        port=cfg["port"],
        database=cfg["database"],
    ),
    pool_pre_ping=True,
)


# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
def log(message):
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}",
        flush=True,
    )


def run_step(step_name, sql):
    log(f"START: {step_name}")
    started = time.time()

    with engine.begin() as connection:
        connection.execute(text(sql))

    elapsed_minutes = (time.time() - started) / 60
    log(f"FINISHED: {step_name} ({elapsed_minutes:.2f} minutes)")


def print_table_count(table_name):
    with engine.connect() as connection:
        n_rows = connection.execute(
            text(f"SELECT COUNT(*) FROM {table_name}")
        ).scalar_one()

    log(f"{table_name}: {n_rows:,} rows")


# ------------------------------------------------------------------
# 1. DEDUPLICATED MENTION EDGES
# ------------------------------------------------------------------
# One row per:
#   city × tweet_id × source user × target user
#
# Only records with a corresponding row in the tweet table are retained.
# Retweets and records with missing tweet_type are excluded.
# ------------------------------------------------------------------
run_step(
    "Create deduplicated mention edges",
    f"""
    DROP TABLE IF EXISTS {TEMP_MENTION_TABLE};

    CREATE UNLOGGED TABLE {TEMP_MENTION_TABLE} AS
    SELECT
        m.city AS city,
        m.tweet_id,
        MIN(m.created_at) AS created_at,
        m.user_id1_source,
        m.user_id2_interaction

    FROM {MENTION_TABLE} AS m

    INNER JOIN {TWEET_TABLE} AS t
        ON m.city = t.city
       AND m.tweet_id = t.tweet_id

    WHERE
        LOWER(TRIM(t.tweet_type)) <> 'retweet'

    GROUP BY
        m.city,
        m.tweet_id,
        m.user_id1_source,
        m.user_id2_interaction;

    CREATE INDEX idx_{TEMP_MENTION_TABLE}_key
        ON {TEMP_MENTION_TABLE} (
            city,
            tweet_id,
            user_id1_source,
            user_id2_interaction
        );

    ANALYZE {TEMP_MENTION_TABLE};
    """,
)

print_table_count(TEMP_MENTION_TABLE)


# ------------------------------------------------------------------
# 2. DEDUPLICATED REPLY EDGES
# ------------------------------------------------------------------
# One row per:
#   city × tweet_id × source user × target user
#
# Only records with a corresponding row in the tweet table are retained.
# Retweets and records with missing tweet_type are excluded.
# ------------------------------------------------------------------
run_step(
    "Create deduplicated reply edges",
    f"""
    DROP TABLE IF EXISTS {TEMP_REPLY_TABLE};

    CREATE UNLOGGED TABLE {TEMP_REPLY_TABLE} AS
    SELECT
        r.city AS city,
        r.tweet_id,
        MIN(r.created_at) AS created_at,
        r.user_id1_source,
        r.user_id2_interaction

    FROM {REPLY_TABLE} AS r

    INNER JOIN {TWEET_TABLE} AS t
        ON r.city = t.city
       AND r.tweet_id = t.tweet_id

    WHERE
        LOWER(TRIM(t.tweet_type)) <> 'retweet'

    GROUP BY
        r.city,
        r.tweet_id,
        r.user_id1_source,
        r.user_id2_interaction;

    CREATE INDEX idx_{TEMP_REPLY_TABLE}_key
        ON {TEMP_REPLY_TABLE} (
            city,
            tweet_id,
            user_id1_source,
            user_id2_interaction
        );

    ANALYZE {TEMP_REPLY_TABLE};
    """,
)

print_table_count(TEMP_REPLY_TABLE)


# ------------------------------------------------------------------
# 3. COMBINED INTERACTION EDGES
# ------------------------------------------------------------------
# interaction_type:
#   1 = reply only
#   2 = mention only
#   3 = both reply and mention
#
# "Both" means that the same:
#   city × tweet_id × source user × target user
# exists in both the reply and mention networks.
#
# Self-interactions are retained here and excluded later during network
# construction.
# ------------------------------------------------------------------
run_step(
    "Create combined interaction edge table",
    f"""
    DROP TABLE IF EXISTS {OUTPUT_TABLE};

    CREATE TABLE {OUTPUT_TABLE} AS
    SELECT
        COALESCE(r.city, m.city) AS city,
        COALESCE(r.tweet_id, m.tweet_id) AS tweet_id,
        COALESCE(r.created_at, m.created_at) AS created_at,

        COALESCE(
            r.user_id1_source,
            m.user_id1_source
        ) AS user_id1_source,

        COALESCE(
            r.user_id2_interaction,
            m.user_id2_interaction
        ) AS user_id2_interaction,

        CASE
            WHEN r.tweet_id IS NOT NULL
             AND m.tweet_id IS NOT NULL
                THEN 3

            WHEN r.tweet_id IS NOT NULL
                THEN 1

            ELSE 2
        END::SMALLINT AS interaction_type

    FROM {TEMP_REPLY_TABLE} AS r

    FULL OUTER JOIN {TEMP_MENTION_TABLE} AS m
        ON r.city = m.city
       AND r.tweet_id = m.tweet_id
       AND r.user_id1_source = m.user_id1_source
       AND r.user_id2_interaction = m.user_id2_interaction;

    CREATE UNIQUE INDEX idx_{OUTPUT_TABLE}_unique_edge
        ON {OUTPUT_TABLE} (
            city,
            tweet_id,
            user_id1_source,
            user_id2_interaction
        );

    CREATE INDEX idx_{OUTPUT_TABLE}_source_target
        ON {OUTPUT_TABLE} (
            user_id1_source,
            user_id2_interaction
        );

    CREATE INDEX idx_{OUTPUT_TABLE}_tweet_id
        ON {OUTPUT_TABLE} (tweet_id);

    CREATE INDEX idx_{OUTPUT_TABLE}_created_at
        ON {OUTPUT_TABLE} (created_at);

    CREATE INDEX idx_{OUTPUT_TABLE}_city
        ON {OUTPUT_TABLE} (city);

    CREATE INDEX idx_{OUTPUT_TABLE}_interaction_type
        ON {OUTPUT_TABLE} (interaction_type);

    ANALYZE {OUTPUT_TABLE};
    """,
)

print_table_count(OUTPUT_TABLE)


# ------------------------------------------------------------------
# 4. FINAL COUNTS
# ------------------------------------------------------------------
with engine.connect() as connection:
    counts = connection.execute(
        text(
            f"""
            SELECT
                COUNT(*) AS rows,
                COUNT(DISTINCT (city, tweet_id)) AS unique_tweets,

                COUNT(*) FILTER (
                    WHERE interaction_type = 1
                ) AS reply_only_rows,

                COUNT(*) FILTER (
                    WHERE interaction_type = 2
                ) AS mention_only_rows,

                COUNT(*) FILTER (
                    WHERE interaction_type = 3
                ) AS both_rows

            FROM {OUTPUT_TABLE}
            """
        )
    ).mappings().one()

for name, value in counts.items():
    log(f"{name}: {value:,}")


# ------------------------------------------------------------------
# 5. REMOVE INTERMEDIATE TABLES
# ------------------------------------------------------------------
run_step(
    "Drop intermediate tables",
    f"""
    DROP TABLE IF EXISTS {TEMP_MENTION_TABLE};
    DROP TABLE IF EXISTS {TEMP_REPLY_TABLE};
    """,
)


# ------------------------------------------------------------------
# FINAL
# ------------------------------------------------------------------
log(f"Finished. Final table: {OUTPUT_TABLE}")