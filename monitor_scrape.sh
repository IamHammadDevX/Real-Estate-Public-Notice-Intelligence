#!/usr/bin/env bash

PROJECT_DIR="/opt/foreclosure-scraper"
LOG_FILE="$PROJECT_DIR/logs/latest.log"

echo "=== SERVICE ==="
systemctl is-active foreclosure-scraper.service
systemctl show foreclosure-scraper.service \
    --property=ActiveState,SubState,NRestarts,ExecMainStartTimestamp \
    --no-pager

echo
echo "=== COMPLETION MARKERS ==="
for state in ga nc fl ny nj md tx full_scrape; do
    if [[ -f "$PROJECT_DIR/state/$state.complete" ]]; then
        echo "$state: complete"
    else
        echo "$state: pending/running"
    fi
done

echo
echo "=== LATEST PROGRESS / ETA ==="
if [[ -f "$LOG_FILE" ]]; then
    grep "PROGRESS" "$LOG_FILE" | tail -n 6
    echo
    echo "=== LAST 20 LOG LINES ==="
    tail -n 20 "$LOG_FILE"
else
    echo "No scrape log found."
fi

echo
echo "=== DATABASE COUNTS ==="
cd "$PROJECT_DIR" || exit 1
source "$PROJECT_DIR/venv/bin/activate"
python -u scrape_status.py
