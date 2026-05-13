#!/usr/bin/env bash
# One-shot setup for Raspberry Pi (Bookworm) or Ubuntu.
#
# Run from the project root:
#   bash scripts/setup_pi.sh

set -euo pipefail

echo "=== Markets Display setup ==="

# System packages PyQt6 needs on a Pi
if command -v apt-get >/dev/null; then
  echo "Installing system packages (sudo required)..."
  sudo apt-get update
  sudo apt-get install -y \
    python3 python3-venv python3-pip \
    libxcb-cursor0 libxkbcommon-x11-0 libegl1 \
    libgl1 libfontconfig1 libdbus-1-3 \
    fonts-dejavu fonts-noto
fi

# Virtualenv
if [ ! -d ".venv" ]; then
  echo "Creating virtualenv at .venv ..."
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt

# .env
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ".env created from .env.example — edit it to add your EODHD_API_KEY"
fi

# Log dir
mkdir -p logs

echo ""
echo "=== Done ==="
echo "Try it (windowed, on the desktop):"
echo "  source .venv/bin/activate"
echo "  python -m src"
echo ""
echo "To run fullscreen on startup, install the systemd unit:"
echo "  sudo cp scripts/markets_display.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  ssudo systemctl enable --now markets_display"
