"""Build the London conversation table from tweets.
Conversations are constructed from observed original tweets, replies and quote tweets.
Retweets are excluded from that text but can help recover a missing root.
The result is the PostgreSQL table thread_table_london.
"""

import json
import time
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# Settings
CONNECTION_PATH = "/home/ilyesvirag/twitter/venv/connection.json"

TWEET_TABLE = "tweet"
OUTPUT_TABLE = "thread_table_london"

CITY = "london"

TEMP_TWEETS = "thread_tweets_london"
TEMP_CORE = "thread_core_london"
TEMP_RETWEETS = "thread_retweets_london"

# Database Connection
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

# Helpers
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

    log(f"FINISHED: {step_name} ({(time.time() - started) / 60:.2f} minutes)")

def print_table_count(table_name):
    with engine.connect() as connection:

        n_rows = connection.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM {table_name}
                """
            )
        ).scalar_one()

    log(
        f"{table_name}: "
        f"{n_rows:,} rows"
    )

# 1. Deduplicate London Tweets
# Rebuild this table from the source data; downstream outputs are recreated by later steps.
run_step(
    "Create deduplicated London tweet table",
    f"""
    DROP TABLE IF EXISTS {TEMP_TWEETS};
    CREATE UNLOGGED TABLE {TEMP_TWEETS} AS
    SELECT DISTINCT ON (
        city,
        tweet_id
    )
        city,
        tweet_id,
        conversation_id,
        user_id,
        created_at,
        tweet_type,
        text
    FROM {TWEET_TABLE}
    WHERE city = '{CITY}'
      AND conversation_id IS NOT NULL
    ORDER BY
        city,
        tweet_id,
        created_at;
    CREATE UNIQUE INDEX idx_{TEMP_TWEETS}_tweet
        ON {TEMP_TWEETS} (
            city,
            tweet_id
        );
    CREATE INDEX idx_{TEMP_TWEETS}_conversation
        ON {TEMP_TWEETS} (
            city,
            conversation_id
        );
    CREATE INDEX idx_{TEMP_TWEETS}_type
        ON {TEMP_TWEETS} (
            tweet_type
        );
    ANALYZE {TEMP_TWEETS};
    """,
)

print_table_count(TEMP_TWEETS)

# 2. Construct Observed Threads
# A thread contains its observed root plus observed replies.
# A quote tweet can itself be the root of a new conversation.
# Retweets are excluded from the observed thread text.
run_step(
    "Create observed threads",
    f"""
    DROP TABLE IF EXISTS {TEMP_CORE};
    CREATE UNLOGGED TABLE {TEMP_CORE} AS
    SELECT
        city,
        conversation_id,
        COUNT(*)
            AS n_tweets_core,
        COUNT(*) FILTER (
            WHERE LOWER(TRIM(tweet_type)) = 'reply'
        ) AS n_reply,
        COUNT(*) FILTER (
            WHERE LOWER(TRIM(tweet_type)) = 'quote'
        ) AS n_quote,
        COUNT(DISTINCT user_id)
            AS n_users_core,
        BOOL_OR(
            tweet_id::TEXT
            = conversation_id::TEXT
        ) AS has_root,
        MIN(created_at)
            AS first_created_at,
        MAX(created_at)
            AS last_created_at,
        EXTRACT(
            EPOCH FROM (
                MAX(created_at)
                - MIN(created_at)
            )
        ) / 60.0
            AS duration_minutes,
        MAX(text) FILTER (
            WHERE
                tweet_id::TEXT
                = conversation_id::TEXT
        ) AS observed_root_text,
        STRING_AGG(
            COALESCE(text, ''),
            ' '
            ORDER BY
                created_at,
                tweet_id
        ) AS core_thread_text
    FROM {TEMP_TWEETS}
    WHERE
        LOWER(TRIM(tweet_type))
        IN (
            'original',
            'reply',
            'quote'
        )
    GROUP BY
        city,
        conversation_id;
    CREATE UNIQUE INDEX idx_{TEMP_CORE}_conversation
        ON {TEMP_CORE} (
            city,
            conversation_id
        );
    ANALYZE {TEMP_CORE};
    """,
)

print_table_count(TEMP_CORE)

# 3. Retweet-Based Root-Text Candidates
run_step(
    "Create retweet-based root text candidates",
    f"""
    DROP TABLE IF EXISTS {TEMP_RETWEETS};
    CREATE UNLOGGED TABLE {TEMP_RETWEETS} AS
    WITH retweet_candidates AS (
        SELECT
            city,
            conversation_id,
            tweet_id,
            text,
            BTRIM(
                REGEXP_REPLACE(
                    text,
                    '^[[:space:]]*RT[[:space:]]+@[A-Za-z0-9_]+:[[:space:]]*',
                    '',
                    'i'
                )
            ) AS candidate_with_colon,
            BTRIM(
                REGEXP_REPLACE(
                    text,
                    '^[[:space:]]*RT[[:space:]]+@[A-Za-z0-9_]+[[:space:]]+',
                    '',
                    'i'
                )
            ) AS candidate_without_colon
        FROM {TEMP_TWEETS}
        WHERE
            LOWER(TRIM(tweet_type))
                = 'retweet'
            AND COALESCE(
                text,
                ''
            ) ~* '^[[:space:]]*RT[[:space:]]+@'
    ),
    candidates AS (
        SELECT
            city,
            conversation_id,
            tweet_id,
            CASE
                WHEN candidate_with_colon <> text
                    THEN candidate_with_colon
                WHEN candidate_without_colon <> text
                    THEN candidate_without_colon
                ELSE NULL
            END AS reconstructed_text
        FROM retweet_candidates
    ),
    candidate_counts AS (
        SELECT
            city,
            conversation_id,
            reconstructed_text,
            COUNT(*)
                AS n_occurrences
        FROM candidates
        WHERE reconstructed_text IS NOT NULL
          AND reconstructed_text <> ''
        GROUP BY
            city,
            conversation_id,
            reconstructed_text
    ),
    ranked AS (
        SELECT
            city,
            conversation_id,
            reconstructed_text,
            n_occurrences,
            ROW_NUMBER() OVER (
                PARTITION BY
                    city,
                    conversation_id
                ORDER BY
                    n_occurrences DESC,
                    LENGTH(
                        reconstructed_text
                    ) DESC
            ) AS candidate_rank
        FROM candidate_counts
    ),
    retweet_counts AS (
        SELECT
            city,
            conversation_id,
            COUNT(
                DISTINCT tweet_id
            ) AS n_retweet
        FROM candidates
        GROUP BY
            city,
            conversation_id
    )
    SELECT
        r.city,
        r.conversation_id,
        r.n_retweet,
        x.reconstructed_text
            AS retweet_root_text,
        x.n_occurrences
            AS retweet_root_text_support
    FROM retweet_counts AS r
    LEFT JOIN ranked AS x
        ON r.city = x.city
       AND r.conversation_id
           = x.conversation_id
       AND x.candidate_rank = 1;
    CREATE UNIQUE INDEX idx_{TEMP_RETWEETS}_conversation
        ON {TEMP_RETWEETS} (
            city,
            conversation_id
        );
    ANALYZE {TEMP_RETWEETS};
    """,
)

print_table_count(TEMP_RETWEETS)

# 4. Create Final Thread Table
run_step(
    "Create final thread table",
    f"""
    DROP TABLE IF EXISTS {OUTPUT_TABLE};
    CREATE TABLE {OUTPUT_TABLE} AS
    SELECT
        c.city,
        c.conversation_id,
        c.n_tweets_core,
        c.n_reply,
        c.n_quote,
        c.n_users_core,
        c.has_root,
        COALESCE(
            r.n_retweet,
            0
        ) AS n_retweet,
        CASE
            WHEN COALESCE(
                r.n_retweet,
                0
            ) > 0
                THEN TRUE
            ELSE FALSE
        END AS has_retweet,
        CASE
            WHEN c.observed_root_text
                 IS NOT NULL
                THEN c.observed_root_text
            WHEN r.retweet_root_text
                 IS NOT NULL
                THEN r.retweet_root_text
            ELSE NULL
        END AS root_text,
        CASE
            WHEN c.observed_root_text
                 IS NOT NULL
                THEN 'observed'
            WHEN r.retweet_root_text
                 IS NOT NULL
                THEN 'retweet'
            ELSE NULL
        END AS root_text_source,
        CASE
            WHEN c.observed_root_text IS NULL
             AND r.retweet_root_text IS NOT NULL
                THEN TRUE
            ELSE FALSE
        END AS root_reconstructed,
        r.retweet_root_text_support,
        c.first_created_at,
        c.last_created_at,
        c.duration_minutes,
        c.core_thread_text,
        CASE
            WHEN c.observed_root_text
                 IS NOT NULL
                THEN c.core_thread_text
            WHEN r.retweet_root_text
                 IS NOT NULL
                THEN
                    r.retweet_root_text
                    || ' '
                    || c.core_thread_text
            ELSE c.core_thread_text
        END AS corrected_thread_text
    FROM {TEMP_CORE} AS c
    LEFT JOIN {TEMP_RETWEETS} AS r
        ON c.city = r.city
       AND c.conversation_id
           = r.conversation_id;
    CREATE UNIQUE INDEX idx_{OUTPUT_TABLE}_conversation
        ON {OUTPUT_TABLE} (
            city,
            conversation_id
        );
    CREATE INDEX idx_{OUTPUT_TABLE}_n_tweets
        ON {OUTPUT_TABLE} (
            n_tweets_core
        );
    CREATE INDEX idx_{OUTPUT_TABLE}_n_users
        ON {OUTPUT_TABLE} (
            n_users_core
        );
    CREATE INDEX idx_{OUTPUT_TABLE}_duration
        ON {OUTPUT_TABLE} (
            duration_minutes
        );
    CREATE INDEX idx_{OUTPUT_TABLE}_root
        ON {OUTPUT_TABLE} (
            has_root
        );
    ANALYZE {OUTPUT_TABLE};
    """,
)

print_table_count(OUTPUT_TABLE)

# 5. Drop Intermediate Tables
run_step(
    "Drop intermediate tables",
    f"""
    DROP TABLE IF EXISTS {TEMP_CORE};
    DROP TABLE IF EXISTS {TEMP_RETWEETS};
    DROP TABLE IF EXISTS {TEMP_TWEETS};
    """,
)

# Final
log(f"Finished. Final table: {OUTPUT_TABLE}")
