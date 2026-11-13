
#!/usr/bin/env bash
set -Eeuo pipefail

# =============================================================================
# EDGE-LEVEL CORPUS PREPARATION AND TOPIC MODELING
# =============================================================================

cd "$(dirname "${BASH_SOURCE[0]}")"

# Python environment
PYTHON="/home/ilyesvirag/twitter/venv/bin/python"

# First and last stages to run (inclusive)
# Available: 00a, 00b, 00c, 01, 02, 03, 04, 05, 06, 07, 08, 09
START_STEP="00a"
END_STEP="04"

# Stage 00a DROPS and recreates the London edge corpus.
# Stage 09 writes final topic assignments back to PostgreSQL.
# Set CONFIRM_DB_WRITE=YES explicitly when running stage 09.

STAGES=("00a" "00b" "00c" "01" "02" "03" "04" "05" "06" "07" "08" "09")

SCRIPTS=(
    "00a_create_edge_corpus.py"
    "00b_clean_edge_text.py"
    "00c_edge_corpus_descriptives.ipynb"
    "01_generate_embeddings.py"
    "02_train_umap_5m.py"
    "03_transform_full_corpus_umap.py"
    "04_select_k_multiseed.py"
    "05_finalize_selected_model.py"
    "06_final_confidence.py"
    "07_final_topic_representation.py"
    "08_final_semantic_examples.py"
    "09_attach_edge_topics.py"
)

# Find stage indices without interpreting leading zeros as octal
start_index=-1
end_index=-1

for i in "${!STAGES[@]}"; do
    [[ "${STAGES[i]}" == "$START_STEP" ]] && start_index=$i
    [[ "${STAGES[i]}" == "$END_STEP" ]] && end_index=$i
done

if (( start_index < 0 || end_index < 0 || start_index > end_index )); then
    echo "ERROR: Invalid START_STEP / END_STEP: $START_STEP / $END_STEP" >&2
    exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Python executable not found: $PYTHON" >&2
    exit 1
fi

for (( i=start_index; i<=end_index; i++ )); do
    if [[ ! -f "${SCRIPTS[i]}" ]]; then
        echo "ERROR: Missing script: ${SCRIPTS[i]}" >&2
        exit 1
    fi
done

# Check database write-back before starting
if (( end_index == 11 )) && [[ "${CONFIRM_DB_WRITE:-}" != "YES" ]]; then
    echo "ERROR: Stage 09 writes to PostgreSQL. Set CONFIRM_DB_WRITE=YES." >&2
    exit 1
fi

echo "Running topic pipeline: $START_STEP through $END_STEP"

# =============================================================================
# RUN PIPELINE
# =============================================================================

for (( i=start_index; i<=end_index; i++ )); do

    echo
    echo "============================================================"
    echo "Stage ${STAGES[i]}: ${SCRIPTS[i]}"
    echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"

    if [[ "${STAGES[i]}" == "00c" ]]; then

        # Execute notebook and save its outputs
        NOTEBOOK_DIR="/mnt/common-hdd/group-dirs/twitter-2025-project/topic_models/edge_level/edge/corpus_descriptives/executed_notebooks"

        mkdir -p "$NOTEBOOK_DIR"

        "$PYTHON" -m jupyter nbconvert \
            --to notebook --execute \
            --ExecutePreprocessor.timeout=-1 \
            --output-dir "$NOTEBOOK_DIR" \
            --output "00c_edge_corpus_descriptives_executed.ipynb" \
            "${SCRIPTS[i]}"

    else
        "$PYTHON" -u "${SCRIPTS[i]}"
    fi

    echo "Completed stage ${STAGES[i]} at $(date '+%Y-%m-%d %H:%M:%S')"
done

echo
echo "Pipeline finished through stage $END_STEP."

if [[ "$END_STEP" == "04" ]]; then
    echo "Review K-selection results, then set FINAL_K and FINAL_FIT_SEED in pipeline_config.py."
fi
