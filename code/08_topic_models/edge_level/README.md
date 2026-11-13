# User-user topic modeling: London Twitter interaction network

## 1. Overview

**Upstream dependency:** `src/threads/` must first construct the shared `thread_table` with a `city` column. 

This pipeline assigns one topic to each **undirected user-user edge** (if their threads comprise enough text). For each pair, the document combines the cleaned text of the conversation threads in which the two users interacted. **We will focus on London now on.**

Outputs are saved under `/mnt/common-hdd/group-dirs/twitter-2025-project/topic_models/edge_level/`:
```text
edge/

├── shared/                 # embeddings and UMAP
├── umap_kmeans/
│   ├── k_selection/        # K/seed fits and validation results
│   └── final_model/        # final fit, topic assignments and diagnostics
├── bertopic/               # reserved for later comparison
└── taxonomy/               # manually coded topic taxonomy
```

## 2. Conceptual unit: what is a document?
Each document corresponds to one **undirected user-user edge**. For each unordered pair `(user_id1, user_id2)`, the upstream corpus construction:

1. Identifies observed interactions between the users, regardless of direction.
2. Links these interactions to Twitter conversations.
3. Includes each conversation only once per pair.
4. Uses the corrected conversation text, including reconstructed roots from retweets where available.
5. Concatenates the linked conversations chronologically into one document.

Repeated interactions within the same conversation do not duplicate its text. The document includes the full observed conversation text, not just the tweets that generated the interaction. This may include tweets from other participants.

The assigned topic summarizes the main subject of the conversations linked to the pair. It does not necessarily describe either user's interests or everything the pair discussed.

## 3. Pipeline and execution
Run the pipeline from this directory, after completing `src/threads/`:
```bash
bash run_topic_pipeline.sh
```

Choose which steps to run by setting `START_STEP` and `END_STEP` at the top of the Bash script.

- **`00a`–`00b`:** Build the edge corpus and clean the text.
- **`00c`:** Execute the descriptive notebook and save its outputs as an executed notebook.
- **`01`–`04`:** Generate embeddings, run UMAP, and select the number of topics.
- **`05`:** Fit the final model using `FINAL_K` and `FINAL_FIT_SEED` from `pipeline_config.py`.
- **`06`–`08`:** Evaluate and interpret the final topics.
- **`09`:** Attach finalized topics to PostgreSQL. Requires `CONFIRM_DB_WRITE=YES`.

The `00c` descriptive notebook runs automatically and is saved to `edge/corpus_descriptives/executed_notebooks/00c_edge_corpus_descriptives_executed.ipynb`.

| Stage | Script | Purpose and main output |
|---|---|---|
| 00a | `00a_create_edge_corpus.py` | Build the undirected edge corpus from interactions and the shared `thread_table`; **recreates** `interaction_edge_thread_corpus_london` |
| 00b | `00b_clean_edge_text.py` | Add `edge_thread_cleaned` and `n_cleaned_words` |
| 00c | `00c_edge_corpus_descriptives.ipynb` | Create corpus descriptives and save the executed notebook |
| 01 | `01_generate_embeddings.py` | Create full-corpus embeddings: `shared/embeddings_384d.npy` |
| 02 | `02_train_umap_5m.py` | Deterministic 5M sample, fitted UMAP, training coordinates in `shared/` |
| 03 | `03_transform_full_corpus_umap.py` | Full-corpus 5D UMAP: `shared/umap_5d.npy` |
| 04 | `04_select_k_multiseed.py` | K × seed models, fit results, matched silhouette evaluations in `umap_kmeans/k_selection/` |
| 05 | `05_finalize_selected_model.py` | Manually selected fit, topic IDs and distances in `umap_kmeans/final_model/` |
| 06 | `06_final_confidence.py` | Robust within-topic centroid-distance scores and low-confidence flags |
| 07 | `07_final_topic_representation.py` | Full-corpus c-TF-IDF, characteristic terms, random examples |
| 08 | `08_final_semantic_examples.py` | Core, typical and peripheral examples per topic |
| 09 | `09_attach_edge_topics.py` | **Later only, after validation:** update existing PostgreSQL edge-corpus table with topics and taxonomy |


## 4. Edge corpus construction and modeling sample
`00a_create_edge_corpus.py` reads `interaction_table`, `tweet` and the shared `thread_table` and creates the PostgreSQL table `interaction_edge_thread_corpus_london` for London. It aggregates the conversations linked to each undirected pair in chronological order, along with interaction, thread and text-volume measures. `00b_clean_edge_text.py` standardizes URLs and mentions, retains hashtag text, normalizes whitespace, and adds cleaned word counts. The notebook `00c_edge_corpus_descriptives.ipynb` examines the resulting corpus. The modeling stages read the resulting table.

Each row represents an undirected user pair. The text used for modeling is `edge_thread_cleaned`, which combines the cleaned texts of the conversations linked to that pair. These conversations may also contain tweets from other participants.

Only rows satisfying the following condition are included:
```sql
edge_thread_cleaned IS NOT NULL

AND n_cleaned_words >= 10
```

