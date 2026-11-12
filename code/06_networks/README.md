# Interaction networks --- Documentation

**Database:** `twitter_cities_v2`

**Network source:** `interaction_table`

**Network tables:** `interaction_network_directed`, `interaction_network_undirected`

**Descriptive analysis currently implemented for:** London

**Observed London interaction period in the executed notebooks:** 2013-01-01 to 2022-12-31

---

## 1. Overview

This pipeline constructs a cleaned tweet-level interaction table from the database's reply and mention networks, aggregates those interactions into city-specific directed and undirected user interaction networks, and then produces descriptive statistics and plots for the London subset.

The full pipeline is:

`mention_network + reply_network + tweet → interaction_table → directed/undirected interaction networks → descriptives → plots`

### 1.1 Tweet-level `interaction_table`

`01_create_interaction_table.py` combines the existing `mention_network` and `reply_network` tables.

The mention and reply inputs are first processed separately. Retweets are excluded using `tweet.tweet_type`. Within each input network, duplicate observations are then collapsed to one row per `city × tweet_id × source user × target user`

The deduplicated reply and mention tables are combined with a full outer join on this complete key. If the same tweet-level source-target interaction occurs in both input tables, it is represented by a single row in `interaction_table`.

Then we create an `interaction_type` variable which comprise mutually exclusive values:
| `interaction_type` | Meaning |
| --- | --- |
| `1` | reply only |
| `2` | mention only |
| `3` | both reply and mention |

Here, **both** means: the same tweet is a reply to a user and also mentions that user.

The final `interaction_table` therefore contains one row per: `city × tweet_id × source user × target user`

with the following columns:

| Column | Description |
| --- | --- |
| `city` | City associated with the tweet |
| `tweet_id` | Tweet generating the interaction |
| `created_at` | Timestamp of the interaction tweet |
| `user_id1_source` | User generating the reply and/or mention |
| `user_id2_interaction` | User targeted by the reply and/or mention |
| `interaction_type` | `1 = reply only`, `2 = mention only`, `3 = both` |

A unique index is created on `(city, tweet_id, user_id1_source, user_id2_interaction)`. Additional indices are created for the source-target pair, `tweet_id`, `created_at`, `city`, and `interaction_type`.

The temporary deduplicated mention and reply tables are dropped after the final `interaction_table` has been created.

**Self-interactions are retained in `interaction_table`.** They are removed only in the next step, when the directed and undirected user-user network tables are constructed. I.e. the `interaction_table` is the cleaned tweet-level interaction table, whereas the network tables exclude self-loops.

### 1.2 From tweet-level interactions to network edges

`02_create_networks.py` aggregates the tweet-level `interaction_table` into directed and undirected user-pair edges. At this stage, self-interactions are excluded using: `user_id1_source <> user_id2_interaction`

For every resulting network edge:
`edge_weight = reply_only_weight + mention_only_weight + both_weight`

where the three subtype weights count the tweet-level rows classified as reply only, mention only, and both.

---

## 2. Pipeline

| Step | File | Input | Main output / purpose |
| --- | --- | --- | --- |
| 01 | `01_create_interaction_table.py` | PostgreSQL `mention_network`, `reply_network`, and `tweet` | Validates interactions against the tweet table, excludes retweets, deduplicates tweet-level reply/mention edges, combines them, and creates `interaction_table` |
| 02 | `02_create_networks.py` | PostgreSQL `interaction_table` | Excludes self-interactions and builds directed and undirected city-specific network tables |
| 03a | `03_network_descriptives_directed.py` | `interaction_network_directed` | London directed network summary, node measures, edge-weight distribution, and weak/strong components |
| 03b | `03_network_descriptives_undirected.py` | `interaction_network_undirected` | London undirected network summary, node measures, edge-weight distribution, and connected components |
| 04a | `04_network_plots_directed.ipynb` | directed descriptive CSVs | Tables and plots for directed network structure |
| 04b | `04_network_plots_undirected.ipynb` | undirected descriptive CSVs | Tables and plots for undirected network structure |

The `interaction_table` and network tables are created for every city represented in the relevant database inputs. The current descriptive scripts and notebooks explicitly filter to `city = 'london'`.

---

## 3. PostgreSQL network tables

### 3.1 `interaction_network_directed`

One row represents one observed **directed** user pair within a city: `city × source user × target user`

Direction is preserved: an edge from A to B is distinct from an edge from B to A.

