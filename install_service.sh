#!/bin/bash
#
# Pi Thermostat SystemD Service Installer
# Installs the thermostat as a system service that starts on boot
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Pi Thermostat SystemD Service Installer${NC}"
echo -e "${BLUE}================================================${NC}"

# Check if running as root for service installation
if [ "$EUID" -ne 0 ]; then
   print_error "This script must be run with sudo"
   exit 1
fi

INSTALL_DIR="$HOME/pi-thermo"
VENV_DIR="$HOME/pi-thermo-env"
SERVICE_FILE="/etc/systemd/system/thermostat.service"
USER=$(sudo -u#-1 whoami)

print_info "Installing systemd service..."
print_info "Install directory: $INSTALL_DIR"
print_info "Virtual environment: $VENV_DIR"
print_info "Service file: $SERVICE_FILE"
print_info "User: $USER"

# Create systemd service file
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Pi Thermostat Controller
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$USER
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

print_success "Service file created at $SERVICE_FILE"

# Reload systemd
print_info "Reloading systemd daemon..."
systemctl daemon-reload
print_success "Systemd daemon reloaded"

# Enable service
print_info "Enabling thermostat service..."
systemctl enable thermostat
print_success "Service enabled (will start on boot)"

echo ""
echo -e "${BLUE}Service installation complete!${NC}"
echo ""
echo "You can now control the service with:"
echo "  sudo systemctl start thermostat     # Start the service"
echo "  sudo systemctl stop thermostat      # Stop the service"
echo "  sudo systemctl restart thermostat   # Restart the service"
echo "  sudo systemctl status thermostat    # Check status"
echo "  sudo systemctl disable thermostat   # Disable auto-start"
echo ""
echo "View logs:"
echo "  sudo journalctl -u thermostat -f    # Real-time logs"
echo "  tail -f $INSTALL_DIR/service.log    # Service output"
echo ""
