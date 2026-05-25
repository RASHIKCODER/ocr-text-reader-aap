#!/bin/bash
# ============================================================
#  OCR Vision System — Auto Start Script (Linux/Raspberry Pi)
#  
#  Setup karne ke liye:
#  1. chmod +x start.sh
#  2. Crontab mein add karo: @reboot /path/to/start.sh
# ============================================================

cd "$(dirname "$0")"

echo "================================"
echo "  OCR Vision System Starting..."
echo "================================"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 not found"
    exit 1
fi

# Install dependencies if needed
if [ ! -f ".deps_installed" ]; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
    touch .deps_installed
fi

# Create required folders
mkdir -p data screenshots

# Start system
echo "Starting OCR Vision..."
python3 main.py

