# Pi Thermostat - Setup Guide

Complete setup instructions for installing and running the Pi Thermostat system.

## Quick Start

### 1. Run the Installer

```bash
cd ~/pi-thermo
chmod +x install.sh
./install.sh
```

The installer will:
- Update system packages
- Install all system dependencies
- Create a Python virtual environment
- Install all required Python packages
- Verify all imports
- Create necessary directories and files

### 2. Enable I2C Interface

The installer will prompt you. If needed, manually enable I2C:

```bash
sudo raspi-config
```

Navigate to:
- `Interface Options` → `I2C` → `Yes`
- Reboot when asked

### 3. Verify Hardware

Check that both I2C devices are detected:

```bash
# Check OLED display (should show 0x3c)
i2cdetect -y 1

# Check temperature sensor (should show 0x38)
i2cdetect -y 3
```

Example output:
```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:          -- -- -- -- -- -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- 38 -- -- -- 3c -- -- --
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
```

If devices don't show up, check:
- I2C cables and connections
- GPIO pin header seating
- Pull-up resistor presence (should be built-in)

### 4. Run the Thermostat

#### Option A: Direct Execution

```bash
cd ~/pi-thermo
python3 thermostat.py
```

#### Option B: With Virtual Environment

```bash
source ~/pi-thermo/activate.sh
python3 ~/pi-thermo/thermostat.py
```

#### Option C: As SystemD Service (Auto-Start)

```bash
sudo ~/pi-thermo/install_service.sh
sudo systemctl start thermostat
```

### 5. Access the Web Interface

Open a browser on any device connected to your network:

```
http://<your-pi-ip>:5000
```

Find your Pi's IP:
```bash
hostname -I
```

## Directory Structure

```
~/pi-thermo/
├── thermostat.py           # Main application
├── config.json             # Configuration (edit this)
├── templates/
│   └── index.html         # Web interface
├── thermo.log             # Application logs
├── events.log             # Heating event history
├── install.sh             # Initial installer
├── install_service.sh     # SystemD service installer
├── activate.sh            # Virtual environment activator
├── execute.sh             # Legacy launcher
└── README.md              # Full documentation
```

## Configuration

Edit `~/pi-thermo/config.json` to customize:

```json
{
  "target_temp_f": 72.0,              // Target temperature (50-90°F)
  "hysteresis": 1.0,                  // Temperature swing (±°F)
  "pid_kp": 0.5,                      // PID proportional gain
  "pid_ki": 0.1,                      // PID integral gain
  "pid_kd": 0.2,                      // PID derivative gain
  "sensor_read_interval": 5.0,        // Read sensor every N seconds
  "display_update_interval": 1.0,     // Update OLED every N seconds
  "relay_min_on_time": 2.0,           // Min heating duration (seconds)
  "relay_min_off_time": 2.0           // Min cooling duration (seconds)
}
```

Changes take effect immediately without restarting.

## Virtual Environment

The installer creates a virtual environment at `~/pi-thermo-env/`.

Activate it anytime:
```bash
source ~/pi-thermo-env/bin/activate
```

Or use the helper:
```bash
source ~/pi-thermo/activate.sh
```

## Running as SystemD Service

### Install Service

```bash
sudo ~/pi-thermo/install_service.sh
```

### Control Service

```bash
# Start
sudo systemctl start thermostat

# Stop
sudo systemctl stop thermostat

# Restart
sudo systemctl restart thermostat

# Check status
sudo systemctl status thermostat

# View logs
sudo journalctl -u thermostat -f

# Disable auto-start
sudo systemctl disable thermostat

# Enable auto-start
sudo systemctl enable thermostat
```

## Logs

### Application Log (`thermo.log`)
- General operations
- Sensor readings
- Relay state changes
- Errors and warnings

View:
```bash
tail -f ~/pi-thermo/thermo.log
```

### Event Log (`events.log`)
- Heating on/off transitions
- Temperature at each event
- Humidity reading
- Timestamps

