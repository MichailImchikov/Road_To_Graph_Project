#!/bin/bash
# run_experiment.sh - Full experiment cycle
# Usage: ./run_experiment.sh [NUM_NODES] [DURATION_SEC]

set -uo pipefail

# === Config ===
NUM_NODES=${1:-20}
DURATION_SEC=${2:-120}
PROJECT_DIR="$HOME/Road_To_Graph_Project"
LOG_DIR="$PROJECT_DIR/logs"
OUTPUT_DIR="$PROJECT_DIR/output"

# === Helpers ===
log() { echo "[$(date +%H:%M:%S)] $*"; }

cleanup() {
    log "Stopping processes..."
    pkill -9 -f "light_node_.*\.py" 2>/dev/null || true
    pkill -9 -f "create_light_ros_graph.py" 2>/dev/null || true
    pkill -9 -f "agent\.agent" 2>/dev/null || true
    pkill -9 -f "collector\.py" 2>/dev/null || true
    log "Cleanup done"
}
trap cleanup EXIT INT TERM

mkdir -p "$LOG_DIR" "$OUTPUT_DIR"

# === 0. Environment Setup (FIXED: Force consistent DDS discovery) ===
set +u
if [ -f "/opt/ros/jazzy/setup.bash" ]; then
    source /opt/ros/jazzy/setup.bash
elif [ -f "/opt/ros/humble/setup.bash" ]; then
    source /opt/ros/humble/setup.bash
fi
set -u

# 🛡️ CRITICAL: Force script and nodes to use the same ROS domain
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}
export ROS_LOCALHOST_ONLY=0

# === 1. Cleanup ===
log "Cleaning up..."
pkill -9 -f "light_node|agent|collector|create_light" 2>/dev/null || true
sleep 2
find "$PROJECT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
log "Ready"

# === 2. Collector ===
log "Starting collector..."
cd "$PROJECT_DIR"
python3 collector/collector.py > "$LOG_DIR/collector.log" 2>&1 &
COLLECTOR_PID=$!
sleep 3

if ! kill -0 $COLLECTOR_PID 2>/dev/null; then
    log "[FAIL] Collector died (PID $COLLECTOR_PID)"
    tail -5 "$LOG_DIR/collector.log"
    exit 1
fi
log "[OK] Collector running (PID $COLLECTOR_PID)"

# === 3. Graph ===
log "Generating graph ($NUM_NODES nodes)..."
GRAPH_SCRIPT="$PROJECT_DIR/benchmark/create_light_ros_graph.py"
sed -i "s/NUM_NODES = .*/NUM_NODES = $NUM_NODES/" "$GRAPH_SCRIPT"

if [ "$NUM_NODES" -gt 30 ]; then
    sed -i "s/TARGET_BW_MBPS = .*/TARGET_BW_MBPS = 5/" "$GRAPH_SCRIPT"
    sed -i "s/BASE_MEM_MB = .*/BASE_MEM_MB = 5/" "$GRAPH_SCRIPT"
    log "[WARN] Reduced load for >30 nodes"
fi

cd "$PROJECT_DIR/benchmark"
python3 create_light_ros_graph.py > "$LOG_DIR/graph.log" 2>&1 &
GRAPH_PID=$!
sleep 12

# Ensure daemon is alive and discovery is active
ros2 daemon start >/dev/null 2>&1 || true
sleep 2

# 🔍 Robust node counting (avoids pipefail issues with grep -c)
NODE_OUTPUT=$(ros2 node list 2>&1)
ROS_COUNT=$(echo "$NODE_OUTPUT" | grep -c "light_worker" || true)
ROS_COUNT=${ROS_COUNT:-0}
log "[OK] Graph launched (~$ROS_COUNT nodes visible)"

if [ "$ROS_COUNT" -eq 0 ]; then
    log "[FAIL] ros2 node list saw 0 nodes."
    log "Debug CLI output: $(echo "$NODE_OUTPUT" | head -3)"
    exit 1
fi

# === 4. LIKWID access check ===
log "Checking LIKWID access..."
if ! sudo -n /usr/bin/likwid-perfctr -C 0 -g MEM sleep 1 >/dev/null 2>&1; then
    log "[FAIL] LIKWID not accessible via sudo"
    log "Hint: Run scripts/setup_likwid.sh"
    exit 1
fi
log "[OK] LIKWID ready"

# === 5. Agent ===
log "Starting agent..."
cd "$PROJECT_DIR"
export TARGET_PROCESS_PATTERN='light_node'
export NODE_NAME_PATTERN='light_node_(\d+)\.py'
export ROS_NAME_TEMPLATE='light_node_{}'
# Agent inherits ROS_DOMAIN_ID=0 from step 0
export ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp COLLECTOR_HOST=127.0.0.1

python3 -m agent.agent > "$LOG_DIR/agent.log" 2>&1 &
AGENT_PID=$!
sleep 10

if ! kill -0 $AGENT_PID 2>/dev/null; then
    log "[FAIL] Agent died (PID $AGENT_PID)"
    tail -10 "$LOG_DIR/agent.log"
    exit 1
fi
log "[OK] Agent running (PID $AGENT_PID)"

# === 6. Data collection ===
log "Collecting data for ${DURATION_SEC}s..."
STEP=$((DURATION_SEC / 10)); [ "$STEP" -lt 1 ] && STEP=1
for i in $(seq 1 10); do
    sleep "$STEP"
    echo -n "."
done
echo ""
log "[OK] Collection complete"

# === 7. Stop graph and agent ===
log "Stopping graph and agent..."
pkill -9 -f "light_node_.*\.py" 2>/dev/null || true
pkill -9 -f "create_light_ros_graph.py" 2>/dev/null || true
pkill -9 -f "agent\.agent" 2>/dev/null || true
sleep 2
log "[OK] Stopped"

# === 8. Aggregation ===
log "Running aggregator..."
cd "$PROJECT_DIR"

if python3 -m aggregator.aggregator >> "$LOG_DIR/aggregator.log" 2>&1; then
    log "[OK] Aggregator succeeded"
    LATEST_JSON=$(ls -t "$OUTPUT_DIR"/report_*.json 2>/dev/null | head -1)
    FINAL_REPORT="${LATEST_JSON:-$OUTPUT_DIR/report_fallback.json}"
else
    log "[WARN] Aggregator failed, trying fallback..."
    curl -sf "http://127.0.0.1:8080/report" > "$OUTPUT_DIR/report_fallback.json" 2>/dev/null || true
    FINAL_REPORT="$OUTPUT_DIR/report_fallback.json"
fi

# === 9. Summary ===
if [ -f "$FINAL_REPORT" ] && [ -s "$FINAL_REPORT" ]; then
    echo ""
    log "=== Experiment Summary ==="
    python3 -c "
import json, sys
try:
    with open('$FINAL_REPORT') as f: d = json.load(f)
    nodes = d.get('nodes', [])
    if not nodes and 'nodes' in d: nodes = [d]
    n = nodes[0] if nodes else {}
    tasks = n.get('tasks', [])
    print(f'Tasks: {len(tasks)}')
    print(f\"CPU: {n.get('total_cpu_load', 0):.1f}% | RAM: {n.get('total_memory_usage_mb', 0):.0f} MB\")
    wt = [t for t in tasks if t.get('network_traffic_mbps', 0) > 0]
    print(f'Nodes with traffic: {len(wt)}/{len(tasks)}')
except Exception as e: print(f'Parse error: {e}')
"
    log "[OK] Report: $FINAL_REPORT"
    log "Logs: $LOG_DIR/"
else
    log "[FAIL] No report generated"
    exit 1
fi

exit 0
