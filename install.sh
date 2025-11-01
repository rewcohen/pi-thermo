#!/bin/bash
#
# Pi Thermostat Installer
# Sets up all dependencies and configuration for the thermostat system
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="$HOME/pi-thermo"
VENV_DIR="$HOME/pi-thermo-env"
LOG_FILE="$INSTALL_DIR/install.log"

# Functions
print_header() {
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================================${NC}"
}

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

# Start installation
print_header "Pi Thermostat System Installer"

echo "Installation log: $LOG_FILE"
echo "Start time: $(date)" > "$LOG_FILE"

# Check if running on Raspberry Pi
print_info "Checking system compatibility..."
if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    print_warning "Not running on a Raspberry Pi. Some hardware features may not work."
else
    print_info "Detected Raspberry Pi: $(cat /proc/device-tree/model)"
fi

# Update system packages
print_header "Updating System Packages"
print_info "Running apt-get update..."
sudo apt-get update >> "$LOG_FILE" 2>&1
print_success "System packages updated"

# Install system dependencies
print_header "Installing System Dependencies"
print_info "Installing required packages..."

PACKAGES=(
    "python3-pip"
    "python3-dev"
    "python3-smbus"
    "python3-rpi.gpio"
    "python3-venv"
    "i2c-tools"
    "build-essential"
    "libopenjp2-7"
    "libtiff5"
    "libjasper1"
    "libharfbuzz0b"
    "libwebp6"
    "libtk8.6"
    "libtcl8.6"
    "git"
)

for package in "${PACKAGES[@]}"; do
    print_info "Installing $package..."
    sudo apt-get install -y "$package" >> "$LOG_FILE" 2>&1
done

print_success "System dependencies installed"

# Create virtual environment
print_header "Creating Python Virtual Environment"
print_info "Creating venv at $VENV_DIR..."
python3 -m venv "$VENV_DIR" >> "$LOG_FILE" 2>&1
print_success "Virtual environment created"

# Activate virtual environment
print_info "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Upgrade pip
print_header "Upgrading Python Package Manager"
print_info "Upgrading pip..."
pip install --upgrade pip >> "$LOG_FILE" 2>&1
print_success "pip upgraded"

# Install Python packages
print_header "Installing Python Packages"

PYTHON_PACKAGES=(
    "smbus2"
    "luma.oled"
    "luma.core"
    "pillow"
    "flask"
    "RPi.GPIO"
)

for package in "${PYTHON_PACKAGES[@]}"; do
    print_info "Installing $package..."
    pip install "$package" >> "$LOG_FILE" 2>&1 || {
        print_error "Failed to install $package"
        echo "Failed to install $package" >> "$LOG_FILE"
    }
done

print_success "Python packages installed"

# Create necessary directories
print_header "Setting Up Directories and Files"
print_info "Creating templates directory..."
mkdir -p "$INSTALL_DIR/templates"
print_success "Templates directory created"

# Create log directory
print_info "Setting up log directory..."
touch "$INSTALL_DIR/thermo.log"
touch "$INSTALL_DIR/events.log"
print_success "Log files created"

# Make scripts executable
print_info "Making scripts executable..."
chmod +x "$INSTALL_DIR/thermostat.py"
chmod +x "$INSTALL_DIR/execute.sh"
print_success "Scripts are executable"

# Create activation script
print_header "Creating Activation Helper"
cat > "$INSTALL_DIR/activate.sh" << 'EOF'
#!/bin/bash
source $HOME/pi-thermo-env/bin/activate
EOF
chmod +x "$INSTALL_DIR/activate.sh"
print_success "Activation script created"

# Create systemd service file (optional)
print_header "Creating SystemD Service (Optional)"
print_info "You can optionally install this as a systemd service."
print_info "To install as service, run:"
echo -e "${YELLOW}sudo $INSTALL_DIR/install_service.sh${NC}"

# Verify installation
print_header "Verifying Installation"
print_info "Testing Python imports..."

python3 << 'PYEOF'
import sys
try:
    import smbus2
    print("[✓] smbus2")
except:
    print("[✗] smbus2")
    sys.exit(1)

try:
    import RPi.GPIO as GPIO
    print("[✓] RPi.GPIO")
except:
    print("[✗] RPi.GPIO")
    sys.exit(1)

try:
    from luma.oled.device import ssd1306
    print("[✓] luma.oled")
except:
    print("[✗] luma.oled")
    sys.exit(1)

try:
    from flask import Flask
    print("[✓] flask")
except:
    print("[✗] flask")
    sys.exit(1)

print("\nAll required modules installed successfully!")
PYEOF

if [ $? -eq 0 ]; then
    print_success "All imports verified"
else
    print_error "Some imports failed"
    exit 1
fi

# Print next steps
print_header "Installation Complete!"
print_info "Installation log saved to: $LOG_FILE"

cat << 'EOF'

Next Steps:
-----------

1. Enable I2C interfaces (if not already enabled):
   sudo raspi-config
   Select: Interfacing Options → I2C → Yes

2. Verify I2C devices:
   i2cdetect -y 1  # OLED display should be at 0x3c
   i2cdetect -y 3  # AHT10 sensor should be at 0x38

3. Run the thermostat:
   python3 ~/pi-thermo/thermostat.py

   Or with virtual environment:
   source ~/pi-thermo/activate.sh
   python3 ~/pi-thermo/thermostat.py

4. Access the web interface:
   http://<pi-ip>:5000

5. View logs:
   tail -f ~/pi-thermo/thermo.log
   tail -f ~/pi-thermo/events.log

Optional - Install as systemd service:
   sudo cp ~/pi-thermo/thermostat.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable thermostat
   sudo systemctl start thermostat

EOF

echo "" >> "$LOG_FILE"
echo "Installation completed at: $(date)" >> "$LOG_FILE"

print_success "Installation finished successfully!"
