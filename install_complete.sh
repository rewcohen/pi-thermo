#!/bin/bash
#
# Pi Thermostat - Complete Installation Script
# Run this on the Pi to set up everything including boot autostart
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Pi Thermostat - Complete Installation${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""

# Check if running as root for system-wide setup
if [ "$EUID" -ne 0 ]; then
   echo -e "${YELLOW}Note: Some steps require sudo. You will be prompted for password.${NC}"
fi

# Get the user who will run the service
# When run with sudo, SUDO_USER is set. Otherwise use current user
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "#-1" ]; then
    THERMOSTAT_USER="$SUDO_USER"
else
    # Fallback: get the actual user
    THERMOSTAT_USER=$(id -u -n 2>/dev/null || echo "acohen")
    # If we're root and can't determine user, use a sensible default
    if [ "$THERMOSTAT_USER" = "root" ]; then
        THERMOSTAT_USER="acohen"
    fi
fi

INSTALL_DIR="/home/$THERMOSTAT_USER/pi-thermo"
VENV_DIR="/home/$THERMOSTAT_USER/pi-thermo-env"
SERVICE_FILE="/etc/systemd/system/thermostat.service"

echo -e "${GREEN}[1/6] Updating system packages...${NC}"
sudo apt-get update > /dev/null 2>&1
sudo apt-get upgrade -y > /dev/null 2>&1
echo -e "${GREEN}✓ System updated${NC}"

echo -e "${GREEN}[2/6] Installing system dependencies...${NC}"
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    python3-smbus \
    python3-rpi.gpio \
    i2c-tools \
    build-essential \
    libopenjp2-7 \
    libtiff5 \
    libwebp6 > /dev/null 2>&1
echo -e "${GREEN}✓ System dependencies installed${NC}"

echo -e "${GREEN}[3/6] Creating Python virtual environment...${NC}"
if [ -d "$VENV_DIR" ]; then
    rm -rf "$VENV_DIR"
fi
python3 -m venv "$VENV_DIR" > /dev/null 2>&1
echo -e "${GREEN}✓ Virtual environment created${NC}"

echo -e "${GREEN}[4/6] Installing Python packages...${NC}"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip > /dev/null 2>&1
pip install -r "$INSTALL_DIR/requirements.txt" > /dev/null 2>&1
deactivate
echo -e "${GREEN}✓ Python packages installed${NC}"

echo -e "${GREEN}[5/6] Fixing line endings...${NC}"
find "$INSTALL_DIR" -name "*.py" -o -name "*.sh" | xargs sed -i 's/\r$//'
chmod +x "$INSTALL_DIR/thermostat.py"
chmod +x "$INSTALL_DIR/execute.sh"
chmod +x "$INSTALL_DIR/activate.sh"
echo -e "${GREEN}✓ Line endings fixed${NC}"

echo -e "${GREEN}[6/6] Setting up systemd service for autostart...${NC}"
sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Pi Thermostat Controller
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$THERMOSTAT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python3 $INSTALL_DIR/thermostat.py
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/service.log
StandardError=append:$INSTALL_DIR/service.log
Environment="PATH=$VENV_DIR/bin"

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable thermostat
echo -e "${GREEN}✓ SystemD service configured${NC}"

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Enable I2C interface (if not already done):"
echo "   sudo raspi-config"
echo "   Select: Interface Options → I2C → Yes"
echo "   Then reboot"
echo ""
echo "2. Start the thermostat service:"
echo "   sudo systemctl start thermostat"
echo ""
echo "3. Check status:"
echo "   sudo systemctl status thermostat"
echo ""
echo "4. View real-time logs:"
echo "   sudo journalctl -u thermostat -f"
echo ""
echo "5. Access web interface:"
echo "   http://$(hostname -I | awk '{print $1}'):5002"
echo ""
echo -e "${YELLOW}Service will automatically start on boot!${NC}"
echo ""
