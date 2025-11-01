# Pi Thermostat - Quick Reference

## Installation

```bash
cd ~/pi-thermo
chmod +x install.sh
./install.sh
```

## Running

```bash
# Direct
python3 ~/pi-thermo/thermostat.py

# Or with virtual env
source ~/pi-thermo/activate.sh
python3 ~/pi-thermo/thermostat.py

# Or as service
sudo systemctl start thermostat
```

## Web Interface

Open browser: `http://<pi-ip>:5000`

Find IP: `hostname -I`

## Logs

```bash
# Application logs
tail -f ~/pi-thermo/thermo.log

# Event history
tail -f ~/pi-thermo/events.log

# Service logs
sudo journalctl -u thermostat -f
```

## Configuration

Edit: `~/pi-thermo/config.json`

Common settings:
```json
{
  "target_temp_f": 72.0,          // Your desired temperature
  "hysteresis": 1.0,              // Temperature tolerance (±°F)
  "sensor_read_interval": 5.0,    // How often to check temp (seconds)
}
```

## Service Control

```bash
# Start/stop/restart
sudo systemctl start thermostat
sudo systemctl stop thermostat
sudo systemctl restart thermostat

# Check status
sudo systemctl status thermostat

# View logs
sudo journalctl -u thermostat -f

# Enable/disable auto-start
sudo systemctl enable thermostat
sudo systemctl disable thermostat
```

## Hardware Check

```bash
# Check I2C devices (OLED should be 0x3c, sensor 0x38)
i2cdetect -y 1    # OLED
i2cdetect -y 3    # Sensor

# List GPIO pins
gpio readall
```

## API Commands

```bash
# Get current status
curl http://localhost:5000/api/status

# Set temperature to 70°F
curl -X POST http://localhost:5000/api/setpoint \
  -H "Content-Type: application/json" \
  -d '{"temperature": 70}'

# Get last 20 events
curl http://localhost:5000/api/events?limit=20
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Module not found | `pip install luma.oled luma.core flask smbus2` |
| I2C device not found | Enable I2C: `sudo raspi-config` → Interfacing → I2C → Yes |
| GPIO permission denied | `sudo usermod -a -G gpio $USER` (log out/back in) |
| Web interface won't load | Check IP with `hostname -I`, verify port 5000 is open |
| Relay not switching | Test GPIO: `gpio -1 mode 13 out && gpio -1 write 13 0` |

## Important Files

| File | Purpose |
|------|---------|
| `thermostat.py` | Main application |
| `config.json` | Settings |
| `thermo.log` | Application log |
| `events.log` | Heating history |
| `templates/index.html` | Web dashboard |

## First Time Setup Checklist

- [ ] Run installer: `./install.sh`
- [ ] Enable I2C: `sudo raspi-config`
- [ ] Verify hardware: `i2cdetect -y 1 && i2cdetect -y 3`
- [ ] Test run: `python3 ~/pi-thermo/thermostat.py`
- [ ] Access web: `http://<pi-ip>:5000`
- [ ] Edit config: `nano ~/pi-thermo/config.json`
- [ ] Set up service: `sudo ~/pi-thermo/install_service.sh`
- [ ] Enable auto-start: `sudo systemctl enable thermostat`
