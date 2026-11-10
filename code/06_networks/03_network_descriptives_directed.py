"""Calculate London directed-network descriptives and export plotting data.

Reads interaction_network_directed, calculates edge, node, reciprocity,
and weak/strong component measures, and writes four CSV files to the
directed descriptives directory. Does not modify PostgreSQL tables.
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

INPUT_TABLE = "interaction_network_directed"
CITY = "london"

OUTPUT_DIR = "/mnt/common-hdd/group-dirs/twitter-2025-project/interaction_network_descriptives/directed"

SUMMARY_CSV = os.path.join(OUTPUT_DIR, "interaction_network_london_summary.csv")

NODES_CSV = os.path.join(OUTPUT_DIR, "interaction_network_london_nodes.csv")

EDGE_WEIGHT_DISTRIBUTION_CSV = os.path.join(OUTPUT_DIR, "interaction_network_london_edge_weight_distribution.csv")

COMPONENT_DISTRIBUTION_CSV = os.path.join(OUTPUT_DIR, "interaction_network_london_component_distribution.csv")

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
        values = {
            "mean": np.nan,
            "median": np.nan,
            "p75": np.nan,
            "p90": np.nan,
            "p95": np.nan,
            "p99": np.nan,
            "max": np.nan,
        }
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
        add_metric(
            rows,
            f"{prefix}_{stat}",
            descriptions[stat],
            value,
        )


# ------------------------------------------------------------------
# 1. READ LONDON NETWORK
# ------------------------------------------------------------------
print("=" * 70)
print("Reading London interaction network")
print("=" * 70)

edges = pd.read_sql(
    f"""
    SELECT
        user_id1_source,
        user_id2_interaction,
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

print(f"Directed edges loaded: {len(edges):,}")

if len(edges) == 0:
    raise ValueError(f"No rows found for city = '{CITY}'.")


# ------------------------------------------------------------------
# 2. CONSTRUCT DIRECTED NETWORK
# ------------------------------------------------------------------
print("\n" + "=" * 70)
print("Constructing directed network")
print("=" * 70)

G = nx.DiGraph()

for row in edges.itertuples(index=False):
    G.add_edge(
        row.user_id1_source,
        row.user_id2_interaction,
        edge_weight=int(row.edge_weight),
        reply_only_weight=int(row.reply_only_weight),
        mention_only_weight=int(row.mention_only_weight),
        both_weight=int(row.both_weight),
    )

n_nodes = G.number_of_nodes()
n_edges = G.number_of_edges()

print(f"Nodes:          {n_nodes:,}")
print(f"Directed edges: {n_edges:,}")


# ------------------------------------------------------------------
# 3. NETWORK-LEVEL DESCRIPTIVES
# ------------------------------------------------------------------
summary_rows = []

total_interactions = int(edges["edge_weight"].sum())
reply_only_interactions = int(edges["reply_only_weight"].sum())
mention_only_interactions = int(edges["mention_only_weight"].sum())
both_interactions = int(edges["both_weight"].sum())

assert total_interactions == (
    reply_only_interactions
    + mention_only_interactions
    + both_interactions
), (
    "Interaction weights are inconsistent: "
    "edge_weight does not equal the sum of "
    "reply_only_weight + mention_only_weight + both_weight."
)

possible_directed_edges = n_nodes * (n_nodes - 1)
density = safe_share(n_edges, possible_directed_edges)

reciprocity = nx.reciprocity(G)
if reciprocity is None:
    reciprocity = np.nan

network_start = edges["first_created_at"].min()
network_end = edges["last_created_at"].max()

add_metric(
    summary_rows,
    "nodes",
    "Number of unique users appearing as source or target in the London network.",
    n_nodes,
)

add_metric(
    summary_rows,
    "directed_edges",
    "Number of distinct non-self directed user-user edges in the London network.",
    n_edges,
)

add_metric(
    summary_rows,
    "total_interactions",
    "Total number of tweet-level interactions represented by the directed edges.",
    total_interactions,
)

add_metric(
    summary_rows,
    "network_density",
    "Observed directed edges divided by the number of possible non-self directed edges.",
    density,
)

add_metric(
    summary_rows,
    "reciprocity",
    "Share of directed edges for which the reverse directed edge also exists.",
    reciprocity,
)

add_metric(
    summary_rows,
    "reply_only_interactions",
    "Total number of reply-only tweet-level interactions.",
    reply_only_interactions,
)

add_metric(
    summary_rows,
    "mention_only_interactions",
    "Total number of mention-only tweet-level interactions.",
    mention_only_interactions,
)

add_metric(
    summary_rows,
    "both_interactions",
    "Total number of interactions classified as both reply and mention.",
    both_interactions,
)

