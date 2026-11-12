# London conversation and edge-thread corpus

This pipeline reconstructs observed Twitter conversations in London, produces thread-level diagnostics, and combines conversation text at the undirected user-pair level. It also cleans the resulting edge-level text for subsequent analysis. PostgreSQL tables are read and written in the `revised` schema.

## Files and order

| Step | File | What it does |
|---|---|---|
| 1 | `01_create_conversation_table.py` | Builds `thread_table_london` from deduplicated London tweets. Original tweets, replies, and quotes form the observed conversation text. Retweets are used only to help recover missing root text. |
| 2 | `02_calculate_thread_stats.py` | Produces thread-size, root-status, and user-count diagnostics, saved as CSVs and figures. |
| 3 | `03_edge_level_corpus.py` | Links interactions to conversations and builds `interaction_edge_thread_corpus_london`, with one row per undirected user pair. |
| 4 | `04_clean_edge_thread_text.py` | Cleans the edge-level text and adds `edge_thread_cleaned` and `n_cleaned_words` to the corpus table. |
| 5 | `05_edge_thread_corpus_descriptives.ipynb` | Examines edge-corpus coverage, text lengths, cleaned-text eligibility, and modeling feasibility. |


## Shared output folder
Generated CSVs, plots, logs, and executed notebooks are saved under:

```text
/mnt/common-hdd/group-dirs/twitter-2025-project/thread_statistics/
├── *.csv, *.png
├── logs/
└── executed_notebooks/
```

## Run

```bash
bash run_thread_pipeline.sh
```

For longer runs, use `tmux`:

```bash
tmux new -s thread_pipeline
bash run_thread_pipeline.sh
```

The scripts run in the order listed above. The pipeline stops if a step fails.

**Rerunning the pipeline:** Steps 1 and 3 recreate their PostgreSQL output tables. Step 4 then regenerates cleaned text and word counts. Existing topic assignments or other downstream columns in the edge corpus are lost when Step 3 rebuilds the table; back them up separately if needed. The cleaning script alone can resume after interruption without repeating completed rows.

## Notes on interpretation

- The thread table contains **observed tweets**, not necessarily complete Twitter conversations.
- Retweet-based root recovery provides an estimate of missing root text; it does not mean the original root tweet was observed.
- The edge corpus combines conversation text associated with each interacting user pair. This is conversation context, not necessarily text authored by either or both users.
- Text cleaning replaces URLs and mentions with placeholders, removes hashtag markers while retaining their text, decodes HTML entities, and normalizes whitespace. It does not remove stopwords, punctuation, or emojis, or apply stemming or lemmatization.
- `n_cleaned_words` counts whitespace-separated tokens in the cleaned text, including `URL` and `@USER` placeholders.
- The notebook reports both raw and cleaned text statistics. The cleaned-text sections require Step 4. A 500-word window is distinct from the embedding model’s 128-transformer-token limit; actual token lengths can be checked in the optional tokenizer diagnostic.

## Key findings from the edge-thread corpus notebook

- **Coverage:** The corpus contains **39.95 million user-pair connections (edges)** and **89.84 million links between user pairs and conversation threads**, which together contain **241.90 million tweets**. These are sums across edges: the same thread and its tweets can be counted for multiple user pairs.
- **Most edges are linked to few conversations:** **74.8%** of edges are associated with just **one thread**, and **25.2%** with more than one. Only **1.0%** are linked to **21 or more threads**.
- **Text is often short:** Average cleaned text length is **150.5 words per edge**, but the distribution is highly skewed. **80.3%** of edges have at least **10 cleaned words**, **53.0%** at least **20**, **23.7%** at least **50**, and just **2.3%** at least **500**.
- **Text is extremely concentrated:** The **top 1%** of edges by cleaned word count across all their associated threads account for **65.6%** of all edge-level cleaned words; the **top 5%** account for **78.0%**.
- **More interactions generally mean more text, but they are not the same thing:** In a sample of up to 200,000 edges, the Spearman correlation is **0.87** between the number of direct interaction tweets between two users and the number of distinct threads associated with their interactions, and **0.63** between the number of direct interaction tweets and the total cleaned word count across their associated threads. The text also includes tweets by other users in those threads.
- **Cleaning barely changes measured word counts:** Raw and cleaned edge-level word counts have a Spearman correlation of approximately **1.00**. This does **not** imply that cleaning leaves the actual text unchanged.
- **Implications for topic modeling:** With a minimum of **10 cleaned words**, **32.08 million edges (80.3%)** are eligible. Limiting each eligible edge to **500 words** retains about **2.11 billion words**, or **35.5%** of the eligible corpus's cleaned-word total; very long edge texts account for much of the original text volume.