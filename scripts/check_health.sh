#!/bin/bash
# Quick health check for VMS Profiler - run anytime to verify setup

set -uo pipefail  # -e disabled: we handle failures manually

COLLECTOR_HOST="${COLLECTOR_HOST:-localhost}"
COLLECTOR_PORT="${COLLECTOR_PORT:-8080}"

echo "VMS Profiler health check @ $(date -Iseconds)"
echo "Target: $COLLECTOR_HOST:$COLLECTOR_PORT"
echo ""

# --- Collector ---
if curl -sf "http://$COLLECTOR_HOST:$COLLECTOR_PORT/health" >/dev/null 2>&1; then
    echo "[OK] collector"
    # Quick peek at response if python3 available
    curl -sf "http://$COLLECTOR_HOST:$COLLECTOR_PORT/health" 2>/dev/null | \
        python3 -m json.tool -c 2>/dev/null || true
else
    echo "[FAIL] collector not reachable"
fi

# --- Processes ---
# pgrep -f is blunt but catches everything; might have false positives
for pattern in "collector.py" "agent.agent" "network_monitor"; do
    if pgrep -f "$pattern" >/dev/null 2>&1; then
        echo "[OK] $pattern"
    else
        # Don't fail the whole check for one missing component
        echo "[WARN] $pattern not running"
    fi
done

# --- Dependencies ---
# These are nice-to-have; agent can run with degraded functionality
for cmd in python3 likwid-topology tshark; do
    command -v "$cmd" >/dev/null 2>&1 && echo "[OK] $cmd" || echo "[INFO] $cmd missing"
done

# --- MSR module ---
# Required for LIKWID hardware counters; soft dependency for basic agent
if lsmod | grep -q "^msr "; then
    echo "[OK] msr"
else
    echo "[WARN] msr not loaded - LIKWID counters unavailable"
    echo "  Hint: sudo modprobe msr"
fi

echo ""
echo "Done."