add_metric(
    summary_rows,
    "share_reply_only",
    "Share of all tweet-level interactions classified as reply only.",
    safe_share(reply_only_interactions, total_interactions),
)

add_metric(
    summary_rows,
    "share_mention_only",
    "Share of all tweet-level interactions classified as mention only.",
    safe_share(mention_only_interactions, total_interactions),
)

add_metric(
    summary_rows,
    "share_both",
    "Share of all tweet-level interactions classified as both reply and mention.",
    safe_share(both_interactions, total_interactions),
)

add_metric(
    summary_rows,
    "network_start",
    "First observed interaction date in the London network.",
    network_start,
)

add_metric(
    summary_rows,
    "network_end",
    "Last observed interaction date in the London network.",
    network_end,
)


# ------------------------------------------------------------------
# 4. EDGE-WEIGHT DISTRIBUTION
# ------------------------------------------------------------------
print("\n" + "=" * 70)
print("Calculating edge-weight descriptives")
print("=" * 70)

add_distribution_summary(
    summary_rows,
    edges["edge_weight"],
    "edge_weight",
    "number of interactions per directed edge",
)

single_interaction_edges = int((edges["edge_weight"] == 1).sum())

add_metric(
    summary_rows,
    "share_single_interaction_edges",
    "Share of directed edges observed exactly once.",
    safe_share(single_interaction_edges, n_edges),
)

edge_weight_distribution = (
    edges["edge_weight"]
    .value_counts()
    .sort_index()
    .rename_axis("edge_weight")
    .reset_index(name="n_edges")
)

edge_weight_distribution["share_edges"] = (
    edge_weight_distribution["n_edges"] / n_edges
)

edge_weight_distribution["cumulative_share_edges"] = (
    edge_weight_distribution["share_edges"].cumsum()
)


# ------------------------------------------------------------------
# 5. NODE-LEVEL MEASURES
# ------------------------------------------------------------------
print("\n" + "=" * 70)
print("Calculating node-level measures")
print("=" * 70)

in_degree = dict(G.in_degree())
out_degree = dict(G.out_degree())

in_strength = dict(G.in_degree(weight="edge_weight"))
out_strength = dict(G.out_degree(weight="edge_weight"))

nodes = pd.DataFrame({"user_id": list(G.nodes())})

nodes["in_degree"] = nodes["user_id"].map(in_degree).fillna(0).astype("int64")
nodes["out_degree"] = nodes["user_id"].map(out_degree).fillna(0).astype("int64")

nodes["in_strength"] = (
    nodes["user_id"].map(in_strength).fillna(0).astype("int64")
)

nodes["out_strength"] = (
    nodes["user_id"].map(out_strength).fillna(0).astype("int64")
)

nodes["degree"] = nodes["in_degree"] + nodes["out_degree"]
nodes["strength"] = nodes["in_strength"] + nodes["out_strength"]


# ------------------------------------------------------------------
# Unique and reciprocal neighbors
# ------------------------------------------------------------------
successors = {node: set(G.successors(node)) for node in G.nodes()}

predecessors = {node: set(G.predecessors(node)) for node in G.nodes()}

nodes["n_unique_neighbors"] = nodes["user_id"].map(
    lambda node: len(successors[node] | predecessors[node])
).astype("int64")

nodes["n_reciprocal_neighbors"] = nodes["user_id"].map(
    lambda node: len(successors[node] & predecessors[node])
).astype("int64")


# ------------------------------------------------------------------
# Node-level reciprocity
# ------------------------------------------------------------------
#
# Each reciprocal neighbor contributes two directed ties. Thus node-level
# reciprocity = 2 × reciprocal neighbors / (in-degree + out-degree).
# ------------------------------------------------------------------
nodes["node_reciprocity"] = np.where(
    nodes["degree"] > 0,
    2 * nodes["n_reciprocal_neighbors"] / nodes["degree"],
    np.nan,
)


# ------------------------------------------------------------------
# Distribution summaries
# ------------------------------------------------------------------
for variable, label in {
    "in_degree": "number of distinct incoming directed neighbors per user",
    "out_degree": "number of distinct outgoing directed neighbors per user",
    "degree": "sum of in-degree and out-degree per user",
    "n_unique_neighbors": "number of distinct neighbors in either direction per user",
    "n_reciprocal_neighbors": "number of distinct neighbors connected in both directions per user",
    "node_reciprocity": "share of a user's directed ties that are reciprocated",
    "in_strength": "total incoming interaction weight per user",
    "out_strength": "total outgoing interaction weight per user",
    "strength": "sum of incoming and outgoing interaction weight per user",
}.items():
    add_distribution_summary(
        summary_rows,
        nodes[variable],
        variable,
        label,
    )


