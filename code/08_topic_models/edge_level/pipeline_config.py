from pathlib import Path

# =============================================================================
# DATA / DOCUMENT UNIT
# =============================================================================
# This package models one aggregated user-user edge document per observation.
# Future pipelines should use the parallel DOCUMENT_UNIT = "edge_thread" branch
# for one edge x conversation/thread document per observation.
DOCUMENT_UNIT = "edge"

CONNECTION_PATH = "/home/ilyesvirag/twitter/venv/connection.json"
SOURCE_TABLE = "interaction_edge_thread_corpus_london"
TEXT_COLUMN = "edge_thread_cleaned"
MIN_CLEANED_WORDS = 10
ORDER_COLS = ("city", "user_id1", "user_id2")

# =============================================================================
# DIRECTORY LAYOUT
# =============================================================================
# Stable project root. Keep model families and document units separate so that
# the same corpus can later be compared with BERTopic, and edge-thread models
# can be added without mixing outputs.
ROOT_DIR = Path("/mnt/common-hdd/group-dirs/twitter-2025-project/topic_models/edge_level")
UNIT_DIR = ROOT_DIR / DOCUMENT_UNIT
SHARED_DIR = UNIT_DIR / "shared"                 # embeddings + UMAP for this document unit
KMEANS_DIR = UNIT_DIR / "umap_kmeans"            # current UMAP + MiniBatchKMeans pipeline
BERTOPIC_DIR = UNIT_DIR / "bertopic"              # reserved for future BERTopic pipeline
TAXONOMY_DIR = UNIT_DIR / "taxonomy"              # final fine-topic labels + coarser substantive taxonomy

for path in (ROOT_DIR, UNIT_DIR, SHARED_DIR, KMEANS_DIR, BERTOPIC_DIR, TAXONOMY_DIR):
    path.mkdir(parents=True, exist_ok=True)

# Backward-compatible alias used by no final script; avoid using it in new code.
BASE_DIR = UNIT_DIR

# =============================================================================
# EMBEDDINGS
# =============================================================================
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MAX_SEQ_LENGTH = 128
EMBEDDING_DIM = 384
EMBED_BATCH_SIZE = 64
DB_FETCH_SIZE = 10_000
EMBED_FLUSH_EVERY = 100_000

# =============================================================================
# UMAP
# =============================================================================
UMAP_TRAIN_SIZE = 5_000_000
UMAP_RANDOM_STATE = 12345
UMAP_N_NEIGHBORS = 15
UMAP_N_COMPONENTS = 5
UMAP_MIN_DIST = 0.0
UMAP_METRIC = "cosine"
UMAP_TRANSFORM_CHUNK = 50_000

# =============================================================================
# K SELECTION / KMEANS
# =============================================================================
K_VALUES = [50, 75, 90, 100, 110, 120, 125, 150, 175, 200, 225, 250, 300]
FIT_SEEDS = [12345, 22345, 32345, 42345, 52345, 62345, 72345, 82345, 92345, 102345]
KMEANS_BATCH_SIZE = 10_000
KMEANS_N_INIT = 10
KMEANS_MAX_ITER = 300
KMEANS_REASSIGNMENT_RATIO = 0.01
SILHOUETTE_REPS = 10
SILHOUETTE_SAMPLE_N = 100_000
SILHOUETTE_BASE_SEED = 24680
ASSIGN_CHUNK_SIZE = 1_000_000

# Final fit used by 05_finalize_selected_model.py.
# Set these MANUALLY after inspecting 04_select_k_multiseed.py outputs.
# The requested model must already exist in KMEANS_DIR / "k_selection".
FINAL_K = 175
FINAL_FIT_SEED = 102345

# =============================================================================
# FINAL-MODEL DIAGNOSTICS
# =============================================================================
MAD_SCALE = 1.4826
LOW_CONFIDENCE_QUANTILE = 0.85

# =============================================================================
# TOPIC REPRESENTATION
# =============================================================================
VOCAB_SAMPLE_PER_TOPIC = 5_000
MAX_FEATURES = 100_000
NGRAM_RANGE = (1, 2)
TOP_N_TERMS = 25
N_RANDOM_EXAMPLES = 10
REPRESENTATION_FETCH_SIZE = 25_000

# Semantic examples
EXAMPLE_QUANTILES = {"core": 0.10, "typical": 0.50, "periphery": 0.90}
N_EXAMPLES_PER_BAND = 5
