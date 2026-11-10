"""Aggregate tweet-level interactions into directed and undirected networks.

Each edge records total, reply-only, mention-only, and combined interaction
weights, along with first and last observed interaction dates.
Self-interactions are excluded from both network tables.
"""

import json
import time
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


CONNECTION_PATH = "/home/ilyesvirag/twitter/venv/connection.json"
INPUT_TABLE = "interaction_table"

DIRECTED_TABLE = "interaction_network_directed"
UNDIRECTED_TABLE = "interaction_network_undirected"


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
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def run_step(step_name, sql):
    log(f"START: {step_name}")
    started = time.time()

    with engine.begin() as connection:
        connection.execute(text(sql))

    log(f"FINISHED: {step_name} ({(time.time() - started) / 60:.2f} minutes)")


# ------------------------------------------------------------------
# 1. DIRECTED NETWORK
# ------------------------------------------------------------------
run_step(
    "Create directed interaction network",
    f"""
    DROP TABLE IF EXISTS {DIRECTED_TABLE};

    CREATE TABLE {DIRECTED_TABLE} AS
    SELECT
        city,
        user_id1_source,
        user_id2_interaction,
        COUNT(*)::BIGINT AS edge_weight,
        COUNT(*) FILTER (WHERE interaction_type = 1)::BIGINT AS reply_only_weight,
        COUNT(*) FILTER (WHERE interaction_type = 2)::BIGINT AS mention_only_weight,
        COUNT(*) FILTER (WHERE interaction_type = 3)::BIGINT AS both_weight,
        MIN(created_at) AS first_created_at,
        MAX(created_at) AS last_created_at
    FROM {INPUT_TABLE}
    WHERE user_id1_source <> user_id2_interaction
    GROUP BY city, user_id1_source, user_id2_interaction;

    CREATE UNIQUE INDEX idx_{DIRECTED_TABLE}_edge
        ON {DIRECTED_TABLE} (city, user_id1_source, user_id2_interaction);

    CREATE INDEX idx_{DIRECTED_TABLE}_edge_weight
        ON {DIRECTED_TABLE} (edge_weight);

    CREATE INDEX idx_{DIRECTED_TABLE}_first_created_at
        ON {DIRECTED_TABLE} (first_created_at);

    CREATE INDEX idx_{DIRECTED_TABLE}_last_created_at
        ON {DIRECTED_TABLE} (last_created_at);

    ANALYZE {DIRECTED_TABLE};
    """,
)


# ------------------------------------------------------------------
# 2. UNDIRECTED NETWORK
# ------------------------------------------------------------------
run_step(
    "Create undirected interaction network",
    f"""
    DROP TABLE IF EXISTS {UNDIRECTED_TABLE};

    CREATE TABLE {UNDIRECTED_TABLE} AS
    SELECT
        city,
        LEAST(user_id1_source, user_id2_interaction) AS user_id1,
        GREATEST(user_id1_source, user_id2_interaction) AS user_id2,
        COUNT(*)::BIGINT AS edge_weight,
        COUNT(*) FILTER (WHERE interaction_type = 1)::BIGINT AS reply_only_weight,
        COUNT(*) FILTER (WHERE interaction_type = 2)::BIGINT AS mention_only_weight,
        COUNT(*) FILTER (WHERE interaction_type = 3)::BIGINT AS both_weight,
        MIN(created_at) AS first_created_at,
        MAX(created_at) AS last_created_at
    FROM {INPUT_TABLE}
    WHERE user_id1_source <> user_id2_interaction
    GROUP BY
        city,
        LEAST(user_id1_source, user_id2_interaction),
        GREATEST(user_id1_source, user_id2_interaction);

    CREATE UNIQUE INDEX idx_{UNDIRECTED_TABLE}_edge
        ON {UNDIRECTED_TABLE} (city, user_id1, user_id2);

    CREATE INDEX idx_{UNDIRECTED_TABLE}_edge_weight
        ON {UNDIRECTED_TABLE} (edge_weight);

    CREATE INDEX idx_{UNDIRECTED_TABLE}_first_created_at
        ON {UNDIRECTED_TABLE} (first_created_at);

    CREATE INDEX idx_{UNDIRECTED_TABLE}_last_created_at
        ON {UNDIRECTED_TABLE} (last_created_at);

    ANALYZE {UNDIRECTED_TABLE};
    """,
)


# ------------------------------------------------------------------
# 3. SUMMARY
# ------------------------------------------------------------------
with engine.connect() as connection:
    directed_stats = connection.execute(
        text(
            f"""
            SELECT
                COUNT(*) AS edges,
                COUNT(DISTINCT user_id1_source) AS source_users,
                COUNT(DISTINCT user_id2_interaction) AS target_users,
                (
                    SELECT COUNT(*)
                    FROM (
                        SELECT user_id1_source AS user_id FROM {DIRECTED_TABLE}
                        UNION
                        SELECT user_id2_interaction AS user_id FROM {DIRECTED_TABLE}
                    ) AS users
                ) AS unique_users,
                SUM(edge_weight) AS total_interactions,
                AVG(edge_weight) AS mean_edge_weight,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY edge_weight) AS median_edge_weight,
                MAX(edge_weight) AS max_edge_weight,
                SUM(reply_only_weight) AS reply_only_interactions,
                SUM(mention_only_weight) AS mention_only_interactions,
                SUM(both_weight) AS both_interactions,
                MIN(first_created_at) AS network_start,
                MAX(last_created_at) AS network_end
            FROM {DIRECTED_TABLE}
            """
        )
    ).mappings().one()

    undirected_stats = connection.execute(
        text(
            f"""
            SELECT
                COUNT(*) AS edges,
                (
                    SELECT COUNT(*)
                    FROM (
                        SELECT user_id1 AS user_id FROM {UNDIRECTED_TABLE}
                        UNION
                        SELECT user_id2 AS user_id FROM {UNDIRECTED_TABLE}
                    ) AS users
                ) AS unique_users,
                SUM(edge_weight) AS total_interactions,
                AVG(edge_weight) AS mean_edge_weight,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY edge_weight) AS median_edge_weight,
                MAX(edge_weight) AS max_edge_weight,
                SUM(reply_only_weight) AS reply_only_interactions,
                SUM(mention_only_weight) AS mention_only_interactions,
                SUM(both_weight) AS both_interactions,
                MIN(first_created_at) AS network_start,
                MAX(last_created_at) AS network_end
            FROM {UNDIRECTED_TABLE}
            """
        )
    ).mappings().one()


log("DIRECTED NETWORK")
for name, value in directed_stats.items():
    log(f"{name}: {value:,}" if isinstance(value, int) else f"{name}: {value}")

log("UNDIRECTED NETWORK")
for name, value in undirected_stats.items():
    log(f"{name}: {value:,}" if isinstance(value, int) else f"{name}: {value}")


log(f"Finished. Directed table: {DIRECTED_TABLE}")
log(f"Finished. Undirected table: {UNDIRECTED_TABLE}")