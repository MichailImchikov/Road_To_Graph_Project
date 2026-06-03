#!/bin/bash
# scripts/setup_likwid.sh - One-time LIKWID permission setup

set -euo pipefail

echo "Setting up LIKWID access..."

# Configure sudoers rule (idempotent)
RULE="$USER ALL=(ALL) NOPASSWD: /usr/bin/likwid-perfctr, /usr/sbin/modprobe"
if ! grep -q "likwid-perfctr" /etc/sudoers.d/likwid 2>/dev/null; then
    echo "$RULE" | sudo tee /etc/sudoers.d/likwid > /dev/null
    sudo chmod 440 /etc/sudoers.d/likwid
    echo "[OK] sudoers rule created"
else
    echo "[OK] sudoers rule already exists"
fi

# Load MSR module if needed
sudo modprobe msr 2>/dev/null || true

# Verify access works non-interactively
echo "Testing LIKWID access..."
if ! sudo -n /usr/bin/likwid-perfctr -C 0 -g MEM sleep 1 > /dev/null 2>&1; then
    echo "[FAIL] Cannot access MSR registers"
    echo "Hint: Check Secure Boot status or run:"
    echo "  sudo modprobe msr && sudo -n /usr/bin/likwid-perfctr -C 0 -g MEM sleep 1"
    exit 1
fi

echo "[OK] LIKWID ready. Run ./run_experiment.sh to start."
