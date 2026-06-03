#!/bin/bash
# scripts/stop_all.sh - Stop all VMS Profiler services

set -uo pipefail

echo "VMS Profiler - Stopping services"

# Helper: graceful then force kill
stop_process() {
    local pattern="$1"
    local name="$2"
    local pids
    
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -z "$pids" ]; then
        echo "[INFO] $name not running"
        return 0
    fi
    
    echo "[STOP] $name (PID: $pids)..."
    kill $pids 2>/dev/null || true
    sleep 1
    kill -9 $pids 2>/dev/null || true
    echo "[OK] $name stopped"
}

# Stop services
stop_process "collector\.py" "Collector"
stop_process "agent\.py" "Agent"
stop_process "network_monitor\.py" "Network monitor"

# Final verification
sleep 1
remaining=$(pgrep -f "collector\.py|agent\.py|network_monitor\.py" 2>/dev/null || true)
if [ -n "$remaining" ]; then
    echo "[WARN] Some processes still running: $remaining"
    echo "Hint: kill -9 <PID>"
else
    echo "[OK] All services stopped"
fi