| Column | Type produced by SQL | Description |
| --- | --- | --- |
| `city` | inherited from input | City associated with the interaction records |
| `user_id1_source` | inherited from input | Source user: the user sending the reply and/or mention |
| `user_id2_interaction` | inherited from input | Target user: the user receiving the reply and/or mention |
| `edge_weight` | BIGINT | Total number of tweet-level interactions from source to target |
| `reply_only_weight` | BIGINT | Number of source→target interactions classified as reply only (`interaction_type = 1`) |
| `mention_only_weight` | BIGINT | Number classified as mention only (`interaction_type = 2`) |
| `both_weight` | BIGINT | Number classified as both reply and mention (`interaction_type = 3`) |
| `first_created_at` | timestamp inherited from input | Earliest observed interaction from source to target |
| `last_created_at` | timestamp inherited from input | Latest observed interaction from source to target |

**Unique edge index:** `(city, user_id1_source, user_id2_interaction)`

**Additional indices:** `edge_weight`, `first_created_at`, `last_created_at` Self-interactions are removed before aggregation.

### 3.2 `interaction_network_undirected`

One row represents one observed **unordered** user pair within a city: `city × unordered user pair`

Interactions in both directions are combined. The two endpoint IDs are stored in deterministic order using `LEAST()` and `GREATEST()`.

| Column | Type produced by SQL | Description |
| --- | --- | --- |
| `city` | inherited from input | City associated with the interaction records |
| `user_id1` | inherited ID type | Smaller of the two user IDs |
| `user_id2` | inherited ID type | Larger of the two user IDs |
| `edge_weight` | BIGINT | Total number of tweet-level interactions between the two users in either direction |
| `reply_only_weight` | BIGINT | Number of interactions between the pair classified as reply only |
| `mention_only_weight` | BIGINT | Number classified as mention only |
| `both_weight` | BIGINT | Number classified as both reply and mention |
| `first_created_at` | timestamp inherited from input | Earliest observed interaction between the pair |
| `last_created_at` | timestamp inherited from input | Latest observed interaction between the pair |

**Unique edge index:** `(city, user_id1, user_id2)`

**Additional indices:** `edge_weight`, `first_created_at`, `last_created_at` Self-interactions are removed before aggregation.

---

## 4. London network snapshot

The following results come from the executed directed and undirected plotting notebooks (pipeline run on 2026-11-10). They supersede earlier London snapshot figures. Directed and undirected columns use the same underlying interaction events, but different edge definitions.

| Measure | Directed | Undirected |
|---|---:|---:|
| Unique users | 10,350,047 | 10,350,047 |
| Edges | 40,477,389 | 40,007,328 |
| Tweet-level interactions | 117,232,348 | 117,232,348 |
| Network density | 3.7786 × 10⁻⁷ | 7.4694 × 10⁻⁷ |
| Mean edge weight | 2.8962 | 2.9303 |
| Median edge weight | 1 | 1 |
| Share of edges observed once | 67.32% | 67.16% |
| First observed interaction | 2013-01-01 00:00:01 | 2013-01-01 00:00:01 |
| Last observed interaction | 2022-12-31 23:59:55 | 2022-12-31 23:59:55 |

Interaction composition is the same in both networks, since direction aggregation does not change the underlying events:

| Interaction category | N | Share |
|---|---:|---:|
| Reply only | 13,768,305 | 11.74% |
| Mention only | 62,494,053 | 53.31% |
| Both reply and mention | 40,969,990 | 34.95% |

The directed network has network-level reciprocity **0.02323**: approximately **2.32%** of directed edges have an observed reverse edge.

The undirected network has **100,943 connected components**. Its largest component contains **10,061,870 users (97.22%)** and **39,819,690 edges**.

The directed network has **9,774,936 strongly connected components** (not directly comparable to the undirected connected-component count). Its largest strongly connected component contains **567,217 users (5.48%)** and **9,237,358 directed edges**. The largest weakly connected component contains **40,289,363 directed edges**.

Both notebooks executed without recorded cell errors. These are outputs of the executed notebooks, not a fresh query against PostgreSQL.

---

## 5. Directed descriptive outputs

Output directory: `/mnt/common-hdd/group-dirs/twitter-2025-project/interaction_network_descriptives/directed/`

### 5.1 `interaction_network_london_summary.csv`

Long-format summary table with columns:

| Column | Description |
| --- | --- |
| `metric` | Machine-readable metric name |
| `description` | Human-readable definition |
| `value` | Metric value |

