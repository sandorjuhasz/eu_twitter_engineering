"""Calculate London undirected-network descriptives and export plotting data.

Reads interaction_network_undirected, calculates edge, node, and connected
component measures, and writes four CSV files to the undirected descriptives
directory. Does not modify PostgreSQL tables.
"""

import json
import os
import numpy as np
import pandas as pd
import networkx as nx

from sqlalchemy import create_engine
from sqlalchemy.engine import URL


# ------------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------------
CONNECTION_PATH = "/home/ilyesvirag/twitter/venv/connection.json"
INPUT_TABLE = "interaction_network_undirected"
CITY = "london"

OUTPUT_DIR = "/mnt/common-hdd/group-dirs/twitter-2025-project/interaction_network_descriptives/undirected"

SUMMARY_CSV = os.path.join(OUTPUT_DIR, "interaction_network_undirected_london_summary.csv")
NODES_CSV = os.path.join(OUTPUT_DIR, "interaction_network_undirected_london_nodes.csv")
EDGE_WEIGHT_DISTRIBUTION_CSV = os.path.join(OUTPUT_DIR, "interaction_network_undirected_london_edge_weight_distribution.csv")
COMPONENT_DISTRIBUTION_CSV = os.path.join(OUTPUT_DIR, "interaction_network_undirected_london_component_distribution.csv")

os.makedirs(OUTPUT_DIR, exist_ok=True)


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
def safe_share(numerator, denominator):
    return np.nan if denominator == 0 else numerator / denominator


def add_metric(rows, metric, description, value):
    rows.append({"metric": metric, "description": description, "value": value})


def add_distribution_summary(rows, series, prefix, label):
    numeric = pd.to_numeric(series, errors="coerce").dropna()

    if len(numeric) == 0:
        values = {"mean": np.nan, "median": np.nan, "p75": np.nan, "p90": np.nan,
                  "p95": np.nan, "p99": np.nan, "max": np.nan}
    else:
        values = {
            "mean": numeric.mean(),
            "median": numeric.median(),
            "p75": numeric.quantile(0.75),
            "p90": numeric.quantile(0.90),
            "p95": numeric.quantile(0.95),
            "p99": numeric.quantile(0.99),
            "max": numeric.max(),
        }

    descriptions = {
        "mean": f"Mean {label}.",
        "median": f"Median {label}.",
        "p75": f"75th percentile of {label}.",
        "p90": f"90th percentile of {label}.",
        "p95": f"95th percentile of {label}.",
        "p99": f"99th percentile of {label}.",
        "max": f"Maximum {label}.",
    }

    for stat, value in values.items():
        add_metric(rows, f"{prefix}_{stat}", descriptions[stat], value)


# ------------------------------------------------------------------
# 1. READ LONDON UNDIRECTED NETWORK
# ------------------------------------------------------------------
print("=" * 70)
print("Reading London undirected interaction network")
print("=" * 70)

edges = pd.read_sql(
    f"""
    SELECT
        user_id1,
        user_id2,
        edge_weight,
        reply_only_weight,
        mention_only_weight,
        both_weight,
        first_created_at,
        last_created_at
    FROM {INPUT_TABLE}
    WHERE city = '{CITY}'
    """,
    engine,
)

print(f"Undirected edges loaded: {len(edges):,}")

if len(edges) == 0:
    raise ValueError(f"No rows found for city = '{CITY}'.")


# ------------------------------------------------------------------
# 2. CONSTRUCT UNDIRECTED NETWORK
# ------------------------------------------------------------------
print("\n" + "=" * 70)
print("Constructing undirected network")
print("=" * 70)

G = nx.Graph()

for row in edges.itertuples(index=False):
    G.add_edge(
        row.user_id1,
        row.user_id2,
        edge_weight=int(row.edge_weight),
        reply_only_weight=int(row.reply_only_weight),
        mention_only_weight=int(row.mention_only_weight),
        both_weight=int(row.both_weight),
    )

n_nodes = G.number_of_nodes()
n_edges = G.number_of_edges()

print(f"Nodes:            {n_nodes:,}")
print(f"Undirected edges: {n_edges:,}")


# ------------------------------------------------------------------
# 3. NETWORK-LEVEL DESCRIPTIVES
# ------------------------------------------------------------------
summary_rows = []

total_interactions = int(edges["edge_weight"].sum())
reply_only_interactions = int(edges["reply_only_weight"].sum())
mention_only_interactions = int(edges["mention_only_weight"].sum())
both_interactions = int(edges["both_weight"].sum())

assert total_interactions == reply_only_interactions + mention_only_interactions + both_interactions, (
    "Interaction weights are inconsistent: edge_weight does not equal the sum of "
    "reply_only_weight + mention_only_weight + both_weight."
)

possible_undirected_edges = n_nodes * (n_nodes - 1) / 2
density = safe_share(n_edges, possible_undirected_edges)

network_start = edges["first_created_at"].min()
network_end = edges["last_created_at"].max()

add_metric(summary_rows, "nodes",
           "Number of unique users appearing in the London undirected network.", n_nodes)

add_metric(summary_rows, "undirected_edges",
           "Number of distinct non-self undirected user-user edges in the London network.", n_edges)

add_metric(summary_rows, "total_interactions",
           "Total number of tweet-level interactions represented by the undirected edges.", total_interactions)

add_metric(summary_rows, "network_density",
           "Observed undirected edges divided by the number of possible non-self undirected edges.", density)

add_metric(summary_rows, "reply_only_interactions",
           "Total number of reply-only tweet-level interactions.", reply_only_interactions)

add_metric(summary_rows, "mention_only_interactions",
           "Total number of mention-only tweet-level interactions.", mention_only_interactions)

