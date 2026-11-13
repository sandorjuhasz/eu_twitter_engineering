"""Build one text corpus per undirected London user pair.
For each pair, collect the conversations in which they interacted and join
corrected thread texts in chronological order. The result is stored in
interaction_edge_thread_corpus_london in PostgreSQL.
"""

import json
import time
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from pipeline_config import CONNECTION_PATH, SOURCE_TABLE

INTERACTION_TABLE = "interaction_table"
TWEET_TABLE = "tweet"
THREAD_TABLE = "thread_table"

OUTPUT_TABLE = SOURCE_TABLE

CITY = "london"

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

def log(message):
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{message}",
        flush=True,
    )

def run_step(step_name, sql):
    log(f"START: {step_name}")
    started = time.time()

    with engine.begin() as connection:
        connection.execute(text(sql))

    log(
        f"FINISHED: {step_name} "
        f"({(time.time() - started) / 60:.2f} minutes)"
    )

# Rebuild the edge corpus; the following cleaning step recreates cleaned-text columns.

run_step(
    "Create edge-level corrected thread corpus",
    f"""
    DROP TABLE IF EXISTS {OUTPUT_TABLE};
    CREATE TABLE {OUTPUT_TABLE} AS
    -- Identify the conversation associated with each London tweet.
    WITH tweet_conversations AS (
        SELECT DISTINCT ON (city, tweet_id)
            city,
            tweet_id,
            conversation_id
        FROM {TWEET_TABLE}
        WHERE city = '{CITY}'
          AND conversation_id IS NOT NULL
        ORDER BY city, tweet_id, created_at
    ),
    -- Identify the conversations shared by each undirected user pair
    edge_threads AS (
        SELECT
            e.city,
            LEAST(e.user_id1_source, e.user_id2_interaction) AS user_id1,
            GREATEST(e.user_id1_source, e.user_id2_interaction) AS user_id2,
            t.conversation_id,
            COUNT(DISTINCT e.tweet_id)::BIGINT
                AS n_interaction_tweets_in_thread
        FROM {INTERACTION_TABLE} AS e
        INNER JOIN tweet_conversations AS t
            ON e.city = t.city
           AND e.tweet_id = t.tweet_id
        WHERE e.city = '{CITY}'
          AND e.user_id1_source <> e.user_id2_interaction
        GROUP BY
            e.city,
            LEAST(e.user_id1_source, e.user_id2_interaction),
            GREATEST(e.user_id1_source, e.user_id2_interaction),
            t.conversation_id
    )
    -- Aggregate thread statistics and concatenate conversation texts chronologically.
    SELECT
        et.city,
        et.user_id1,
        et.user_id2,
        SUM(et.n_interaction_tweets_in_thread)::BIGINT
            AS n_interaction_tweets,
        COUNT(*)::BIGINT
            AS n_threads,
        SUM(
            th.n_tweets_core
            + CASE
                WHEN th.root_reconstructed THEN 1
                ELSE 0
              END
        )::BIGINT
            AS n_thread_tweets,
        SUM(
            CHAR_LENGTH(
                COALESCE(th.corrected_thread_text, '')
            )
        )::BIGINT
            AS n_text_characters,
        SUM(
            CASE
                WHEN NULLIF(
                    BTRIM(COALESCE(th.corrected_thread_text, '')),
                    ''
                ) IS NULL
                    THEN 0
                ELSE CARDINALITY(
                    REGEXP_SPLIT_TO_ARRAY(
                        BTRIM(th.corrected_thread_text),
                        E'\\\\s+'
                    )
                )
            END
        )::BIGINT
            AS n_text_words,
        STRING_AGG(
            th.corrected_thread_text,
            E'\\n\\n'
            ORDER BY th.first_created_at, th.conversation_id
        )
            AS edge_thread_text
    FROM edge_threads AS et
    INNER JOIN {THREAD_TABLE} AS th
        ON et.city = th.city
       AND et.conversation_id = th.conversation_id
    GROUP BY
        et.city,
        et.user_id1,
        et.user_id2;
    CREATE UNIQUE INDEX idx_{OUTPUT_TABLE}_edge
        ON {OUTPUT_TABLE} (
            city,
            user_id1,
            user_id2
        );
    CREATE INDEX idx_{OUTPUT_TABLE}_n_threads
        ON {OUTPUT_TABLE} (
            n_threads
        );
    ANALYZE {OUTPUT_TABLE};
    """,
)

with engine.connect() as connection:
    stats = connection.execute(
        text(
            f"""
            SELECT
                COUNT(*) AS n_edges,
                AVG(n_threads) AS mean_threads,
                PERCENTILE_CONT(0.5)
                    WITHIN GROUP (ORDER BY n_threads)
                    AS median_threads,
                PERCENTILE_CONT(0.9)
                    WITHIN GROUP (ORDER BY n_threads)
                    AS p90_threads,
                PERCENTILE_CONT(0.99)
                    WITHIN GROUP (ORDER BY n_threads)
                    AS p99_threads,
                MAX(n_threads) AS max_threads,
                AVG(n_thread_tweets) AS mean_thread_tweets,
                PERCENTILE_CONT(0.5)
                    WITHIN GROUP (ORDER BY n_thread_tweets)
                    AS median_thread_tweets,
                PERCENTILE_CONT(0.9)
                    WITHIN GROUP (ORDER BY n_thread_tweets)
                    AS p90_thread_tweets,
                PERCENTILE_CONT(0.95)
                    WITHIN GROUP (ORDER BY n_thread_tweets)
                    AS p95_thread_tweets,
                PERCENTILE_CONT(0.99)
                    WITHIN GROUP (ORDER BY n_thread_tweets)
                    AS p99_thread_tweets,
                MAX(n_thread_tweets) AS max_thread_tweets,
                AVG(n_text_characters) AS mean_text_characters,
                PERCENTILE_CONT(0.5)
                    WITHIN GROUP (ORDER BY n_text_characters)
                    AS median_text_characters,
                PERCENTILE_CONT(0.9)
                    WITHIN GROUP (ORDER BY n_text_characters)
                    AS p90_text_characters,
                PERCENTILE_CONT(0.95)
                    WITHIN GROUP (ORDER BY n_text_characters)
                    AS p95_text_characters,
                PERCENTILE_CONT(0.99)
                    WITHIN GROUP (ORDER BY n_text_characters)
                    AS p99_text_characters,
                MAX(n_text_characters) AS max_text_characters,
                AVG(n_text_words) AS mean_text_words,
                PERCENTILE_CONT(0.5)
                    WITHIN GROUP (ORDER BY n_text_words)
                    AS median_text_words,
                PERCENTILE_CONT(0.9)
                    WITHIN GROUP (ORDER BY n_text_words)
                    AS p90_text_words,
                PERCENTILE_CONT(0.95)
                    WITHIN GROUP (ORDER BY n_text_words)
                    AS p95_text_words,
                PERCENTILE_CONT(0.99)
                    WITHIN GROUP (ORDER BY n_text_words)
                    AS p99_text_words,
                MAX(n_text_words) AS max_text_words
            FROM {OUTPUT_TABLE};
            """
        )
    ).mappings().one()

log("OUTPUT SUMMARY")

for name, value in stats.items():
    if isinstance(value, int):
        log(f"{name}: {value:,}")
    else:
        log(f"{name}: {value}")

log(f"Finished. Final table: {OUTPUT_TABLE}")
