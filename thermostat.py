#!/usr/bin/env python3
"""
Raspberry Pi Thermostat Controller with Web Interface
Controls heating via relay based on AHT10 temperature sensor
Displays status on SSD1306 OLED screen and web interface
Temperatures in Fahrenheit
"""

import os
import sys
import time
import logging
import json
import signal
import threading
from datetime import datetime
from pathlib import Path
from collections import deque
from threading import Lock

try:
    import smbus2
    import RPi.GPIO as GPIO
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    from luma.core.render import canvas
    from PIL import ImageFont, Image, ImageDraw
    from flask import Flask, render_template, jsonify, request
except ImportError as e:
    print(f"Error: Required library not installed: {e}")
    sys.exit(1)

# ============================================================================
# Configuration
# ============================================================================

CONFIG_FILE = os.path.expanduser("~/pi-thermo/config.json")
LOG_FILE = os.path.expanduser("~/pi-thermo/thermo.log")
EVENT_LOG_FILE = os.path.expanduser("~/pi-thermo/events.log")

# Sensor configuration
AHT10_ADDRESS = 0x38
AHT10_I2C_BUS = 3

# Display configuration
OLED_I2C_BUS = 1
OLED_I2C_ADDR = 0x3c

# Relay configuration (GPIO pin 13, BCM mode)
RELAY_PIN = 13

# Web server configuration
WEB_PORT = 5002
WEB_HOST = "0.0.0.0"

# Default configuration (can be overridden by config.json)
DEFAULT_CONFIG = {
    "target_temp_f": 72.0,         # Target temperature in °F
    "hysteresis": 1.0,             # Hysteresis band (±°F)
    "pid_kp": 0.5,                 # PID proportional gain
    "pid_ki": 0.1,                 # PID integral gain
    "pid_kd": 0.2,                 # PID derivative gain
    "pid_max_output": 1.0,         # Max PID output
    "pid_min_output": 0.0,         # Min PID output
    "sensor_read_interval": 5.0,   # Read sensor every N seconds
    "display_update_interval": 1.0, # Update display every N seconds
    "relay_min_on_time": 2.0,      # Minimum relay ON duration (seconds)
    "relay_min_off_time": 2.0,     # Minimum relay OFF duration (seconds)
}

# ============================================================================
# Logging Setup
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# Event Logger
# ============================================================================

class EventLogger:
    """Track heating on/off events"""
    
    def __init__(self, max_events=500):
        self.events = deque(maxlen=max_events)
        self.lock = Lock()
        self.load_events()
    
    def load_events(self):
        """Load recent events from file"""
        if os.path.exists(EVENT_LOG_FILE):
            try:
                with open(EVENT_LOG_FILE, 'r') as f:
                    lines = f.readlines()
                    for line in lines[-500:]:  # Load last 500 events
                        try:
                            event = json.loads(line.strip())
                            self.events.append(event)
                        except:
                            pass
                logger.info(f"Loaded {len(self.events)} events from {EVENT_LOG_FILE}")
            except Exception as e:
                logger.error(f"Error loading events: {e}")
    
    def log_event(self, event_type, temp_f, humidity):
        """Log a heating event (on/off)"""
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,  # "on" or "off"
            "temperature_f": round(temp_f, 1),
            "humidity": round(humidity, 1) if humidity else None
        }
        
        with self.lock:
            self.events.append(event)
        
        # Write to file
        try:
            with open(EVENT_LOG_FILE, 'a') as f:
                f.write(json.dumps(event) + '\n')
        except Exception as e:
            logger.error(f"Error writing event: {e}")
    
    def get_events(self, limit=100):
        """Get most recent events"""
        with self.lock:
            return list(reversed(list(self.events)[-limit:]))

# ============================================================================
# PID Controller
# ============================================================================

