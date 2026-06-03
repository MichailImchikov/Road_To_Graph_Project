#!/bin/bash
# scripts/install.sh - Install VMS Profiler dependencies

set -euo pipefail

echo "VMS Profiler - Dependency Installer"

# Detect distro
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "[WARN] This script is designed for Linux"
    echo "Hint: Use WSL or a VM on Windows/macOS"
    exit 1
fi

DISTRO=$(grep "^ID=" /etc/os-release | cut -d= -f2 | tr -d '"')
echo "[OK] Detected: $DISTRO"

# Package manager helper
install_packages() {
    case $DISTRO in
        ubuntu|debian|linuxmint)
            sudo apt update -qq
            sudo apt install -y "$@"
            ;;
        centos|rhel|fedora)
            sudo dnf update -y -q || sudo yum update -y -q
            sudo dnf install -y "$@" || sudo yum install -y "$@"
            ;;
        *)
            echo "[WARN] Unknown distro, trying apt..."
            sudo apt update -qq && sudo apt install -y "$@" || true
            ;;
    esac
}

# System dependencies
echo "Installing system packages..."
install_packages \
    likwid net-tools iproute2 python3 python3-pip python3-venv curl wget git

# LIKWID setup
echo "Configuring LIKWID..."
sudo modprobe msr 2>/dev/null || true

# Persist msr module across reboots
if [ ! -f /etc/modules-load.d/msr.conf ] || ! grep -q "^msr$" /etc/modules-load.d/msr.conf 2>/dev/null; then
    echo "msr" | sudo tee -a /etc/modules-load.d/msr.conf > /dev/null
    echo "[OK] msr module added to auto-load"
fi

# Verify LIKWID
if likwid-topology &>/dev/null; then
    echo "[OK] LIKWID working"
else
    echo "[WARN] LIKWID check failed - verify installation"
fi

# Python dependencies
echo "Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "[OK] Virtual environment created"
fi

source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "[OK] Python dependencies installed"

# Create directories
mkdir -p output logs
touch output/.gitkeep logs/.gitkeep
echo "[OK] Directories ready"

# Final verification
echo ""
echo "Dependency check:"
for cmd in python3 pip3 likwid-topology curl; do
    if command -v "$cmd" &>/dev/null; then
        echo "[OK] $cmd"
    else
        echo "[FAIL] $cmd not found"
    fi
done

echo ""
echo "[OK] Installation complete"
echo "Next: ./scripts/start_collector.sh (central node) or ./scripts/start_agent.sh (worker)"