### Data sources and modeling configuration
| Setting | Value |
|---|---|
| City | London |
| Corpus construction inputs | `interaction_table`, `tweet`, `thread_table` |
| Edge corpus / modeling input | `interaction_edge_thread_corpus_london` |
| Text column | `edge_thread_cleaned` |
| Eligible documents | `edge_thread_cleaned IS NOT NULL AND n_cleaned_words >= 10` |
| Embedding model | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| Embedding dimensions | 384 |
| Maximum sequence length | 128 transformer tokens |
| UMAP | 5 dimensions |
| Clustering | MiniBatchKMeans |
| Currently configured final K | `175` |
| Currently configured final fit seed | `102345` |

## 5. Embeddings
`01_generate_embeddings.py` uses `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` with 384 dimensions, `max_seq_length = 128`, batch size 64, DB fetch size 10,000, and flushes every 100,000 documents. It writes `shared/embeddings_384d.npy`, `n_documents.txt`, `embedding_progress.json` while running, and `embedding_metadata.json` on completion. 

Long documents are truncated at 128 transformer tokens. Because edge texts concatenate conversation context chronologically, embeddings of long documents emphasize their beginning rather than the full observation period.

## 6. UMAP
`02_train_umap_5m.py` draws a deterministic sample of up to 5,000,000 rows without replacement (seed 12345), fits UMAP with `n_neighbors=15`, `n_components=5`, `min_dist=0.0`, `metric='cosine'`, `low_memory=True`, and saves the model, sample indices, training coordinates and metadata under `shared/`. `03_transform_full_corpus_umap.py` then transforms all eligible embeddings in restartable chunks of 50,000, writing `shared/umap_5d.npy` and progress/metadata files. Both steps may require substantial memory and compute.

## 7. K selection and final fit
The configured grid is `K_VALUES = [50, 75, 90, 100, 110, 120, 125, 150, 175, 200, 225, 250, 300]`, with 10 fit seeds per K. `04_select_k_multiseed.py` fits full-corpus MiniBatchKMeans (`batch_size=10,000`, `n_init=10`, `max_iter=300`, `reassignment_ratio=0.01`). It computes silhouettes on 10 **matched** random samples of up to 100,000 observations (computationally expensive for exact silhouette scoring), averaging within seed and then across seeds. Inertia is reported as a diagnostic, not an elbow-selection rule. The script records the highest-mean-silhouette K and a representative seed in `selected_model.json`, but **does not automatically determine the final research choice**.

The K grid can be extended in `pipeline_config.py` while preserving existing candidates and matched samples. Add finer values around plausible solutions after inspecting the initial grid, rather than dropping the broad comparison or changing the evaluation protocol mid-comparison.

After inspection, set `FINAL_K` and `FINAL_FIT_SEED` manually. `05_finalize_selected_model.py` reuses the selected fitted model (it does not refit), saves `topics_k{K}.npy`, `assigned_centroid_distance_k{K}.npy`, `topic_sizes_k{K}.csv`, and `final_model_metadata.json` under `umap_kmeans/final_model/`. It can reuse migrated labels; this is safe only if their model and source-corpus provenance match the new run. Centroid distance is **not** a probability that a topic is correct.

## 8. Topic interpretation and validation
`06_final_confidence.py` computes topic-specific median and MAD of assigned-centroid distance, a robust z-score and a global high-distance flag (configured quantile 0.85). `07_final_topic_representation.py` estimates a vocabulary from up to 5,000 examples per topic and computes full-corpus c-TF-IDF using unigrams/bigrams, up to 100,000 features; it also saves random document examples. `08_final_semantic_examples.py` selects five examples per topic near the 10th, 50th and 90th within-topic distance quantiles (core, typical, periphery).

## 9. Taxonomy and later SQL write-back
Stage 09 currently requires `FINAL_K=175` and expects a human-coded mapping at `edge/taxonomy/k175_final_taxonomy_mapping.csv`, with one row for each topic 0–174. If the final K differs, stage 09 and the taxonomy schema must be adapted before use. This mapping is an **input required by stage 09**, not generated by the modeling scripts. Topic validation and taxonomy coding must be completed first.

`09_attach_edge_topics.py` is intentionally deferred. It updates **the existing** `interaction_edge_thread_corpus_london` PostgreSQL table directly.

## 10. What the topics mean
A topic groups edge documents with similar text. Each eligible pair receives one KMeans topic assignment, based on the combined text of its linked conversations.

This assignment should not be treated as an individual user's interest, evidence that every conversation between the pair concerned the same subject, or a description of their communication over time. The model uses one document per pair for the entire observation period, so it cannot capture changes in topics within a pair.

## 11. Important interpretation caveats
#### Text from other participants
Linked conversations can contain tweets by users other than the two endpoints. The topic is based on the text of these conversations, not only the pair's own tweets.

#### Unequal text volume
Most edge documents are short, while a small share contain much more text.

#### Transformer truncation
The embedding model processes at most 128 transformer tokens per document. Since conversations are concatenated chronologically, long documents are represented mainly by their beginning.

#### One topic per edge
KMeans assigns one topic to every eligible edge, even if the document covers several subjects or fits no cluster particularly well. There is no noise or outlier class. Centroid distances and core/typical/peripheral examples help assess these assignments, but distances are not probabilities.
