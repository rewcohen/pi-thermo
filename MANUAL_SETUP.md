# Pi Thermostat - Manual Setup for your Pi

Since automated install has issues with sudo/SSH, follow these manual steps **on your Pi directly**.

## Step 1: SSH into your Pi

From your Windows machine:
```powershell
ssh acohen@192.168.69.22
```
Enter password: `$Crag3tar`

## Step 2: Update System (requires password)

```bash
sudo apt-get update
sudo apt-get upgrade -y
```

## Step 3: Install System Packages (requires password)

```bash
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    python3-smbus \
    python3-rpi.gpio \
    i2c-tools \
    build-essential \
    libopenjp2-7 \
    libtiff5 \
    libwebp6
```

## Step 4: Enable I2C Interface (requires password)

```bash
sudo raspi-config
```

Then:
1. Navigate to: **Interface Options** → **I2C** → **Yes**
2. Exit and **Reboot** when prompted

After reboot, SSH back in and continue...

## Step 5: Verify I2C Hardware

Check both I2C buses:

```bash
i2cdetect -y 1    # Should show 0x3c (OLED)
i2cdetect -y 3    # Should show 0x38 (Temperature sensor)
```

## Step 6: Create Virtual Environment

```bash
cd ~/pi-thermo
python3 -m venv ~/pi-thermo-env
source ~/pi-thermo-env/bin/activate
```

## Step 7: Upgrade Pip

```bash
pip install --upgrade pip
```

## Step 8: Install Python Packages

```bash
pip install -r requirements.txt
```

Or manually:
```bash
pip install smbus2 luma.oled luma.core pillow flask RPi.GPIO
```

## Step 9: Fix Line Endings (important!)

```bash
sed -i 's/\r$//' ~/pi-thermo/*.py ~/pi-thermo/*.sh
```

## Step 10: Make Scripts Executable

```bash
chmod +x ~/pi-thermo/thermostat.py
chmod +x ~/pi-thermo/execute.sh
chmod +x ~/pi-thermo/activate.sh
```

## Step 11: Test Installation

```bash
source ~/pi-thermo/activate.sh
python3 -c "import luma.oled; import flask; import smbus2; print('[OK] All packages working!')"
```

## Step 12: Run the Thermostat!

```bash
source ~/pi-thermo/activate.sh
python3 ~/pi-thermo/thermostat.py
```

You should see:
```
============================================================
Pi Thermostat Controller Starting
============================================================
[INFO] AHT10 sensor initialized on I2C bus 3
[INFO] OLED display initialized on I2C bus 1, address 0x3c
[INFO] Thermostat controller initialized successfully
[INFO] Starting web server on 0.0.0.0:5000
```

## Step 13: Access the Web Interface

From any device on your network, open:
```
http://192.168.69.22:5000
```

You should see a beautiful dashboard with:
- Current temperature
- Target temperature control
- Humidity reading
- Heating status
- Event log

## Step 14 (Optional): Run as SystemD Service

Keep thermostat running even after you disconnect:

```bash
# Convert service installer line endings
sed -i 's/\r$//' ~/pi-thermo/install_service.sh

# Install service (requires password)
sudo ~/pi-thermo/install_service.sh

# Start it
sudo systemctl start thermostat

# Auto-start on boot
sudo systemctl enable thermostat
```

Check status:
```bash
sudo systemctl status thermostat
sudo journalctl -u thermostat -f
```

## Troubleshooting

### "luma module not found"
```bash
source ~/pi-thermo/activate.sh
pip install luma.oled luma.core
```

### "I2C device not found"
1. Did you run `sudo raspi-config` to enable I2C?
2. Did you reboot after enabling?
3. Check: `i2cdetect -y 1` and `i2cdetect -y 3`

### "Permission denied" on GPIO
```bash
sudo usermod -a -G gpio acohen
# Log out and back in
```

### Web interface not loading
1. Make sure thermostat is running: `ps aux | grep thermostat`
2. Check Pi IP: `hostname -I`
3. Check logs: `tail -f ~/pi-thermo/thermo.log`

## Quick Copy-Paste Commands

If you're impatient, run these one at a time:

```bash
# Full setup sequence
ssh acohen@192.168.69.22
# Enter password

# Commands to run on Pi (one per line, paste carefully):
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y python3-pip python3-venv python3-smbus python3-rpi.gpio i2c-tools build-essential libopenjp2-7 libtiff5 libwebp6

# Enable I2C
sudo raspi-config
# (enable I2C manually, then reboot and SSH back in)

# Setup
cd ~/pi-thermo
python3 -m venv ~/pi-thermo-env
source ~/pi-thermo-env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
sed -i 's/\r$//' ~/pi-thermo/*.py ~/pi-thermo/*.sh
chmod +x ~/pi-thermo/thermostat.py ~/pi-thermo/execute.sh ~/pi-thermo/activate.sh

# Test
python3 -c "import luma.oled; import flask; print('[OK] Ready!')"

# Run
python3 ~/pi-thermo/thermostat.py
```

## What to Watch For

When thermostat starts, you should see:
- ✓ AHT10 sensor initialized
- ✓ OLED display initialized
- ✓ Web server on 0.0.0.0:5000
- ✓ Starting thermostat control loop

If you see errors, check the logs:
```bash
tail -f ~/pi-thermo/thermo.log
```

## Next Steps

1. Set your target temperature in the web interface
2. Monitor the event log to see heating cycles
3. Check `~/pi-thermo/events.log` for history
4. Adjust hysteresis in `config.json` if needed
5. Edit `config.json` to customize behavior

## Accessing from Different Networks

After setup, you can access from anywhere:
- **Local network**: `http://192.168.69.22:5000`
- **Different network**: May need port forwarding or VPN