It contains network size, density, reciprocity, interaction composition, observation period, edge-weight summaries, node-level distribution summaries, and weak/strong component statistics.

For continuous/count distributions the script records: mean, median, p75, p90, p95, p99, and maximum.

### 5.2 `interaction_network_london_nodes.csv`

One row per user appearing in at least one London interaction edge.

| Column | Description |
| --- | --- |
| `user_id` | Twitter user ID |
| `in_degree` | Number of distinct incoming directed neighbors |
| `out_degree` | Number of distinct outgoing directed neighbors |
| `in_strength` | Total incoming interaction count |
| `out_strength` | Total outgoing interaction count |
| `degree` | `in_degree + out_degree`; a reciprocal neighbor can contribute twice |
| `strength` | `in_strength + out_strength` |
| `n_unique_neighbors` | Distinct interaction partners in either direction; reciprocal partner counted once |
| `n_reciprocal_neighbors` | Distinct partners for which both A→B and B→A exist |
| `node_reciprocity` | `2 × n_reciprocal_neighbors / degree`; share of a user’s incident directed edges that are reciprocated |
| `weak_component_id` | Weak-component rank; component 1 is the largest |
| `strong_component_id` | Strong-component rank; component 1 is the largest |
| `in_giant_weak_component` | Whether user belongs to largest weakly connected component |
| `in_giant_strong_component` | Whether user belongs to largest strongly connected component |

Note: the directed `degree` is **not** the number of unique partners. Use `n_unique_neighbors` for that quantity.

### 5.3 `interaction_network_london_edge_weight_distribution.csv`

One row per observed directed edge-weight value.

| Column | Description |
| --- | --- |
| `edge_weight` | Number of interactions on a directed edge |
| `n_edges` | Number of directed edges with exactly this weight |
| `share_edges` | Share of directed edges with exactly this weight |
| `cumulative_share_edges` | Cumulative share as edge weight increases |

### 5.4 `interaction_network_london_component_distribution.csv`

One row per weak or strong component.

| Column | Description |
| --- | --- |
| `component_type` | `weak` or `strong` |
| `component_id` | Component rank by size; 1 = largest |
| `n_nodes` | Number of users in the component |
| `share_nodes` | Component size divided by all network users |

---

## 6. Undirected descriptive outputs

Output directory: `/mnt/common-hdd/group-dirs/twitter-2025-project/interaction_network_descriptives/undirected/`

### 6.1 `interaction_network_undirected_london_summary.csv`

Long-format summary table with `metric`, `description`, and `value`. It contains network size, density, interaction composition, observation period, edge-weight summaries, degree/strength summaries, and connected-component statistics.

### 6.2 `interaction_network_undirected_london_nodes.csv`

One row per user appearing in at least one London interaction edge.

| Column | Description |
| --- | --- |
| `user_id` | Twitter user ID |
| `degree` | Number of distinct undirected interaction partners |
| `strength` | Total interaction weight over all incident undirected edges |
| `component_id` | Connected-component rank by size; 1 = largest |
| `in_giant_component` | Whether user belongs to the largest connected component |

The script includes two useful internal identities:

-   `sum(degree) = 2 × number of undirected edges`

-   `sum(strength) = 2 × total interaction count`

### 6.3 `interaction_network_undirected_london_edge_weight_distribution.csv`

| Column | Description |
| --- | --- |
| `edge_weight` | Number of interactions between an unordered user pair |
| `n_edges` | Number of undirected edges with exactly this weight |
| `share_edges` | Share of undirected edges with exactly this weight |
| `cumulative_share_edges` | Cumulative share as edge weight increases |

### 6.4 `interaction_network_undirected_london_component_distribution.csv`

| Column | Description |
| --- | --- |
| `component_id` | Component rank by size; 1 = largest |
| `n_nodes` | Number of users in the component |
| `share_nodes` | Component size divided by all network users |

---

## 7. Plotting notebooks

Executed notebooks are saved under: `/mnt/common-hdd/group-dirs/twitter-2025-project/interaction_network_descriptives/executed_notebooks/` 
The plotting notebooks save PNG figures to the `plots/` subfolder of their respective `directed/` and `undirected/` output directories.

### 7.1 Directed notebook

`04_network_plots_directed.ipynb` reads the four directed descriptive CSVs. It does not alter the PostgreSQL network table.

It presents and plots:
-   overall network summary;
-   edge-weight distribution;
-   in-degree and out-degree;
-   total directed degree;
-   number of unique neighbors;
-   in-strength, out-strength, and total strength;
-   network reciprocity;
-   weakly connected components;
-   strongly connected components.

