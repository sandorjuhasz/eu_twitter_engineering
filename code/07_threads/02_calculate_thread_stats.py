"""Check the London conversation table and save thread diagnostics.
Includes thread size, observed roots, reconstructed roots and user counts.
Reads PostgreSQL tables without changing them.
"""

import os
import json

import pandas as pd
import matplotlib.pyplot as plt

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# Settings
CONNECTION_PATH = "/home/ilyesvirag/twitter/venv/connection.json"

TWEET_TABLE = "tweet"
THREAD_TABLE = "thread_table_london"

CITY = "london"

OUTPUT_DIR = "/mnt/common-hdd/group-dirs/twitter-2025-project/thread_statistics"

os.makedirs(OUTPUT_DIR, exist_ok=True)

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

# 1. Source Tweet Table
with engine.connect() as connection:

    source = connection.execute(
        text(
            f"""
            SELECT
                COUNT(*)
                    AS n_rows,
                COUNT(
                    DISTINCT tweet_id
                ) AS n_unique_tweets,
                COUNT(
                    DISTINCT conversation_id
                ) AS n_conversations,
                COUNT(
                    DISTINCT conversation_id
                ) FILTER (
                    WHERE
                        tweet_id::TEXT
                        = conversation_id::TEXT
                )
                    AS n_conversations_with_root
            FROM {TWEET_TABLE}
            WHERE city = :city
              AND conversation_id
                  IS NOT NULL
              AND LOWER(
                    TRIM(tweet_type)
                  )
                  IN (
                      'original',
                      'reply',
                      'quote'
                  );
            """
        ),
        {
            "city": CITY,
        },
    ).mappings().one()

print("\n" + "=" * 70)
print("SOURCE TWEET TABLE")
print("=" * 70)

for name, value in source.items():
    print(
        f"{name}: "
        f"{value:,}"
    )

# 2. Thread Size Distribution
with engine.connect() as connection:

    thread_size = pd.read_sql(
        text(
            f"""
            SELECT
                CASE
                    WHEN n_tweets_core = 1
                        THEN '1'
                    WHEN n_tweets_core = 2
                        THEN '2'
                    WHEN n_tweets_core = 3
                        THEN '3'
                    WHEN n_tweets_core
                         BETWEEN 4 AND 5
                        THEN '4-5'
                    WHEN n_tweets_core
                         BETWEEN 6 AND 10
                        THEN '6-10'
                    WHEN n_tweets_core
                         BETWEEN 11 AND 20
                        THEN '11-20'
                    ELSE '21+'
                END AS thread_size,
                COUNT(*)
                    AS n_threads,
                MIN(n_tweets_core)
                    AS sort_order
            FROM {THREAD_TABLE}
            GROUP BY 1
            ORDER BY sort_order;
            """
        ),
        connection,
    )

print("\n" + "=" * 70)
print("THREAD SIZE DISTRIBUTION")
print("=" * 70)

print(
    thread_size[
        [
            "thread_size",
            "n_threads",
        ]
    ].to_string(
        index=False
    )
)

thread_size[
    [
        "thread_size",
        "n_threads",
    ]
].to_csv(
    os.path.join(
        OUTPUT_DIR,
        "thread_size_distribution.csv",
    ),
    index=False,
)

# 3. Thread Size Plot
fig, ax = plt.subplots(
    figsize=(8, 5)
)

ax.bar(
    thread_size["thread_size"],
    thread_size["n_threads"],
)

ax.set_xlabel(
    "Number of observed tweets in conversation"
)

ax.set_ylabel(
    "Number of conversations"
)

ax.set_title(
    "Conversation size distribution"
)

fig.tight_layout()

fig.savefig(
    os.path.join(
        OUTPUT_DIR,
        "thread_size_distribution.png",
    ),
    dpi=300,
)

plt.close(fig)

# 4. Root × Thread Size
with engine.connect() as connection:

    root_size = pd.read_sql(
        text(
            f"""
            SELECT
                has_root,
                n_tweets_core,
                COUNT(*)
                    AS n_threads
            FROM {THREAD_TABLE}
            WHERE n_tweets_core <= 10
            GROUP BY
                has_root,
                n_tweets_core
            ORDER BY
                has_root DESC,
                n_tweets_core;
            """
        ),
        connection,
    )

print("\n" + "=" * 70)
print("ROOT × THREAD SIZE")
print("=" * 70)

print(
    root_size.to_string(
        index=False
    )
)

root_size.to_csv(
    os.path.join(
        OUTPUT_DIR,
        "root_by_thread_size.csv",
    ),
    index=False,
)

# 5. Root × Thread Size Plot
plot_root = (
    root_size
    .pivot(
        index="n_tweets_core",
        columns="has_root",
        values="n_threads",
    )
    .fillna(0)
)

fig, ax = plt.subplots(
    figsize=(8, 5)
)

plot_root.plot(
    kind="bar",
    ax=ax,
)

ax.set_xlabel(
    "Number of observed tweets"
)

ax.set_ylabel(
    "Number of conversations"
)

ax.set_title(
    "Conversation size by observed-root status"
)

ax.legend(
    title="Root observed"
)

fig.tight_layout()

fig.savefig(
    os.path.join(
        OUTPUT_DIR,
        "root_by_thread_size.png",
    ),
    dpi=300,
)

plt.close(fig)

