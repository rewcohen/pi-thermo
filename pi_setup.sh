#!/bin/bash
# Quick setup for Pi Thermostat - Run this on the Pi

set -e

echo "================================================"
echo "Pi Thermostat Quick Setup"
echo "================================================"

cd ~/pi-thermo

# Create virtual environment
echo "[1/5] Creating virtual environment..."
python3 -m venv ~/pi-thermo-env

# Activate and upgrade pip
echo "[2/5] Upgrading pip..."
source ~/pi-thermo-env/bin/activate
pip install --upgrade pip --quiet

# Install packages from requirements
echo "[3/5] Installing Python packages..."
pip install -r requirements.txt --quiet

# Fix line endings
echo "[4/5] Fixing line endings..."
sed -i 's/\r$//' ~/pi-thermo/*.py ~/pi-thermo/*.sh 2>/dev/null || true

# Make scripts executable
echo "[5/5] Making scripts executable..."
chmod +x ~/pi-thermo/thermostat.py
chmod +x ~/pi-thermo/execute.sh
chmod +x ~/pi-thermo/activate.sh

echo ""
echo "================================================"
echo "Setup Complete!"
echo "================================================"
echo ""
echo "Test the installation:"
echo "  source ~/pi-thermo/activate.sh"
echo "  python3 -c 'import luma.oled; print(\"[OK] All packages installed\")'\"
echo ""
echo "Run the thermostat:"
echo "  source ~/pi-thermo/activate.sh"
echo "  python3 ~/pi-thermo/thermostat.py"
echo ""
echo "Access web interface:"
echo "  http://<your-pi-ip>:5000"
echo ""
