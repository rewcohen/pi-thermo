# Pi Thermostat Controller

A complete smart thermostat system for Raspberry Pi Zero 2W featuring:
- ✅ Real-time temperature & humidity monitoring (AHT10 sensor)
- ✅ Hysteresis-based heating control via GPIO relay
- ✅ Beautiful responsive web dashboard (Flask)
- ✅ Live OLED display status
- ✅ Automatic systemd service with boot autostart
- ✅ Event logging for heating cycles
- ✅ All temperatures in **Fahrenheit**

## Hardware Setup

- **Sensor**: AHT10 (I2C bus 3, address 0x38)
- **Display**: SSD1306 OLED 128x64 (I2C bus 1, address 0x3c)
- **Relay**: GPIO pin 13 (BCM mode) - LOW turns relay ON (heating enabled), HIGH turns relay OFF (heating disabled)

## Features

- **Web Interface**: Beautiful responsive dashboard accessible from any browser
  - View current temperature, target setpoint, and humidity in real-time
  - Set target temperature with validation (50-90°F)
  - Live heating on/off status with visual indicators
  - Event log showing all heating on/off transitions with timestamps and temperatures
- **Temperatures in Fahrenheit**: All readings, setpoints, and logs use °F
- **Intelligent Heating Control**: Uses hysteresis-based switching to prevent relay chatter
  - Turns heating ON when temp drops to `target_temp_f - hysteresis`
  - Turns heating OFF when temp rises to `target_temp_f + hysteresis`
- **Event Logging**: Complete history of heating on/off events with timestamp, temperature, and humidity
- **Real-time OLED Display**: Shows current/target temperature, humidity, heating status on display
- **Comprehensive Logging**: All operations logged to `thermo.log` with error handling
- **REST API**: Easy integration with other systems

## Configuration

Edit `config.json` to customize behavior:

```json
{
  "target_temp_f": 72.0,            // Target temperature in °F
  "hysteresis": 1.0,                // Temperature band for on/off switching (±°F)
  "pid_kp": 0.5,                    // PID proportional gain
  "pid_ki": 0.1,                    // PID integral gain
  "pid_kd": 0.2,                    // PID derivative gain
  "sensor_read_interval": 5.0,      // How often to read sensor (seconds)
  "display_update_interval": 1.0,   // How often to update display (seconds)
  "relay_min_on_time": 2.0,         // Minimum heating duration (seconds)
  "relay_min_off_time": 2.0         // Minimum cooling duration (seconds)
}
```

## Running the Thermostat

```bash
# Run directly
python3 ~/pi-thermo/thermostat.py

# Or use the launcher script
~/pi-thermo/execute.sh
```

The application will:
1. Start the thermostat controller (running sensor reads and relay control)
2. Start the web server on `http://0.0.0.0:5000`
3. Display status on the OLED screen
4. Log all events to `thermo.log` and `events.log`

## Web Interface

Access the web dashboard from any device on your network:

```
http://<pi-ip-address>:5000
```

The dashboard provides:
- **Real-time status**: Current temperature, target, humidity, heating status
- **Temperature control**: Set target temperature with validation
- **Event log**: View last 20 heating on/off events with timestamps and temperatures
- **Auto-refresh**: Updates every 2 seconds
- **Responsive design**: Works on desktop, tablet, and mobile

## REST API Endpoints

### Get Status
```bash
curl http://<pi-address>:5000/api/status
```
Returns:
```json
{
  "current_temp_f": 71.5,
  "target_temp_f": 72.0,
  "humidity": 45.2,
  "heating_on": false,
  "timestamp": "2025-11-01T10:30:00"
}
```

### Set Target Temperature
```bash
curl -X POST http://<pi-address>:5000/api/setpoint \
  -H "Content-Type: application/json" \
  -d '{"temperature": 70.5}'
```

### Get Event Log
```bash
curl http://<pi-address>:5000/api/events?limit=50
```
Returns:
```json
{
  "events": [
    {
      "timestamp": "2025-11-01T10:30:15",
      "type": "on",
      "temperature_f": 71.2,
      "humidity": 45.1
    },
    {
      "timestamp": "2025-11-01T10:25:00",
      "type": "off",
      "temperature_f": 72.5,
      "humidity": 44.8
    }
  ]
}
```

## Display Output

The OLED shows 6 lines:

```
THERMOSTAT
Curr: 71.5F
Target: 72.0F
Humidity: 45%
HEATING ON       (or "Heating OFF")
PID: 50%
```

## Logs

Two log files maintain thermostat history:

### thermo.log
General application log:
- Sensor readings
- Relay state changes (ON/OFF with temperature)
- Error messages
- Configuration loaded
- Web server startup/shutdown

### events.log
Heating event history (JSON format, one event per line):
```json
{"timestamp": "2025-11-01T10:30:15.123456", "type": "on", "temperature_f": 71.2, "humidity": 45.1}
{"timestamp": "2025-11-01T10:25:00.654321", "type": "off", "temperature_f": 72.5, "humidity": 44.8}
```
Use for:
- Tracking heating cycles and efficiency
- Analyzing temperature trends
- System troubleshooting

View recent events:
```bash
tail -f ~/pi-thermo/events.log
```

## Control Logic

1. **Sensor Reading**: Samples AHT10 every 5 seconds (configurable)
2. **Temperature Check**: Compares current temp to target with hysteresis band
3. **Relay Control**:
   - If heating is OFF and `temp <= (target - hysteresis)`: Turn heating ON
   - If heating is ON and `temp >= (target + hysteresis)`: Turn heating OFF
   - Respects minimum on/off times to prevent rapid cycling
4. **Display Update**: Updates OLED every 1 second with current status

## Tuning Hysteresis

The hysteresis value prevents the relay from constantly switching:
- Smaller hysteresis (0.5°F): More precise temperature, but more frequent relay switching
- Larger hysteresis (2.0°F): Less relay switching, but wider temperature band

Recommended settings:
- Small spaces: 0.5-1.0°F hysteresis
- Large spaces: 1.5-2.0°F hysteresis
- Monitor the event log to optimize for your system

## Troubleshooting

**Sensor not reading**: Check I2C bus 3 connection and AHT10 address (0x38)
```bash
i2cdetect -y 3
```

**Display not updating**: Check I2C bus 1 and SSD1306 address (0x3c)
```bash
i2cdetect -y 1
```

**Relay not switching**: Check GPIO pin 13 and relay wiring
```bash
gpio -1 mode 13 out
gpio -1 write 13 0  # Turn ON (LOW)
gpio -1 write 13 1  # Turn OFF (HIGH)
```

**Check logs**: 
```bash
tail -f ~/pi-thermo/thermo.log
```