class PIDController:
    """Simple PID controller for temperature control"""
    
    def __init__(self, kp, ki, kd, min_output=0.0, max_output=1.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.min_output = min_output
        self.max_output = max_output
        
        self.integral = 0.0
        self.last_error = 0.0
        self.last_time = time.time()
    
    def update(self, setpoint, measured_value):
        """Calculate PID output"""
        now = time.time()
        dt = now - self.last_time
        self.last_time = now
        
        if dt <= 0:
            return 0.0
        
        error = setpoint - measured_value
        
        # Proportional term
        p_term = self.kp * error
        
        # Integral term with anti-windup
        self.integral += error * dt
        self.integral = max(self.min_output, min(self.max_output, self.integral))
        i_term = self.ki * self.integral
        
        # Derivative term
        d_term = self.kd * (error - self.last_error) / dt if dt > 0 else 0.0
        self.last_error = error
        
        # Total output
        output = p_term + i_term + d_term
        output = max(self.min_output, min(self.max_output, output))
        
        return output

# ============================================================================
# Sensor Interface
# ============================================================================

class AHT10Sensor:
    """AHT10 temperature and humidity sensor"""
    
    def __init__(self, bus=AHT10_I2C_BUS, address=AHT10_ADDRESS):
        self.bus = None
        self.address = address
        self.bus_num = bus
        try:
            self.bus = smbus2.SMBus(bus)
            logger.info(f"AHT10 sensor initialized on I2C bus {bus}")
        except Exception as e:
            logger.error(f"Failed to initialize AHT10 sensor: {e}")
            raise
    
    def celsius_to_fahrenheit(self, celsius):
        """Convert Celsius to Fahrenheit"""
        return (celsius * 9/5) + 32
    
    def read(self):
        """Read temperature (°F) and humidity from sensor"""
        try:
            # Trigger measurement
            trigger_msg = smbus2.i2c_msg.write(self.address, [0xAC, 0x33, 0x00])
            self.bus.i2c_rdwr(trigger_msg)
            time.sleep(0.1)
            
            # Read 6 bytes
            read_msg = smbus2.i2c_msg.read(self.address, 6)
            self.bus.i2c_rdwr(read_msg)
            data = list(read_msg)
            
            # Check if busy
            if data[0] & 0x80:
                logger.warning("Sensor busy, retrying...")
                time.sleep(0.1)
                read_msg = smbus2.i2c_msg.read(self.address, 6)
                self.bus.i2c_rdwr(read_msg)
                data = list(read_msg)
            
            # Extract humidity (20 bits)
            humidity_raw = ((data[1] << 16) | (data[2] << 8) | data[3]) >> 4
            humidity = (humidity_raw / 1048576.0) * 100.0
            
            # Extract temperature (20 bits) in Celsius
            temperature_raw = ((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5]
            temperature_c = (temperature_raw / 1048576.0) * 200.0 - 50.0
            
            # Convert to Fahrenheit
            temperature_f = self.celsius_to_fahrenheit(temperature_c)
            
            logger.debug(f"Sensor read: {temperature_f:.1f}°F ({temperature_c:.1f}°C), {humidity:.1f}%")
            return temperature_f, humidity
        
        except Exception as e:
            logger.error(f"Failed to read AHT10 sensor: {e}")
            return None, None
    
    def close(self):
        """Close I2C connection"""
        if self.bus:
            try:
                self.bus.close()
            except Exception as e:
                logger.error(f"Error closing sensor bus: {e}")

# ============================================================================
# Relay Control
# ============================================================================

class RelayControl:
    """GPIO-based relay control for heating"""
    
    def __init__(self, pin=RELAY_PIN):
        self.pin = pin
        self.relay_state = False
        self.last_state_change = time.time()
        logger.info(f"Relay initialized on GPIO pin {pin} (currently OFF)")
    
    def turn_on(self):
        """Turn relay ON (enables heating) - set GPIO LOW"""
        if not self.relay_state:
            try:
                # Clean up any previous GPIO state
                try:
                    GPIO.cleanup()
                except:
                    pass
                
                # Set up GPIO fresh
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.pin, GPIO.OUT)
                GPIO.output(self.pin, GPIO.LOW)  # LOW = heating ON
                self.relay_state = True
                self.last_state_change = time.time()
                logger.info("Relay turned ON - heating enabled (GPIO pin LOW)")
            except RuntimeError as e:
                # GPIO mode already set, try to just set output
                try:
                    GPIO.output(self.pin, GPIO.LOW)
                    self.relay_state = True
                    self.last_state_change = time.time()
                    logger.info("Relay turned ON - heating enabled (GPIO already initialized)")
                except Exception as e2:
                    logger.error(f"Error turning relay ON: {e} / {e2}")
            except Exception as e:
                logger.error(f"Error turning relay ON: {e}")
    
    def turn_off(self):
        """Turn relay OFF (disables heating) - cleanup GPIO"""
        if self.relay_state:
            try:
                logger.info("Attempting to turn relay OFF via GPIO.cleanup()")
                GPIO.cleanup()
                self.relay_state = False
                self.last_state_change = time.time()
                logger.info("Relay turned OFF - heating disabled (GPIO cleanup)")
            except Exception as e:
                logger.error(f"Error turning relay OFF: {e}")
                raise
    
    def get_state(self):
        """Get current relay state"""
        return self.relay_state
    
    def time_in_state(self):
        """Get how long relay has been in current state"""
        return time.time() - self.last_state_change
    
    def cleanup(self):
        """Clean up GPIO"""
        try:
            GPIO.cleanup()
            logger.info("GPIO cleanup completed")
        except Exception as e:
            logger.error(f"Error during GPIO cleanup: {e}")

# ============================================================================
# Display Interface
# ============================================================================

class OLEDDisplay:
    """SSD1306 OLED display control"""
    
    def __init__(self, bus=OLED_I2C_BUS, address=OLED_I2C_ADDR):
        try:
            serial = i2c(port=bus, address=address)
            self.device = ssd1306(serial)
            self.font = ImageFont.load_default()
            logger.info(f"OLED display initialized on I2C bus {bus}, address 0x{address:02x}")
        except Exception as e:
            logger.error(f"Failed to initialize OLED display: {e}")
            self.device = None
    
    def show_status(self, current_temp_f, target_temp_f, humidity, relay_on, pid_output=0.0):
        """Display thermostat status"""
        if not self.device:
            return
        
        try:
            with canvas(self.device) as draw:
                # Title
                draw.text((0, 0), "THERMOSTAT", font=self.font, fill="white")
                
                # Current temperature and setpoint
                temp_str = f"Curr: {current_temp_f:.1f}F" if current_temp_f is not None else "Curr: N/A"
                draw.text((0, 10), temp_str, font=self.font, fill="white")
                
                target_str = f"Target: {target_temp_f:.1f}F"
                draw.text((0, 20), target_str, font=self.font, fill="white")
                
                # Humidity
                hum_str = f"Humidity: {humidity:.0f}%" if humidity is not None else "Humidity: N/A"
                draw.text((0, 30), hum_str, font=self.font, fill="white")
                
                # Relay status and PID output
                relay_str = "HEATING ON" if relay_on else "Heating OFF"
                pid_str = f"PID: {pid_output*100:.0f}%"
                draw.text((0, 40), relay_str, font=self.font, fill="white")
                draw.text((0, 50), pid_str, font=self.font, fill="white")
        
        except Exception as e:
            logger.error(f"Error updating OLED display: {e}")
    
    def show_error(self, error_msg):
        """Display error message"""
        if not self.device:
            return
        
        try:
            with canvas(self.device) as draw:
                draw.text((0, 0), "ERROR", font=self.font, fill="white")
                draw.text((0, 10), error_msg[:21], font=self.font, fill="white")
                if len(error_msg) > 21:
                    draw.text((0, 20), error_msg[21:42], font=self.font, fill="white")
        except Exception as e:
            logger.error(f"Error displaying error message: {e}")

# ============================================================================
# Configuration Management
# ============================================================================

def load_config():
    """Load configuration from JSON file"""
    config = DEFAULT_CONFIG.copy()
    
    logger.info(f"Loading config from {CONFIG_FILE}")
    logger.info(f"Default target_temp_f: {DEFAULT_CONFIG['target_temp_f']}")
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                content = f.read()
                logger.debug(f"Config file content: {content}")
                user_config = json.loads(content)
                logger.info(f"Loaded config: {user_config}")
                config.update(user_config)
                logger.info(f"Configuration loaded from {CONFIG_FILE} - target_temp_f={config['target_temp_f']}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e} - using defaults")
        except Exception as e:
            logger.error(f"Error loading config file: {e} - using defaults")
    else:
        logger.info(f"Config file not found at {CONFIG_FILE}, creating default")
        # Create default config file
        try:
            config_dir = os.path.dirname(CONFIG_FILE)
            os.makedirs(config_dir, exist_ok=True)
            with open(CONFIG_FILE, 'w') as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
            logger.info(f"Default configuration saved to {CONFIG_FILE}")
        except Exception as e:
            logger.error(f"Error creating config file: {e}")
    
    logger.info(f"Final config loaded: target_temp_f={config.get('target_temp_f', 'MISSING')}")
    return config

def save_config(config):
    """Save configuration to JSON file with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Ensure directory exists
            config_dir = os.path.dirname(CONFIG_FILE)
            os.makedirs(config_dir, exist_ok=True)
            
            # Write with temporary file for safety
            temp_file = CONFIG_FILE + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Atomic rename
            os.replace(temp_file, CONFIG_FILE)
            
            logger.info(f"Configuration saved successfully: target_temp_f={config.get('target_temp_f')}")
            return True
        except Exception as e:
            logger.error(f"Error saving config (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(0.5)  # Brief delay before retry
            else:
                logger.error(f"Failed to save config after {max_retries} attempts")
                return False
    
    return False

# ============================================================================
# Main Thermostat Controller
# ============================================================================

class ThermostatController:
    """Main thermostat controller"""
    
    def __init__(self):
        self.config = load_config()
        self.sensor = None
        self.relay = None
        self.display = None
        self.pid = None
        self.event_logger = EventLogger()
        self.running = True
        self.last_sensor_read = 0
        self.current_temp_f = None
        self.current_humidity = None
        self.config_lock = Lock()
        
        # Initialize components
        try:
            self.sensor = AHT10Sensor()
            self.relay = RelayControl()
            self.display = OLEDDisplay()
            
            # Initialize PID controller
            self.pid = PIDController(
                kp=self.config["pid_kp"],
                ki=self.config["pid_ki"],
                kd=self.config["pid_kd"],
                min_output=self.config["pid_min_output"],
                max_output=self.config["pid_max_output"]
            )
            
            logger.info("Thermostat controller initialized successfully")
        
        except Exception as e:
            logger.error(f"Failed to initialize thermostat: {e}")
            self.cleanup()
            raise
    
    def update_temperature(self):
        """Read temperature from sensor"""
        try:
            temp_f, humidity = self.sensor.read()
            if temp_f is not None:
                self.current_temp_f = temp_f
                self.current_humidity = humidity
                return True
            return False
        except Exception as e:
            logger.error(f"Error reading temperature: {e}")
            return False
    
    def control_heating(self):
        """Main control logic using hysteresis"""
        if self.current_temp_f is None:
            logger.warning("Cannot control heating - no temperature reading")
            return
        
        with self.config_lock:
            target = self.config["target_temp_f"]
            hysteresis = self.config["hysteresis"]
            min_on = self.config["relay_min_on_time"]
            min_off = self.config["relay_min_off_time"]
        
        # Relay on/off decision: use threshold-based switching with hysteresis
        time_in_state = self.relay.time_in_state()
        
        if self.relay.get_state():
            # Currently ON: turn off if temp >= target + hysteresis
            if self.current_temp_f >= (target + hysteresis) and time_in_state >= min_on:
                self.relay.turn_off()
                logger.info(f"Temperature reached {self.current_temp_f:.1f}°F, turning off heat")
                self.event_logger.log_event("off", self.current_temp_f, self.current_humidity)
        else:
            # Currently OFF: turn on if temp <= target - hysteresis
            if self.current_temp_f <= (target - hysteresis) and time_in_state >= min_off:
                self.relay.turn_on()
                logger.info(f"Temperature dropped to {self.current_temp_f:.1f}°F, turning on heat")
                self.event_logger.log_event("on", self.current_temp_f, self.current_humidity)
    
    def update_display(self):
        """Update OLED display"""
        try:
            with self.config_lock:
                target_temp = self.config["target_temp_f"]
            
            # Calculate PID output for display (0-1 range)
            if self.current_temp_f is not None and self.relay.get_state():
                pid_output = 0.5 if self.relay.get_state() else 0.0
            else:
                pid_output = 0.0
            
            self.display.show_status(
                self.current_temp_f,
                target_temp,
                self.current_humidity,
                self.relay.get_state(),
                pid_output
            )
        except Exception as e:
            logger.error(f"Error updating display: {e}")
    
    def set_target_temp(self, temp_f):
        """Set target temperature with validation"""
        logger.info(f"[SET_TEMP] Starting with temp_f={temp_f}")
        try:
            temp_f_float = float(temp_f)
            logger.info(f"[SET_TEMP] Converted to float: {temp_f_float}")
            
            # Validate range
            if not (50 <= temp_f_float <= 90):
                logger.error(f"[SET_TEMP] Temperature {temp_f_float} out of valid range 50-90°F")
                return False
            
            logger.info(f"[SET_TEMP] Acquiring config_lock")
            with self.config_lock:
                old_temp = self.config.get("target_temp_f")
                logger.info(f"[SET_TEMP] Old temperature: {old_temp}, New temperature: {temp_f_float}")
                self.config["target_temp_f"] = temp_f_float
            
            # Save to disk
            logger.info(f"[SET_TEMP] Calling save_config()")
            if save_config(self.config):
                logger.info(f"[SET_TEMP] SUCCESS - Target temperature changed from {old_temp}°F to {temp_f_float}°F")
                return True
            else:
                logger.error(f"[SET_TEMP] FAILED - save_config returned False for {temp_f_float}°F")
                # Revert change
                with self.config_lock:
                    self.config["target_temp_f"] = old_temp
                return False
        except ValueError as e:
            logger.error(f"[SET_TEMP] Invalid temperature value: {temp_f} - {e}")
            return False
        except Exception as e:
            logger.error(f"[SET_TEMP] Unexpected error: {e}", exc_info=True)
            return False
    
    def get_status(self):
        """Get current status for web interface"""
        with self.config_lock:
            target_temp = self.config["target_temp_f"]
        
        return {
            "current_temp_f": round(self.current_temp_f, 1) if self.current_temp_f else None,
            "target_temp_f": target_temp,
            "humidity": round(self.current_humidity, 1) if self.current_humidity else None,
            "heating_on": self.relay.get_state(),
            "timestamp": datetime.now().isoformat()
        }
    
    def run(self):
        """Main control loop"""
        logger.info("Starting thermostat control loop")
        
        last_display_update = 0
        
        try:
            while self.running:
                now = time.time()
                
                # Read sensor at configured interval
                with self.config_lock:
                    sensor_interval = self.config["sensor_read_interval"]
                    display_interval = self.config["display_update_interval"]
                
                if now - self.last_sensor_read >= sensor_interval:
                    if self.update_temperature():
                        self.control_heating()
                        last_display_update = 0  # Force display update
                    self.last_sensor_read = now
                
                # Update display at configured interval
                if now - last_display_update >= display_interval:
                    self.update_display()
                    last_display_update = now
                
                time.sleep(0.1)
        
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources...")
        
        try:
            if self.relay:
                self.relay.turn_off()
                self.relay.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up relay: {e}")
        
        try:
            if self.sensor:
                self.sensor.close()
        except Exception as e:
            logger.error(f"Error closing sensor: {e}")
        
        logger.info("Thermostat shutdown complete")
    
    def signal_handler(self, sig, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {sig}, shutting down...")
        self.running = False

# ============================================================================
# Web Server
# ============================================================================

# Global thermostat controller instance
controller = None

def create_app():
    """Create Flask app"""
    app = Flask(__name__, template_folder=os.path.expanduser("~/pi-thermo/templates"))
    
    @app.route('/')
    def index():
        """Serve web interface"""
        return render_template('index.html')
    
    @app.route('/api/status', methods=['GET'])
    def api_status():
        """Get current thermostat status"""
        if controller:
            return jsonify(controller.get_status())
        return jsonify({"error": "Controller not initialized"}), 500
    
    @app.route('/api/setpoint', methods=['POST'])
    def api_setpoint():
        """Set target temperature"""
        logger.info(f"[SETPOINT API] Received POST request")
        data = request.get_json()
        logger.info(f"[SETPOINT API] Request data: {data}")
        
        if 'temperature' not in data:
            logger.error("[SETPOINT API] Missing temperature parameter")
            return jsonify({"error": "Missing temperature parameter"}), 400
        
        try:
            temp = float(data['temperature'])
            logger.info(f"[SETPOINT API] Parsed temperature: {temp}°F")
            
            if 50 <= temp <= 90:  # Reasonable range
                logger.info(f"[SETPOINT API] Temperature in valid range, calling set_target_temp({temp})")
                result = controller.set_target_temp(temp)
                logger.info(f"[SETPOINT API] set_target_temp returned: {result}")
                
                if result:
                    logger.info(f"[SETPOINT API] SUCCESS - Set target to {temp}°F")
                    return jsonify({"status": "ok", "target_temp_f": temp})
                else:
                    logger.error(f"[SETPOINT API] FAILED - set_target_temp returned False for {temp}°F")
                    return jsonify({"error": "Failed to save temperature setting"}), 500
            else:
                logger.error(f"[SETPOINT API] Temperature {temp}°F out of range (50-90)")
                return jsonify({"error": "Temperature out of range (50-90°F)"}), 400
        except ValueError as e:
            logger.error(f"[SETPOINT API] Invalid temperature value: {data.get('temperature')} - {e}")
            return jsonify({"error": f"Invalid temperature value: {e}"}), 400
        except Exception as e:
            logger.error(f"[SETPOINT API] Unexpected error: {e}", exc_info=True)
            return jsonify({"error": f"Server error: {e}"}), 500
    
    @app.route('/api/events', methods=['GET'])
    def api_events():
        """Get heating on/off event log"""
        limit = request.args.get('limit', 100, type=int)
        if controller:
            events = controller.event_logger.get_events(limit)
            return jsonify({"events": events})
        return jsonify({"error": "Controller not initialized"}), 500
    
    return app

# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main entry point"""
    global controller
    
    logger.info("=" * 60)
    logger.info("Pi Thermostat Controller Starting")
    logger.info("=" * 60)
    
    try:
        controller = ThermostatController()
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, controller.signal_handler)
        signal.signal(signal.SIGTERM, controller.signal_handler)
        
        # Start controller thread
        control_thread = threading.Thread(target=controller.run, daemon=False)
        control_thread.start()
        
        # Start web server
        app = create_app()
        logger.info(f"Starting web server on {WEB_HOST}:{WEB_PORT}")
        try:
            # Allow socket reuse to fix "Address already in use" errors
            from werkzeug.serving import make_server
            server = make_server(WEB_HOST, WEB_PORT, app, threaded=True)
            server.socket.setsockopt(1, 15, 1)  # SO_REUSEADDR
            logger.info(f"Web server initialized on {WEB_HOST}:{WEB_PORT}")
            server.serve_forever()
        except Exception as e:
            logger.error(f"Web server error: {e}")
        
        # Wait for control thread
        control_thread.join()
    
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("Pi Thermostat Controller Stopped")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
