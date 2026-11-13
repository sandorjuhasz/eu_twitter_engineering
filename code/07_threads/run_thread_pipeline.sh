
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
RUN_RECONSTRUCTION=1
RUN_STATS=1

# =============================================================================
# 1. RECONSTRUCT CONVERSATIONS
# =============================================================================

if [[ "$RUN_RECONSTRUCTION" == 1 ]]; then
    "$PYTHON" 01_create_conversation_table.py
fi

# =============================================================================
# 2. CALCULATE THREAD STATISTICS
# =============================================================================

if [[ "$RUN_STATS" == 1 ]]; then
    "$PYTHON" 02_calculate_thread_stats.py
fi
