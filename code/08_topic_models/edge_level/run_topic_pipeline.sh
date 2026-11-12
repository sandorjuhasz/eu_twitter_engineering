
#!/usr/bin/env bash
set -Eeuo pipefail

# =============================================================================
# EDGE-LEVEL TOPIC MODELING PIPELINE
# =============================================================================
#
# Run:
#   bash run_topic_pipeline.sh
#
# The pipeline runs steps in order and stops if any step fails.
# Previously completed stages are reused where supported by their scripts.
#
# IMPORTANT:
#   After step 04, inspect the K-selection results and manually set
#   FINAL_K and FINAL_FIT_SEED in pipeline_config.py.
#   Step 09 modifies the PostgreSQL source table directly.
#
# =============================================================================
# 1. SETTINGS — EDIT HERE
# =============================================================================

PYTHON="/home/ilyesvirag/twitter/venv/bin/python"

START_STEP=1
END_STEP=4

# Set END_STEP=5 after validating K selection and setting FINAL_K/FINAL_FIT_SEED.
# Steps 06–09 are reserved for later validation and taxonomy finalization.

# =============================================================================
# 2. PIPELINE STEPS
# =============================================================================

STEPS=(
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

DESCRIPTIONS=(
    "Generate full-corpus embeddings"
    "Train UMAP on 5M documents"
    "Transform full corpus with UMAP"
    "Select K using multiple seeds"
    "Finalize selected KMeans model"
    "Calculate topic confidence"
    "Generate topic representations"
    "Extract semantic examples"
    "Attach final topics to PostgreSQL"
)

# =============================================================================
# 3. INITIAL CHECKS
# =============================================================================

cd "$(dirname "$0")"

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Python executable not found: $PYTHON"
    exit 1
fi

if (( START_STEP < 1 || END_STEP > 9 || START_STEP > END_STEP )); then
    echo "ERROR: START_STEP and END_STEP must be between 1 and 9."
    exit 1
fi

for (( i=START_STEP-1; i<END_STEP; i++ )); do
    if [[ ! -f "${STEPS[i]}" ]]; then
        echo "ERROR: Missing script: ${STEPS[i]}"
        exit 1
    fi
done

echo "============================================================"
echo " EDGE-LEVEL TOPIC MODELING"
echo "============================================================"
echo " Python:       $PYTHON"
echo " Starting at:  Step $START_STEP"
echo " Ending at:    Step $END_STEP"
echo " Started:      $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

# =============================================================================
# 4. RUN PIPELINE
# =============================================================================

for (( i=START_STEP-1; i<END_STEP; i++ )); do

    STEP=$((i+1))

    echo
    echo "------------------------------------------------------------"
    echo " STEP $(printf '%02d' "$STEP"): ${DESCRIPTIONS[i]}"
    echo " Script: ${STEPS[i]}"
    echo " Started: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "------------------------------------------------------------"

    "$PYTHON" -u "${STEPS[i]}"

    echo " COMPLETED STEP $(printf '%02d' "$STEP")"
    echo " Finished: $(date '+%Y-%m-%d %H:%M:%S')"

done

# =============================================================================
# 5. FINISHED
# =============================================================================

echo
echo "============================================================"
echo " PIPELINE COMPLETED THROUGH STEP $END_STEP"
echo " Finished: $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

if (( END_STEP == 4 )); then
    echo
    echo " NEXT:"
    echo " 1. Review K-selection results."
    echo " 2. Set FINAL_K and FINAL_FIT_SEED in pipeline_config.py."
    echo " 3. Set END_STEP=5 and rerun this script."
fi