# ------------------------------------------------------------------
# 6. CONNECTED COMPONENTS
# ------------------------------------------------------------------
print("\n" + "=" * 70)
print("Calculating connected components")
print("=" * 70)

weak_components = sorted(
    nx.weakly_connected_components(G),
    key=len,
    reverse=True,
)

strong_components = sorted(
    nx.strongly_connected_components(G),
    key=len,
    reverse=True,
)

weak_component_map = {}
for component_id, component_nodes in enumerate(weak_components, start=1):
    for node in component_nodes:
        weak_component_map[node] = component_id

strong_component_map = {}
for component_id, component_nodes in enumerate(strong_components, start=1):
    for node in component_nodes:
        strong_component_map[node] = component_id

nodes["weak_component_id"] = (
    nodes["user_id"].map(weak_component_map).astype("int64")
)

nodes["strong_component_id"] = (
    nodes["user_id"].map(strong_component_map).astype("int64")
)

nodes["in_giant_weak_component"] = nodes["weak_component_id"] == 1
nodes["in_giant_strong_component"] = nodes["strong_component_id"] == 1

giant_weak_nodes = len(weak_components[0]) if weak_components else 0
giant_strong_nodes = len(strong_components[0]) if strong_components else 0

giant_weak_node_set = weak_components[0] if weak_components else set()
giant_strong_node_set = strong_components[0] if strong_components else set()

giant_weak_edges = G.subgraph(giant_weak_node_set).number_of_edges()
giant_strong_edges = G.subgraph(giant_strong_node_set).number_of_edges()

add_metric(
    summary_rows,
    "n_weak_components",
    "Number of weakly connected components.",
    len(weak_components),
)

add_metric(
    summary_rows,
    "giant_weak_component_nodes",
    "Number of users in the largest weakly connected component.",
    giant_weak_nodes,
)

add_metric(
    summary_rows,
    "share_nodes_in_giant_weak_component",
    "Share of all users in the largest weakly connected component.",
    safe_share(giant_weak_nodes, n_nodes),
)

add_metric(
    summary_rows,
    "giant_weak_component_edges",
    "Number of directed edges contained in the largest weakly connected component.",
    giant_weak_edges,
)

add_metric(
    summary_rows,
    "n_strong_components",
    "Number of strongly connected components.",
    len(strong_components),
)

add_metric(
    summary_rows,
    "giant_strong_component_nodes",
    "Number of users in the largest strongly connected component.",
    giant_strong_nodes,
)

add_metric(
    summary_rows,
    "share_nodes_in_giant_strong_component",
    "Share of all users in the largest strongly connected component.",
    safe_share(giant_strong_nodes, n_nodes),
)

add_metric(
    summary_rows,
    "giant_strong_component_edges",
    "Number of directed edges contained in the largest strongly connected component.",
    giant_strong_edges,
)


# ------------------------------------------------------------------
# 7. COMPONENT DISTRIBUTIONS
# ------------------------------------------------------------------
weak_component_distribution = pd.DataFrame(
    {
        "component_type": "weak",
        "component_id": range(1, len(weak_components) + 1),
        "n_nodes": [len(component) for component in weak_components],
    }
)

strong_component_distribution = pd.DataFrame(
    {
        "component_type": "strong",
        "component_id": range(1, len(strong_components) + 1),
        "n_nodes": [len(component) for component in strong_components],
    }
)

component_distribution = pd.concat(
    [weak_component_distribution, strong_component_distribution],
    ignore_index=True,
)

component_distribution["share_nodes"] = (
    component_distribution["n_nodes"] / n_nodes
)


# ------------------------------------------------------------------
# 8. SAVE OUTPUTS
# ------------------------------------------------------------------
print("\n" + "=" * 70)
print("Saving outputs")
print("=" * 70)

summary = pd.DataFrame(summary_rows)

summary.to_csv(
    SUMMARY_CSV,
    index=False,
)

nodes.to_csv(
    NODES_CSV,
    index=False,
)

edge_weight_distribution.to_csv(
    EDGE_WEIGHT_DISTRIBUTION_CSV,
    index=False,
)

component_distribution.to_csv(
    COMPONENT_DISTRIBUTION_CSV,
    index=False,
)


# ------------------------------------------------------------------
# 9. FINAL OUTPUT
# ------------------------------------------------------------------
print("\nOutputs saved:")
print(SUMMARY_CSV)
print(NODES_CSV)
print(EDGE_WEIGHT_DISTRIBUTION_CSV)
print(COMPONENT_DISTRIBUTION_CSV)

print("\nDone.")