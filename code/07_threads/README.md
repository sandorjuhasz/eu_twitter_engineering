# Conversation reconstruction and thread diagnostics

This pipeline reconstructs observed Twitter conversations across all cities in the source data and stores them in a **single PostgreSQL `thread_table`**, identified by `(city, conversation_id)`. It also produces city-level diagnostics and a notebook for comparing conversation characteristics. 

## Files and execution

| Step | File | Purpose |
|---|---|---|
| 1 | `01_create_conversation_table.py` | Reconstructs conversations and creates the shared `thread_table`. |
| 2 | `02_calculate_thread_stats.py` | Exports conversation-level diagnostics by city. |
| Analysis | `03_thread_descriptives.ipynb` | Visualizes and compares the exported statistics; run manually. |
| Runner | `run_thread_pipeline.sh` | Executes steps 1–2 sequentially. |

Run from `src/threads/`:

```bash
bash run_thread_pipeline.sh
```

For longer runs, use `tmux`:

```bash
tmux new -s thread_pipeline
bash run_thread_pipeline.sh
```


## Conversation reconstruction

The input is the PostgreSQL `tweet` table, deduplicated by `(city, tweet_id)`. Original tweets, replies and quotes contribute to the observed conversation text in chronological order. Retweets are excluded from this text but may help reconstruct missing root text.

The resulting `thread_table` contains observed tweet and user counts, conversation duration, root-observation and reconstruction indicators, `core_thread_text` and `corrected_thread_text`.

**Interpretation:** Conversations represent observed Twitter data rather than necessarily complete conversations. Retweet-based root recovery provides an estimate of missing text, not an observed original tweet. Multiple tweets within a conversation may originate from a single user.

## Thread diagnostics

CSV outputs are saved under:

`/mnt/common-hdd/group-dirs/twitter-2025-project/thread_statistics/`

| File | Measures |
|---|---|
| `city_summary.csv` | Conversation and tweet counts, singletons (w only one tweet), multi-tweet/multi-user conversations, root availability and retweet coverage. |
| `thread_size_distribution.csv` | Distribution of observed tweets per conversation. |
| `users_per_multi_tweet_conversation.csv` | Number of distinct users in multi-tweet conversations. |
| `root_by_thread_size.csv` | Observed-root status by conversation size, capped at 10 tweets. |
| `root_text_sources.csv` | Source and availability of root text. |
| `singleton_composition.csv` | Root/reply/quote composition of singletons. |
| `duration_distribution.csv` | Median, 90th and 99th percentiles of conversation duration. |

All statistics are reported by city. The notebook reads these CSVs, displays distributions and supports cross-city comparisons using relative frequencies. It does not query PostgreSQL. Figures and executed notebooks are not automatically saved.