View recent events:
```bash
tail -20 ~/pi-thermo/events.log
```

Parse specific events:
```bash
grep '"type": "on"' ~/pi-thermo/events.log | wc -l  # Count heating cycles
```

### Service Log (if running as service)
View service-specific logs:
```bash
sudo journalctl -u thermostat -f
tail -f ~/pi-thermo/service.log
```

## API Reference

### Get Status
```bash
curl http://localhost:5000/api/status
```

### Set Temperature
```bash
curl -X POST http://localhost:5000/api/setpoint \
  -H "Content-Type: application/json" \
  -d '{"temperature": 70.5}'
```

### Get Events
```bash
curl http://localhost:5000/api/events?limit=50
```

## Troubleshooting

### Module Not Found Error

```
Error: Required library not installed: No module named 'luma'
```

Solution:
```bash
source ~/pi-thermo-env/bin/activate
pip install luma.oled luma.core pillow flask smbus2 RPi.GPIO
```

### I2C Device Not Found

```
Error: Failed to read AHT10 sensor: [Errno 2] No such file or directory
```

Solutions:
1. Enable I2C: `sudo raspi-config`
2. Verify cables and connections
3. Check device addresses: `i2cdetect -y 1` and `i2cdetect -y 3`
4. Verify I2C bus numbers in config

### GPIO Permission Denied

```
RuntimeError: No access to /dev/mem.  Try running as root!
```

Solution:
```bash
# Add user to gpio group
sudo usermod -a -G gpio $(whoami)

# Log out and back in for changes to take effect
```

### Web Interface Not Loading

1. Check firewall allows port 5000
2. Verify Pi's IP: `hostname -I`
3. Check thermostat logs: `tail -f ~/pi-thermo/thermo.log`
4. Try `curl http://localhost:5000` from the Pi

### Temperature Readings Incorrect

1. Check sensor connection
2. Verify I2C address: `i2cdetect -y 3` (should show 0x38)
3. View debug info: `grep "Sensor read" ~/pi-thermo/thermo.log`

### Relay Not Switching

1. Verify GPIO pin 13 connection
2. Check relay module wiring
3. Test GPIO manually:
   ```bash
   gpio -1 mode 13 out
   gpio -1 write 13 0  # Turn ON
   gpio -1 write 13 1  # Turn OFF
   ```

## Performance Optimization

### Sensor Read Interval
- Smaller values (1-3s): More responsive but higher CPU
- Larger values (10-30s): Lower CPU but slower response
- Default: 5 seconds (balanced)

### Hysteresis Tuning
- Too small (0.2°F): Relay chatter, excessive cycling
- Too large (3.0°F): Poor temperature control
- Recommended: 0.5-1.5°F

Monitor event frequency:
```bash
tail -100 ~/pi-thermo/events.log | jq -s length
```

### Display Updates
- Update interval doesn't affect control frequency
- Lower values = more responsive display
- Higher values = lower CPU usage

## Security

The web server is accessible to all devices on your network. For production:

1. Use a reverse proxy with authentication (nginx + basic auth)
2. Run behind a firewall
3. Change default port in code
4. Add API token validation
5. Use HTTPS with self-signed certificate

## Uninstalling

Remove everything:
```bash
# Stop the service (if running)
sudo systemctl stop thermostat
sudo systemctl disable thermostat
sudo rm /etc/systemd/system/thermostat.service
sudo systemctl daemon-reload

# Remove installed packages (optional)
rm -rf ~/pi-thermo
rm -rf ~/pi-thermo-env
```

## Support

For issues, check:
1. Installation log: `cat ~/pi-thermo/install.log`
2. Application logs: `tail -f ~/pi-thermo/thermo.log`
3. Event logs: `tail -f ~/pi-thermo/events.log`
4. GPIO test: `gpio readall`
5. I2C test: `i2cdetect -y 1 && i2cdetect -y 3`
