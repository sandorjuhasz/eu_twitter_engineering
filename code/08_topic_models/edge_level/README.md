# Edge-level topic-modeling pipeline

This directory contains the cleaned, reproducible pipeline for the current **edge-document UMAP + MiniBatchKMeans model**. The directory structure is deliberately designed so that two planned extensions can be added without mixing outputs:

1. a **BERTopic** specification on the same edge documents;
2. an **edge-thread document** specification, where one observation is one user-pair × conversation/thread and topic assignments are aggregated back to the user-user edge afterwards.

## Permanent output root

```text
/mnt/common-hdd/group-dirs/twitter-2025-project/topic_models/edge_level/  
```

Recommended project tree:

```text
edge_level/
├── edge/                              # current: one aggregated document per user-user edge
│   ├── shared/                        # embeddings + UMAP representation shared by models
│   ├── umap_kmeans/                   # current UMAP + MiniBatchKMeans model
│   │   ├── k_selection/
│   │   └── final_model/
│   ├── bertopic/                      # reserved: BERTopic on the same edge documents
│   └── taxonomy/                      # fine-topic labels + coarser substantive categories
│
└── edge_thread/                       # future: one edge × thread/conversation per observation
    ├── shared/                        # edge-thread embeddings + dimensional representation
    ├── umap_kmeans/                   # optional KMeans version on edge-thread documents
    ├── bertopic/                      # BERTopic on edge-thread documents
    └── aggregation/                   # thread-topic assignments/shares aggregated to edges
```

The current package writes only under `edge/`. The future `edge_thread/` branch should be a separate pipeline/configuration because its SQL source, row identifiers and number of observations will differ.

## Current document definition

The current observation is an undirected user-user **edge document**. All qualifying corrected conversation/thread text linked to the edge is aggregated before embedding. Eligible documents satisfy `n_cleaned_words >= 10`.

SQL rows are read in deterministic order:

```text
city, user_id1, user_id2
```

This ordering is an invariant: row `i` must refer to the same edge in the embedding, UMAP and topic-assignment arrays.

## Current pipeline

1. `01_generate_embeddings.py` — full-corpus multilingual MiniLM embeddings.
2. `02_train_umap_5m.py` — fit UMAP on a deterministic 5M sample.
3. `03_transform_full_corpus_umap.py` — transform all eligible edge documents to 5D.
4. `04_select_k_multiseed.py` — reproducible multi-K, multi-seed validation.
5. `05_finalize_selected_model.py` — finalize the **manually specified** K and fit seed.
6. `06_final_confidence.py` — topic-specific robust centroid-distance diagnostics.
7. `07_final_topic_representation.py` — full-corpus c-TF-IDF representation and random examples.
8. `08_final_semantic_examples.py` — core, typical and peripheral examples for every final topic.

## Manual final-fit choice

`04_select_k_multiseed.py` produces the numerical evidence used for K selection but does **not** determine the final model automatically.

After inspecting the numerical and semantic validation, set in `pipeline_config.py`:

```python
FINAL_K = 175
FINAL_FIT_SEED = 102345
```

`05_finalize_selected_model.py` then uses exactly that already fitted model from `edge/umap_kmeans/k_selection/`.

This separation is intentional: the final fit is an explicit research decision and is not silently changed by a selection rule.

## K selection

The validation grid is:

```text
K = 50, 75, 90, 100, 110, 120, 125, 150, 175, 200, 250
```

Each K is fitted with 10 initialization seeds. Silhouette is evaluated on 10 matched random samples of 100,000 observations. The same evaluation sample is used across models within a repetition, permitting matched comparisons. Inertia is retained as a diagnostic rather than treated as evidence for a forced elbow.

The current evidence supports **K=175** as the fine-grained solution. The final choice should remain documented together with the numerical and semantic validation rather than being hard-coded as an automatic consequence of one metric.

## Interpretation and coarser taxonomy

K=175 is intended as the fine-grained topic taxonomy. After semantic validation, the 175 topics will be labelled and regrouped into a substantively interpretable coarser taxonomy of approximately **20–50 categories**. K=125 and K=150 solutions can be used as auxiliary evidence for grouping, but they do not constrain the final grouping. These edge-level taxonomy files belong under `edge/taxonomy/`; no aggregation step is needed because one observation is already one user-user edge.

The eventual edge-level output should preserve both levels, for example:

```text
topic_fine_id
topic_fine_label
topic_crude_id
topic_crude_label
```

## Planned BERTopic comparison

A BERTopic version will be run on the same edge-document corpus. Its outputs belong under:

```text
edge/bertopic/
```

Where technically appropriate, preprocessing/embedding settings should be shared or explicitly matched so that the comparison is interpretable. Model-specific outputs must not be written into `edge/shared/`.

## Planned edge-thread specification

A later specification will change the unit of observation from one aggregated edge document to one **edge × thread/conversation document**. It belongs under:

```text
edge_thread/
```

Each thread-level observation will receive topic information first. These assignments will then be aggregated to the user-user edge, allowing LDA-like mixed membership at edge level, such as:

- dominant topic;
- topic shares across conversations;
- topic diversity/entropy;
- shares in the coarser 20–50 substantive categories.

The aggregation products belong under:

```text
edge_thread/aggregation/
```

This keeps three conceptually different objects separate: the fine thread-level topic assignment, the aggregated edge-level topic composition, and the current single-document-per-edge model.

## Important embedding limitation

The current sentence-transformer uses `max_seq_length = 128`. Long aggregated edge documents are therefore truncated at the embedding stage. Because the current edge corpus is chronologically concatenated, long-document embeddings disproportionately reflect earlier text. The planned edge-thread specification should reduce this problem because its documents are substantially shorter.

## Final SQL step

After the fine K=175 labels and the coarser taxonomy are frozen, a separate export/write-back stage should attach the final topic variables to the SQL corpus using the same deterministic row order and explicit row-count/order checks. The SQL write-back should be implemented only after the taxonomy is frozen, so model construction and substantive labelling remain separate reproducible stages.