Cumulative plots use the interpretation **number/share of observations with value at least x**. Plot ranges are generally truncated at a high quantile for readability rather than deleting observations from the underlying descriptive data.

### 7.2 Undirected notebook

`04_network_plots_undirected.ipynb` reads the four undirected descriptive CSVs and presents:

-   overall network summary;
-   undirected edge-weight distribution;
-   degree distribution;
-   strength distribution;
-   connected components and giant component;
-   giant-component summary and connected-component size plots.

The executed notebook **does not create** the previously documented interactive high-degree network-core visualization. Its final cell prints a path to `undirected_high_degree_core_interactive.html`, but no cell in the uploaded notebook writes that file. The printed path alone is not evidence that the HTML exists.

---

## 8. Measure definitions

### Edge weight

Number of observed tweet-level reply/mention interaction records represented by an edge. In the directed network this is source→target specific; in the undirected network both directions are combined.

### Degree

In the directed network:
-   `in_degree`: number of distinct users with an edge into the focal user;
-   `out_degree`: number of distinct users with an edge from the focal user;
-   `degree = in_degree + out_degree`.

In the undirected network, `degree` is simply the number of distinct interaction partners.

### Strength

Weighted analogue of degree. It counts interaction events rather than distinct partners.

### Reciprocity

At network level, `nx.reciprocity(G)` is used. It measures the share of directed edges that are reciprocated by an edge in the opposite direction.

At node level: `node_reciprocity = 2 × reciprocal_neighbors / (in_degree + out_degree)`

### Density

Directed: `number of directed edges / [N × (N − 1)]` 
Undirected: `number of undirected edges / [N × (N − 1) / 2]` 
Self-edges are excluded in both cases.

### Components

-   **Weakly connected component:** connected after ignoring direction.
-   **Strongly connected component:** every pair of nodes is mutually reachable through directed paths.
-   **Undirected connected component:** standard connected component of the undirected graph.

Component IDs are assigned after sorting components by size, so ID 1 is the largest component. IDs of equally sized smaller components should not be treated as persistent identifiers across reruns.

---

## 9. About the networks and their structure

### Network size and structure

- The network is huge: around **10.4 million users**, **40 million connections**, and **117 million interactions**. But most connections are weak: about **two-thirds** involve only a single interaction.
- The average connection involves around **3 interactions**, but this is likely driven by a relatively small number of more active user pairs. For most users, interaction ties are much weaker.
- The directed and undirected networks have almost the same number of edges (**40.5 vs. 40.0 million**). This already suggests that relatively few user pairs interact in both directions.

### Reciprocity and interaction patterns

- Only **2.3%** of directed connections are reciprocated. Most interactions are therefore one-sided: one user replies to or mentions another without an observed interaction in the opposite direction.
- Mentions dominate the network. Around **53%** of interactions are mentions only, **12%** are replies only, and **35%** are both (a reply that also mentions the recipient).
- This may suggest two things: 1) The network captures a broad range of interactions, but not necessarily strong social relationships, since mentioning someone does not mean that the two users communicate regularly. 2) This could also be partly an artifact of data, since only users with sufficiently many geolocated tweets were included in the dataset (so we may not observe their interaction partners' tweets if those users do not meet this criterion).

### Connectivity

- The undirected network is remarkably well connected: **97.2%** of users belong to a single giant component. Almost everyone is connected to everyone else through some chain of interactions when direction is ignored.
- However, the directed network looks very different. Only **5.5%** of users belong to the largest strongly connected component, where users can reach one another through directed interaction paths.
- So the network is highly connected in a structural sense, but much less interconnected when we account for the direction of interactions.

### What does this mean for our analysis?

- A connection is not necessarily a meaningful social tie. Most edges represent a single interaction, and reciprocity is extremely low. We should  be **extreamly** careful  interpreting the network as a social or friendship network.
- The giant component is not necessarily evidence of a cohesive community. Although **97%** of users are connected, this can happen through long chains of weak, one-sided interactions.

Overall: The London Twitter network is extremely large and structurally connected, but its connections are predominantly weak and one-sided. However, this may partly the result of the data gathering approach. Nevertheless, we have to keep in mind this important limitation: we cannot reliably distinguish genuinely one-sided interactions from missing reciprocal interactions. Therefore, analyses that rely on network structure, particularly reciprocity and connectivity, should be interpreted with caution.

---

