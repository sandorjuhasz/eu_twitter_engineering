#!/usr/bin/env bash
set -euo pipefail

# Run the London conversation and edge-corpus pipeline in order.
# Run this file from anywhere; the scripts are resolved relative to it.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="/home/ilyesvirag/twitter/venv/bin/python"
OUTPUT_DIR="/mnt/common-hdd/group-dirs/twitter-2025-project/thread_statistics"

mkdir -p "$OUTPUT_DIR/logs" "$OUTPUT_DIR/executed_notebooks"
LOG_FILE="$OUTPUT_DIR/logs/thread_pipeline_$(date +%Y%m%d_%H%M%S).log"
cd "$SCRIPT_DIR"

# Keep a copy of everything printed in the terminal.
exec > >(tee -a "$LOG_FILE") 2>&1

echo "Starting London thread pipeline: $(date)"
echo "Log: $LOG_FILE"

echo "[1/5] Create conversation table"
"$PYTHON" 01_create_conversation_table.py

echo "[2/5] Calculate thread statistics"
"$PYTHON" 02_calculate_thread_stats.py

echo "[3/5] Create edge-level thread corpus"
"$PYTHON" 03_edge_level_corpus.py

echo "[4/5] Clean edge-level thread text"
"$PYTHON" 04_clean_edge_thread_text.py

echo "[5/5] Run edge-corpus descriptives notebook"
"$PYTHON" -m jupyter nbconvert --to notebook --execute \
  05_edge_thread_corpus_descriptives.ipynb \
  --output-dir "$OUTPUT_DIR/executed_notebooks" \
  --output 05_edge_thread_corpus_descriptives_executed.ipynb

echo "Finished: $(date)"
