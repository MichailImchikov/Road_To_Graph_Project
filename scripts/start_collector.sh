#!/bin/bash
# scripts/start_collector.sh - Launch central metrics collector

set -euo pipefail

# Configuration
COLLECTOR_HOST="${COLLECTOR_HOST:-0.0.0.0}"
COLLECTOR_PORT="${COLLECTOR_PORT:-8080}"
LOG_FILE="${LOG_FILE:-logs/collector.log}"

echo "VMS Profiler - Collector Launcher"
echo "Binding: $COLLECTOR_HOST:$COLLECTOR_PORT"

# Check dependencies
command -v python3 &>/dev/null || { echo "[FAIL] python3 not found"; exit 1; }
python3 -c "import flask" &>/dev/null || { echo "[FAIL] Flask not installed"; exit 1; }

# Setup
mkdir -p logs output
export COLLECTOR_HOST COLLECTOR_PORT

# Prevent duplicate runs
if pgrep -f "collector\.py" > /dev/null 2>&1; then
    echo "[WARN] Collector already running"
    exit 1
fi

# Launch
echo "Starting collector..."
nohup python3 collector/collector.py > "$LOG_FILE" 2>&1 &
COLLECTOR_PID=$!

# Verify health endpoint
sleep 2
if curl -sf "http://localhost:$COLLECTOR_PORT/health" > /dev/null 2>&1; then
    echo "[OK] Collector running (PID $COLLECTOR_PID)"
    curl -sf "http://localhost:$COLLECTOR_PORT/health" 2>/dev/null | python3 -m json.tool || true
else
    echo "[FAIL] Health check failed. Check $LOG_FILE"
    exit 1
fi

echo "[OK] Ready on port $COLLECTOR_PORT"
