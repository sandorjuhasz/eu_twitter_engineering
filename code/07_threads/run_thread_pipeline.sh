#!/usr/bin/env bash
set -Eeuo pipefail

# =============================================================================
# THREAD RECONSTRUCTION AND DIAGNOSTICS
# =============================================================================

# Run from the directory containing this script
cd "$(dirname "${BASH_SOURCE[0]}")"

# Python environment
PYTHON="/home/ilyesvirag/twitter/venv/bin/python"

# Steps to run (1 = yes, 0 = no)
RUN_RECONSTRUCTION=0
RUN_STATS=1
RUN_NOTEBOOK=1

# Saved outputs
OUTPUT_DIR="/mnt/common-hdd/group-dirs/twitter-2025-project/thread_statistics"
LOG_DIR="$OUTPUT_DIR/logs"
NOTEBOOK_DIR="$OUTPUT_DIR/executed_notebooks"
mkdir -p "$LOG_DIR" "$NOTEBOOK_DIR"
LOG_FILE="$LOG_DIR/thread_pipeline_$(date +%Y%m%d_%H%M%S).log"

# Save console output and errors while retaining the original exit status.
{
    echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Log: $LOG_FILE"

    # =========================================================================
    # 1. RECONSTRUCT CONVERSATIONS
    # =========================================================================

    if [[ "$RUN_RECONSTRUCTION" == 1 ]]; then
        "$PYTHON" -u 01_create_conversation_table.py
    fi

    # =========================================================================
    # 2. CALCULATE THREAD STATISTICS
    # =========================================================================

    if [[ "$RUN_STATS" == 1 ]]; then
        "$PYTHON" -u 02_calculate_thread_stats.py
    fi

    # =========================================================================
    # 3. EXECUTE AND SAVE DESCRIPTIVE NOTEBOOK
    # =========================================================================

    if [[ "$RUN_NOTEBOOK" == 1 ]]; then
        jupyter nbconvert --to notebook --execute \
            --ExecutePreprocessor.kernel_name=twitter-venv \
            --ExecutePreprocessor.timeout=-1 \
            --output-dir "$NOTEBOOK_DIR" \
            --output "03_thread_descriptives_executed.ipynb" \
            03_thread_descriptives.ipynb
    fi

    echo "Finished: $(date '+%Y-%m-%d %H:%M:%S')"
} 2>&1 | tee "$LOG_FILE"