add_metric(summary_rows, "both_interactions",
           "Total number of interactions classified as both reply and mention.", both_interactions)

add_metric(summary_rows, "share_reply_only",
           "Share of all tweet-level interactions classified as reply only.",
           safe_share(reply_only_interactions, total_interactions))

add_metric(summary_rows, "share_mention_only",
           "Share of all tweet-level interactions classified as mention only.",
           safe_share(mention_only_interactions, total_interactions))

add_metric(summary_rows, "share_both",
           "Share of all tweet-level interactions classified as both reply and mention.",
           safe_share(both_interactions, total_interactions))

add_metric(summary_rows, "network_start",
           "First observed interaction date in the London network.", network_start)

add_metric(summary_rows, "network_end",
           "Last observed interaction date in the London network.", network_end)


# ------------------------------------------------------------------
# 4. EDGE-WEIGHT DISTRIBUTION
# ------------------------------------------------------------------
print("\n" + "=" * 70)
print("Calculating undirected edge-weight descriptives")
print("=" * 70)

add_distribution_summary(
    summary_rows,
    edges["edge_weight"],
    "edge_weight",
    "number of interactions per undirected edge",
)

single_interaction_edges = int((edges["edge_weight"] == 1).sum())

add_metric(
    summary_rows,
    "share_single_interaction_edges",
    "Share of undirected edges with exactly one observed interaction.",
    safe_share(single_interaction_edges, n_edges),
)

edge_weight_distribution = (
    edges["edge_weight"]
    .value_counts()
    .sort_index()
    .rename_axis("edge_weight")
    .reset_index(name="n_edges")
)

edge_weight_distribution["share_edges"] = edge_weight_distribution["n_edges"] / n_edges
edge_weight_distribution["cumulative_share_edges"] = edge_weight_distribution["share_edges"].cumsum()


# ------------------------------------------------------------------
# 5. NODE-LEVEL MEASURES
# ------------------------------------------------------------------
print("\n" + "=" * 70)
print("Calculating node-level measures")
print("=" * 70)

degree = dict(G.degree())
strength = dict(G.degree(weight="edge_weight"))

nodes = pd.DataFrame({"user_id": list(G.nodes())})

nodes["degree"] = nodes["user_id"].map(degree).fillna(0).astype("int64")
nodes["strength"] = nodes["user_id"].map(strength).fillna(0).astype("int64")

add_distribution_summary(
    summary_rows,
    nodes["degree"],
    "degree",
    "number of distinct undirected neighbors per user",
)

add_distribution_summary(
    summary_rows,
    nodes["strength"],
    "strength",
    "total interaction weight across all undirected edges incident to a user",
)


# ------------------------------------------------------------------
# 6. CONNECTED COMPONENTS
# ------------------------------------------------------------------
print("\n" + "=" * 70)
print("Calculating connected components")
print("=" * 70)

components = sorted(nx.connected_components(G), key=len, reverse=True)

component_map = {}
for component_id, component_nodes in enumerate(components, start=1):
    for node in component_nodes:
        component_map[node] = component_id

nodes["component_id"] = nodes["user_id"].map(component_map).astype("int64")
nodes["in_giant_component"] = nodes["component_id"] == 1

giant_component_nodes = len(components[0]) if components else 0
giant_component_node_set = components[0] if components else set()
giant_component_edges = G.subgraph(giant_component_node_set).number_of_edges()

add_metric(
    summary_rows,
    "n_components",
    "Number of connected components in the undirected network.",
    len(components),
)

add_metric(
    summary_rows,
    "giant_component_nodes",
    "Number of users in the largest connected component.",
    giant_component_nodes,
)

add_metric(
    summary_rows,
    "share_nodes_in_giant_component",
    "Share of all users in the largest connected component.",
    safe_share(giant_component_nodes, n_nodes),
)

add_metric(
    summary_rows,
    "giant_component_edges",
    "Number of undirected edges contained in the largest connected component.",
    giant_component_edges,
)


# ------------------------------------------------------------------
# 7. COMPONENT DISTRIBUTION
# ------------------------------------------------------------------
component_distribution = pd.DataFrame(
    {
        "component_id": range(1, len(components) + 1),
        "n_nodes": [len(component) for component in components],
    }
)

component_distribution["share_nodes"] = component_distribution["n_nodes"] / n_nodes


# ------------------------------------------------------------------
# 8. INTERNAL CONSISTENCY CHECKS
# ------------------------------------------------------------------
assert int(nodes["degree"].sum()) == 2 * n_edges, (
    "Degree consistency check failed: sum(degree) should equal 2 × number of undirected edges."
)

assert int(nodes["strength"].sum()) == 2 * total_interactions, (
    "Strength consistency check failed: sum(strength) should equal 2 × total interactions."
)


# ------------------------------------------------------------------
# 9. SAVE OUTPUTS
# ------------------------------------------------------------------
print("\n" + "=" * 70)
print("Saving outputs")
print("=" * 70)

summary = pd.DataFrame(summary_rows)

summary.to_csv(SUMMARY_CSV, index=False)
nodes.to_csv(NODES_CSV, index=False)
edge_weight_distribution.to_csv(EDGE_WEIGHT_DISTRIBUTION_CSV, index=False)
component_distribution.to_csv(COMPONENT_DISTRIBUTION_CSV, index=False)


# ------------------------------------------------------------------
# 10. FINAL OUTPUT
# ------------------------------------------------------------------
print("\nOutputs saved:")
print(SUMMARY_CSV)
print(NODES_CSV)
print(EDGE_WEIGHT_DISTRIBUTION_CSV)
print(COMPONENT_DISTRIBUTION_CSV)

print("\nDone.")