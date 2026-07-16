#!/bin/bash
# Run from repo root:
#   nohup bash notes/run_v2_build.sh &
#   tail -f notes/run_v2_build_<timestamp>.log

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DB_DIR="$REPO_ROOT/code/03_database_setup"
LOG_FILE="$SCRIPT_DIR/run_v2_build_$(date +%Y%m%d_%H%M%S).log"

# Update this to your Python path if needed
PYTHON="python"

exec > >(tee -a "$LOG_FILE") 2>&1

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

run_step() {
    local label="$1"
    local script="$2"
    log "=== START: $label ($script) ==="
    $PYTHON "$script"
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log "=== ERROR: $script exited with code $exit_code — stopping ==="
        exit $exit_code
    fi
    log "=== DONE: $label ==="
    echo ""
}

log "twitter_cities_v2 build started"
log "Log: $LOG_FILE"
log "Working dir: $DB_DIR"
echo ""

cd "$DB_DIR" || { log "ERROR: cannot cd to $DB_DIR"; exit 1; }

# run_step "00 — create database"        "00_database.py"
# run_step "01 — tweet table (~6h)"      "01_tweet_table.py"
# run_step "03 — interaction networks"   "03_interaction_networks.py"
# run_step "04 — place table"            "04_place_table.py"
# run_step "05 — text extras"            "05_text_extras.py"
run_step "06 — user table"             "06_user_table.py"

log "All steps completed successfully"
