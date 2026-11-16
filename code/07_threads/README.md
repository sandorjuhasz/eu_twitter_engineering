# Conversation reconstruction and thread diagnostics

This pipeline reconstructs observed Twitter conversations across all cities in the source data and stores them in a **single PostgreSQL `thread_table`**, identified by `(city, conversation_id)`. It also produces city-level diagnostics and a notebook for comparing conversation characteristics. 

## Files and execution

| Step | File | Purpose |
|---|---|---|
| 1 | `01_create_conversation_table.py` | Reconstructs conversations and creates the shared `thread_table`. |
| 2 | `02_calculate_thread_stats.py` | Exports conversation-level diagnostics by city. |
| 3 | `03_thread_descriptives.ipynb` | Visualizes and compares the exported statistics; executed and saved automatically. |
| Runner | `run_thread_pipeline.sh` | Executes steps 1–3 sequentially and saves a timestamped log. |

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

All statistics are reported by city. The notebook reads these CSVs, displays distributions and supports cross-city comparisons using relative frequencies.

## Empirical summary

**Source:** `02_calculate_thread_stats.py` pipeline log (`/thread_statistics/logs fodler`) and `03_thread_descriptives_executed.ipynb`. 

We have **139.2 million observed conversations** across Amsterdam, London and Portland. These are conversations reconstructed from the available tweets, not necessarily complete Twitter threads. The following table combines the pipeline log's conversation and root-reconstruction counts with the notebook's cross-city comparisons.

| Measure | Amsterdam | London | Portland |
|---|---:|---:|---:|
| Observed tweets | 20,936,901 | 129,941,246 | 16,022,182 |
| Conversations | 17,717,944 | 107,353,003 | 14,166,116 |
| Single-tweet conversations | 90.7% | 89.7% | 93.0% |
| Multi-tweet conversations | 1,645,301 | 11,085,182 | 987,137 |
| Multi-user conversations | 0.94% | 1.45% | 0.65% |
| Conversations with observed root | 74.8% | 75.1% | 79.5% |
| Roots reconstructed from retweets | 1,952 | 4,257 | 130 |
| Root recovery among missing-root conversations with retweet evidence | 99.74% | 99.91% | 100.00% |
| 99th percentile of conversation duration | 12.8 h | 17.4 h | 8.0 h |

**Main patterns.** Conversation sizes are highly skewed: approximately 90–93% contain only one observed non-retweet tweet. Multi-user conversations are particularly rare (0.65–1.45% of all conversations), even among the much larger London sample. The original root tweet is observed in roughly three-quarters of conversations, with somewhat higher coverage in Portland. Although retweet-based recovery succeeds in almost every missing-root case *where suitable retweet evidence exists*, it reconstructs only a few thousand roots across the three cities and therefore does not substantially reduce overall root missingness.