# 6. Singleton Thread Composition
# has_root = TRUE:
#   classify the observed root as quote versus non-quote.
# has_root = FALSE:
#   inspect whether the single observed core tweet is a reply/quote
#   and whether retweet evidence exists.
with engine.connect() as connection:

    singleton = connection.execute(
        text(
            f"""
            SELECT
                COUNT(*) FILTER (
                    WHERE n_tweets_core = 1
                      AND has_root
                )
                    AS singleton_with_root,
                COUNT(*) FILTER (
                    WHERE n_tweets_core = 1
                      AND has_root
                      AND n_quote = 1
                )
                    AS singleton_root_quote,
                COUNT(*) FILTER (
                    WHERE n_tweets_core = 1
                      AND has_root
                      AND n_quote = 0
                )
                    AS singleton_root_original,
                COUNT(*) FILTER (
                    WHERE n_tweets_core = 1
                      AND NOT has_root
                )
                    AS singleton_missing_root,
                COUNT(*) FILTER (
                    WHERE n_tweets_core = 1
                      AND NOT has_root
                      AND n_reply > 0
                )
                    AS singleton_missing_root_reply,
                COUNT(*) FILTER (
                    WHERE n_tweets_core = 1
                      AND NOT has_root
                      AND n_quote > 0
                )
                    AS singleton_missing_root_quote,
                COUNT(*) FILTER (
                    WHERE n_tweets_core = 1
                      AND NOT has_root
                      AND n_retweet > 0
                )
                    AS singleton_missing_root_with_retweet
            FROM {THREAD_TABLE};
            """
        )
    ).mappings().one()

print("\n" + "=" * 70)
print("SINGLETON THREAD COMPOSITION")
print("=" * 70)

for name, value in singleton.items():
    print(
        f"{name}: "
        f"{value:,}"
    )

# 7. Overall Thread Diagnostics
with engine.connect() as connection:

    totals = connection.execute(
        text(
            f"""
            SELECT
                COUNT(*)
                    AS n_threads,
                COUNT(*) FILTER (
                    WHERE has_root
                )
                    AS threads_with_root,
                COUNT(*) FILTER (
                    WHERE NOT has_root
                )
                    AS threads_missing_root,
                COUNT(*) FILTER (
                    WHERE n_retweet > 0
                )
                    AS threads_with_retweet,
                COUNT(*) FILTER (
                    WHERE NOT has_root
                      AND n_retweet > 0
                )
                    AS missing_root_with_retweet,
                COUNT(*) FILTER (
                    WHERE root_reconstructed
                )
                    AS threads_root_reconstructed,
                COUNT(*) FILTER (
                    WHERE n_tweets_core >= 2
                )
                    AS multi_tweet_threads,
                COUNT(*) FILTER (
                    WHERE n_users_core >= 2
                )
                    AS multi_user_threads,
                COUNT(*) FILTER (
                    WHERE n_tweets_core >= 2
                      AND n_users_core >= 2
                )
                    AS multi_tweet_multi_user_threads,
                COUNT(*) FILTER (
                    WHERE n_quote > 0
                )
                    AS threads_with_quote_root,
                COUNT(*) FILTER (
                    WHERE n_quote > 1
                )
                    AS threads_with_multiple_quotes,
                MAX(n_quote)
                    AS max_n_quote
            FROM {THREAD_TABLE};
            """
        )
    ).mappings().one()

print("\n" + "=" * 70)
print("OVERALL THREAD DIAGNOSTICS")
print("=" * 70)

for name, value in totals.items():
    print(
        f"{name}: "
        f"{value:,}"
    )

# 8. Retweet Reconstruction Rate
if totals["missing_root_with_retweet"] > 0:

    reconstruction_rate = (
        totals["threads_root_reconstructed"]
        / totals["missing_root_with_retweet"]
    )

else:
    reconstruction_rate = float("nan")

print(
    "\nroot reconstruction rate "
    "among missing-root threads with retweet evidence: "
    f"{reconstruction_rate:.4%}"
)

# 9. User Count Distribution
with engine.connect() as connection:

    user_dist = pd.read_sql(
        text(
            f"""
            SELECT
                CASE
                    WHEN n_users_core = 1
                        THEN '1'
                    WHEN n_users_core = 2
                        THEN '2'
                    WHEN n_users_core = 3
                        THEN '3'
                    WHEN n_users_core
                         BETWEEN 4 AND 5
                        THEN '4-5'
                    WHEN n_users_core
                         BETWEEN 6 AND 10
                        THEN '6-10'
                    ELSE '11+'
                END AS n_users,
                COUNT(*)
                    AS n_threads,
                MIN(n_users_core)
                    AS sort_order
            FROM {THREAD_TABLE}
            WHERE n_tweets_core >= 2
            GROUP BY 1
            ORDER BY sort_order;
            """
        ),
        connection,
    )

user_dist[
    [
        "n_users",
        "n_threads",
    ]
].to_csv(
    os.path.join(
        OUTPUT_DIR,
        "users_per_multitweet_thread.csv",
    ),
    index=False,
)

fig, ax = plt.subplots(
    figsize=(8, 5)
)

ax.bar(
    user_dist["n_users"],
    user_dist["n_threads"],
)

ax.set_xlabel(
    "Number of users"
)

ax.set_ylabel(
    "Number of conversations"
)

ax.set_title(
    "Users per multi-tweet conversation"
)

fig.tight_layout()

fig.savefig(
    os.path.join(
        OUTPUT_DIR,
        "users_per_multitweet_thread.png",
    ),
    dpi=300,
)

plt.close(fig)

# Final
print("\nSaved diagnostics to:")
print(OUTPUT_DIR)

print("\nDone.")
