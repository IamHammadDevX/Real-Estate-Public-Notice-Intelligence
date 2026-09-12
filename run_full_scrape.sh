#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="/opt/foreclosure-scraper"
STATE_DIR="$PROJECT_DIR/state"
LOG_DIR="$PROJECT_DIR/logs"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/full_scrape_$RUN_ID.log"

cd "$PROJECT_DIR"
mkdir -p "$STATE_DIR" "$LOG_DIR" "$PROJECT_DIR/exports"
exec 9>"$STATE_DIR/full_scrape.lock"
if ! flock -n 9; then
    echo "Another full scrape process is already running."
    exit 1
fi

ln -sfn "$(basename "$LOG_FILE")" "$LOG_DIR/latest.log"
exec > >(tee -a "$LOG_FILE") 2>&1

started_at="$(date --iso-8601=seconds)"
trap 'status=$?; echo "RUN_END status=$status at=$(date --iso-8601=seconds)"' EXIT

echo "RUN_START id=$RUN_ID at=$started_at"
source "$PROJECT_DIR/venv/bin/activate"
export PYTHONUNBUFFERED=1
export HEADLESS=1
export STRICT_RUN=1
export RESUME_EXISTING=1

if [[ ! -f "$STATE_DIR/ga.complete" ]]; then
    echo "STATE_START GA"
    python -u gapubs.py
    touch "$STATE_DIR/ga.complete"
    echo "STATE_COMPLETE GA"
else
    echo "STATE_SKIP GA already complete"
fi

if [[ ! -f "$STATE_DIR/nc.complete" ]]; then
    echo "STATE_START NC"
    python -u ncpubs.py
    touch "$STATE_DIR/nc.complete"
    echo "STATE_COMPLETE NC"
else
    echo "STATE_SKIP NC already complete"
fi

for state in FL NY NJ MD TX; do
    marker="$(echo "$state" | tr '[:upper:]' '[:lower:]')"
    if [[ ! -f "$STATE_DIR/$marker.complete" ]]; then
        echo "STATE_START $state"
        python -u multistate_scraper.py "$state"
        touch "$STATE_DIR/$marker.complete"
        echo "STATE_COMPLETE $state"
    else
        echo "STATE_SKIP $state already complete"
    fi
done

echo "EXPORT_START"
python -u export_pub_tables.py
echo "EXPORT_COMPLETE"
touch "$STATE_DIR/full_scrape.complete"
echo "FULL_SCRAPE_COMPLETE"
