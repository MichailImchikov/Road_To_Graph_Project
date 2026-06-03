#!/bin/bash
# scripts/start_agent.sh - Launch profiling agent and network monitor

set -euo pipefail

# Configuration
NODE_ID="${NODE_ID:-node-$(hostname)}"
COLLECTOR_HOST="${COLLECTOR_HOST:-localhost}"
COLLECTOR_PORT="${COLLECTOR_PORT:-8080}"
LOG_FILE_AGENT="${LOG_FILE_AGENT:-logs/agent.log}"
LOG_FILE_NETWORK="${LOG_FILE_NETWORK:-logs/network_monitor.log}"

echo "VMS Profiler - Agent Launcher"
echo "Node: $NODE_ID | Collector: $COLLECTOR_HOST:$COLLECTOR_PORT"

# Check dependencies
command -v python3 &>/dev/null || { echo "[FAIL] python3 not found"; exit 1; }
command -v likwid-topology &>/dev/null || echo "[WARN] LIKWID not found"
command -v tshark &>/dev/null || echo "[WARN] tshark not found"

# Load MSR module if needed
lsmod | grep -q msr || sudo modprobe msr 2>/dev/null || true

# Setup dirs and environment
mkdir -p logs output
export NODE_ID COLLECTOR_HOST COLLECTOR_PORT

# Prevent duplicate runs
if pgrep -f "agent\.py" > /dev/null 2>&1; then
    echo "[WARN] Agent already running"
    exit 1
fi

# Launch processes
echo "Starting agent..."
nohup python3 agent/agent.py > "$LOG_FILE_AGENT" 2>&1 &
AGENT_PID=$!

echo "Starting network monitor..."
nohup python3 agent/network_monitor.py > "$LOG_FILE_NETWORK" 2>&1 &
NETWORK_PID=$!

# Verify launch
sleep 2
if kill -0 $AGENT_PID 2>/dev/null; then
    echo "[OK] Agent running (PID $AGENT_PID)"
else
    echo "[FAIL] Agent failed. Check $LOG_FILE_AGENT"
    exit 1
fi

if kill -0 $NETWORK_PID 2>/dev/null; then
    echo "[OK] Network monitor running (PID $NETWORK_PID)"
else
    echo "[WARN] Network monitor failed. Check $LOG_FILE_NETWORK"
fi

echo "[OK] Ready. Logs: $LOG_FILE_AGENT, $LOG_FILE_NETWORK"
