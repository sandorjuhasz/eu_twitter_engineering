#!/usr/bin/env bash

# Stop immediately if any command fails (including commands piped to tee).
set -euo pipefail

# Run this script from the folder containing the Python scripts and notebooks.
cd "$(dirname "$0")"

PYTHON="/home/ilyesvirag/twitter/venv/bin/python"
OUTPUT="/mnt/common-hdd/group-dirs/twitter-2025-project/interaction_network_descriptives"

# Save terminal output to a timestamped log file as well.
mkdir -p "$OUTPUT/logs" "$OUTPUT/executed_notebooks"
LOG="$OUTPUT/logs/pipeline_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

# 1. Build the tweet-level interaction table (recreates the DB table).
echo "1/6 - Creating interaction table"
"$PYTHON" 01_create_interaction_table.py

# 2. Build directed and undirected network tables (recreates both DB tables).
echo "2/6 - Creating networks"
"$PYTHON" 02_create_networks.py

# 3. Calculate directed network descriptives.
echo "3/6 - Directed descriptives"
"$PYTHON" 03_network_descriptives_directed.py

# 4. Calculate undirected network descriptives.
echo "4/6 - Undirected descriptives"
"$PYTHON" 03_network_descriptives_undirected.py

# 5. Execute directed plotting notebook; preserve the original notebook.
echo "5/6 - Directed plots"
"$PYTHON" -m jupyter nbconvert --execute --to notebook \
    --ExecutePreprocessor.timeout=-1 \
    --output 04_network_plots_directed_executed.ipynb \
    --output-dir "$OUTPUT/executed_notebooks" \
    04_network_plots_directed.ipynb

# 6. Execute undirected plotting notebook; preserve the original notebook.
echo "6/6 - Undirected plots"
"$PYTHON" -m jupyter nbconvert --execute --to notebook \
    --ExecutePreprocessor.timeout=-1 \
    --output 04_network_plots_undirected_executed.ipynb \
    --output-dir "$OUTPUT/executed_notebooks" \
    04_network_plots_undirected.ipynb

echo "Pipeline completed successfully. Log: $LOG"
