#!/bin/bash
# scripts/generate_report.sh - Generate final profiling report

set -euo pipefail

COLLECTOR_HOST="${COLLECTOR_HOST:-localhost}"
COLLECTOR_PORT="${COLLECTOR_PORT:-8080}"
OUTPUT_DIR="${OUTPUT_DIR:-./output}"

echo "VMS Profiler - Report Generator"
echo "Target: $COLLECTOR_HOST:$COLLECTOR_PORT"

# Check collector health
if ! curl -sf "http://$COLLECTOR_HOST:$COLLECTOR_PORT/health" > /dev/null 2>&1; then
    echo "[FAIL] Collector not reachable"
    exit 1
fi
echo "[OK] Collector online"

# Show quick stats preview
echo "Fetching metrics summary..."
curl -sf "http://$COLLECTOR_HOST:$COLLECTOR_PORT/stats" 2>/dev/null | python3 -m json.tool || true

# Generate full report
echo "Running aggregator..."
mkdir -p "$OUTPUT_DIR"

python3 aggregator/aggregator.py \
    --collector-host "$COLLECTOR_HOST" \
    --collector-port "$COLLECTOR_PORT" \
    --output-dir "$OUTPUT_DIR"

echo "[OK] Done. Files in $OUTPUT_DIR:"
find "$OUTPUT_DIR" -maxdepth 1 -name "report_*" -type f -exec ls -lh {} \;
