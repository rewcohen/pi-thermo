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
import socket
import subprocess
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

# Default configuration (optimized for Pi Zero 2W with energy saving)
DEFAULT_CONFIG = {
    "target_temp_f": 72.0,         # Target temperature in °F
    "hysteresis": 1.0,             # Hysteresis band (±°F)
    "pid_kp": 0.5,                 # PID proportional gain
    "pid_ki": 0.1,                 # PID integral gain
    "pid_kd": 0.2,                 # PID derivative gain
    "pid_max_output": 1.0,         # Max PID output
    "pid_min_output": 0.0,         # Min PID output
    "sensor_read_interval": 5.0,   # Read sensor every N seconds
    "display_update_interval": 2.0, # Update display every N seconds (slower for Pi Zero 2W)
    "relay_min_on_time": 2.0,      # Minimum relay ON duration (seconds)
    "relay_min_off_time": 2.0,     # Minimum relay OFF duration (seconds)
    "outside_temp_check_interval": 900,  # Check outside temp every 15 minutes
    "thermal_analysis_enabled": True,     # Enable thermal analysis
    "energy_saving_min_temp": 60.0,       # Minimum temp during energy saving
    "energy_saving_override_duration": 3600,  # Override duration in seconds (1 hour)
    "thermal_data_retention_hours": 24,    # How long to keep thermal data
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
# Utility Functions
# ============================================================================

def get_ip_address():
    """Get the local IP address - avoid loopback and return actual network IP"""
    try:
        # Try multiple methods to get actual network IP (not loopback)
        
        # Method 1: Connect to external address and get local socket address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith('127.') and not ip.startswith('0.'):
                s.close()
                return ip
        except:
            pass
        s.close()
        
        # Method 2: Try common network interface addresses
        possible_ips = ['192.168.1.100', '192.168.0.100', '10.0.0.100', '172.16.0.100']
        for test_ip in possible_ips:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            try:
                s.bind((test_ip, 0))
                s.close()
                return test_ip
            except:
                s.close()
                continue
        
        # Method 3: Fallback to hostname method with validation
        hostname = socket.gethostname()
        try:
            ip = socket.gethostbyname(hostname)
            if ip and not ip.startswith('127.') and not ip.startswith('0.'):
                return ip
        except:
            pass
        
        # Default fallback (common for home networks)
        return "192.168.1.100"
        
    except Exception as e:
        logger.error(f"Error getting IP address: {e}")
        return "192.168.1.100"

def get_outside_temperature():
    """Get outside temperature from wttr.in API"""
    try:
        # Use curl to fetch temperature for zipcode 18960
        result = subprocess.run(
            ['curl', '-s', 'https://wttr.in/18960?format=%t&u'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            temp_str = result.stdout.strip()
            # Parse format like "+45°F" or "32°F"
            if '°F' in temp_str:
                temp_str = temp_str.replace('°F', '').strip()
                # Handle signs like + or -
                if temp_str.startswith('+'):
                    temp_str = temp_str[1:]
                try:
                    temp_f = float(temp_str)
                    logger.info(f"Outside temperature: {temp_f}°F")
                    return temp_f
                except ValueError:
                    logger.error(f"Could not parse temperature: {temp_str}")
        else:
            logger.error(f"curl failed with return code: {result.returncode}")
            
    except subprocess.TimeoutExpired:
        logger.error("Timeout fetching outside temperature")
    except Exception as e:
        logger.error(f"Error fetching outside temperature: {e}")
    
    return None

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
# Thermal Analysis
# ============================================================================

class ThermalAnalysis:
    """Track and analyze heating/cooling rates"""
    
    def __init__(self, max_samples=50):
        self.max_samples = max_samples
        self.temperature_data = deque(maxlen=max_samples)
        self.heating_rates = deque(maxlen=20)
        self.cooling_rates = deque(maxlen=20)
        self.lock = Lock()
        
        # Current rates
        self.heating_rate_seconds_per_degree = None
        self.cooling_rate_seconds_per_degree = None
    
    def add_temperature_reading(self, temp_f, heating_on):
        """Add temperature reading with heating state"""
        now = time.time()
        reading = {
            "timestamp": now,
            "temperature_f": temp_f,
            "heating_on": heating_on
        }
        
        with self.lock:
            self.temperature_data.append(reading)
            
            # Calculate rates if we have enough data
            if len(self.temperature_data) >= 3:
                self._calculate_rates()
    
    def _calculate_rates(self):
        """Calculate heating and cooling rates from data"""
        data = list(self.temperature_data)
        
        # Heating rates (when heating turns on and temperature rises)
        for i in range(1, len(data)):
            if not data[i-1]["heating_on"] and data[i]["heating_on"]:
                # Heating just turned on - look for temperature rise
                for j in range(i, min(i+10, len(data))):
                    if data[j]["temperature_f"] and data[i]["temperature_f"]:
                        temp_change = data[j]["temperature_f"] - data[i]["temperature_f"]
                        time_change = data[j]["timestamp"] - data[i]["timestamp"]
                        
                        if temp_change > 0.5 and time_change > 60:  # At least 0.5°F change over 1 minute
                            rate = time_change / temp_change  # seconds per degree
                            if 300 < rate < 3600:  # Reasonable range: 5 min to 1 hour per degree
                                self.heating_rates.append(rate)
                                break
        
        # Cooling rates (when heating turns off and temperature falls)
        for i in range(1, len(data)):
            if data[i-1]["heating_on"] and not data[i]["heating_on"]:
                # Heating just turned off - look for temperature fall
                for j in range(i, min(i+15, len(data))):
                    if data[j]["temperature_f"] and data[i]["temperature_f"]:
                        temp_change = data[i]["temperature_f"] - data[j]["temperature_f"]
                        time_change = data[j]["timestamp"] - data[i]["timestamp"]
                        
                        if temp_change > 0.5 and time_change > 120:  # At least 0.5°F change over 2 minutes
                            rate = time_change / temp_change  # seconds per degree
                            if 600 < rate < 7200:  # Reasonable range: 10 min to 2 hours per degree
                                self.cooling_rates.append(rate)
                                break
        
        # Update current averages
        if len(self.heating_rates) >= 3:
            self.heating_rate_seconds_per_degree = sum(self.heating_rates) / len(self.heating_rates)
        
        if len(self.cooling_rates) >= 3:
            self.cooling_rate_seconds_per_degree = sum(self.cooling_rates) / len(self.cooling_rates)
    
    def get_thermal_data(self):
        """Get current thermal analysis data"""
        with self.lock:
            return {
                "heating_rate_seconds_per_degree": self.heating_rate_seconds_per_degree,
                "cooling_rate_seconds_per_degree": self.cooling_rate_seconds_per_degree,
                "heating_samples": len(self.heating_rates),
                "cooling_samples": len(self.cooling_rates),
                "total_samples": len(self.temperature_data)
            }

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
            self.font = ImageFont.load_default()  # Use normal size font
            self.show_temp = True  # For temp/humidity cycling
            self.last_cycle_time = time.time()
            self.cycle_interval = 5.0  # Cycle every 5 seconds
            logger.info(f"OLED display initialized on I2C bus {bus}, address 0x{address:02x}")
        except Exception as e:
            logger.error(f"Failed to initialize OLED display: {e}")
            self.device = None
    
    def show_status(self, current_temp_f, target_temp_f, humidity, relay_on, pid_output=0.0, outside_temp=None, energy_saving_active=False, thermal_data=None):
        """Display thermostat status with energy saving mode"""
        if not self.device:
            return
        
        try:
            ip_address = get_ip_address()
            system_status = "***SYSTEM ON***" if relay_on else "***SYSTEM OFF***"
            
            with canvas(self.device) as draw:
                # Check if we need to cycle temp/humidity display
                now = time.time()
                if now - self.last_cycle_time >= self.cycle_interval:
                    self.show_temp = not self.show_temp
                    self.last_cycle_time = now
                
                # Line 1: System status (normal font, yellow for first 16 pixels)
                draw.text((0, 2), system_status, font=self.font, fill="yellow")
                
                # Line 2: IP address (yellow for first 16 pixels)
                draw.text((0, 18), f"IP: {ip_address}", font=self.font, fill="yellow")
                
                # Line 3: Combined temp/humidity cycling (below yellow zone)
                if self.show_temp:
                    temp_str = f"Inside: {current_temp_f:.1f}F" if current_temp_f is not None else "Inside: N/A"
                    draw.text((0, 32), temp_str, font=self.font, fill="white")
                else:
                    hum_str = f"Humidity: {humidity:.0f}%" if humidity is not None else "Humidity: N/A"
                    draw.text((0, 32), hum_str, font=self.font, fill="white")
                
                # Line 4: Outside temperature
                if outside_temp is not None:
                    outside_str = f"Outside: {outside_temp:.1f}F"
                else:
                    outside_str = "Outside: --F"
                draw.text((0, 42), outside_str, font=self.font, fill="white")
                
                # Line 5: Energy saving status or target temperature
                if energy_saving_active:
                    draw.text((0, 52), "ENERGY SAVE", font=self.font, fill="red")
                else:
                    target_str = f"Target: {target_temp_f:.1f}F"
                    draw.text((0, 52), target_str, font=self.font, fill="white")
                
                # Line 6: Thermal rate when available (only if temp shown, otherwise skip)
                if self.show_temp and thermal_data:
                    if relay_on and thermal_data.get("heating_rate_seconds_per_degree"):
                        rate_min = thermal_data["heating_rate_seconds_per_degree"] / 60
                        rate_str = f"Heat: {rate_min:.1f}°/min"
                        draw.text((0, 62), rate_str, font=self.font, fill="white")
                    elif not relay_on and thermal_data.get("cooling_rate_seconds_per_degree"):
                        rate_min = thermal_data["cooling_rate_seconds_per_degree"] / 60
                        rate_str = f"Cool: {rate_min:.1f}°/min"
                        draw.text((0, 62), rate_str, font=self.font, fill="white")
        
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
    """Main thermostat controller with energy saving mode"""
    
    def __init__(self):
        self.config = load_config()
        self.sensor = None
        self.relay = None
        self.display = None
        self.pid = None
        self.event_logger = EventLogger()
        self.thermal_analysis = None
        self.running = True
        self.last_sensor_read = 0
        self.current_temp_f = None
        self.current_humidity = None
        self.outside_temp = None
        self.last_outside_temp_check = 0
        self.config_lock = Lock()
        
        # Energy saving mode variables
        self.energy_saving_active = False
        self.energy_saving_override = False
        self.override_start_time = 0
        
        # Initialize components
        try:
            self.sensor = AHT10Sensor()
            self.relay = RelayControl()
            self.display = OLEDDisplay()
            
            # Initialize thermal analysis
            self.thermal_analysis = ThermalAnalysis()
            
            # Initialize PID controller
            self.pid = PIDController(
                kp=self.config["pid_kp"],
                ki=self.config["pid_ki"],
                kd=self.config["pid_kd"],
                min_output=self.config["pid_min_output"],
                max_output=self.config["pid_max_output"]
            )
            
            # Initial outside temperature check
            self.update_outside_temperature()
            
            logger.info("Thermostat controller with energy saving initialized successfully")
        
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
                
                # Add to thermal analysis
                if self.thermal_analysis:
                    self.thermal_analysis.add_temperature_reading(temp_f, self.relay.get_state())
                
                return True
            return False
        except Exception as e:
            logger.error(f"Error reading temperature: {e}")
            return False
    
    def update_outside_temperature(self):
        """Update outside temperature with caching"""
        now = time.time()
        check_interval = self.config.get("outside_temp_check_interval", 900)  # 15 minutes default
        
        if now - self.last_outside_temp_check >= check_interval or self.outside_temp is None:
            outside_temp = get_outside_temperature()
            if outside_temp is not None:
                self.outside_temp = outside_temp
                self.last_outside_temp_check = now
                logger.info(f"Updated outside temperature: {outside_temp:.1f}°F")
            else:
                logger.warning("Failed to fetch outside temperature")
    
    def check_energy_saving_mode(self):
        """Check if energy saving mode should be active"""
        if self.energy_saving_override:
            # Check if override period has expired
            override_duration = self.config.get("energy_saving_override_duration", 3600)
            if time.time() - self.override_start_time >= override_duration:
                self.energy_saving_override = False
                logger.info("Energy saving override expired, returning to normal mode")
        
        # Don't apply energy saving if override is active
        if self.energy_saving_override:
            self.energy_saving_active = False
            return False
        
        # Energy saving logic: if outside >= inside, don't heat (except minimum temp)
        if self.outside_temp is not None and self.current_temp_f is not None:
            if self.outside_temp >= self.current_temp_f:
                self.energy_saving_active = True
                return True
            else:
                self.energy_saving_active = False
        
        return False
    
    def set_energy_saving_override(self):
        """Override energy saving mode for specified duration"""
        self.energy_saving_override = True
        self.override_start_time = time.time()
        self.energy_saving_active = False
        override_duration = self.config.get("energy_saving_override_duration", 3600)
        logger.info(f"Energy saving override activated for {override_duration/3600:.1f} hours")
    
    def control_heating(self):
        """Main control logic using hysteresis with energy saving mode"""
        if self.current_temp_f is None:
            logger.warning("Cannot control heating - no temperature reading")
            return
        
        # Check energy saving mode
        is_energy_saving = self.check_energy_saving_mode()
        
        with self.config_lock:
            target = self.config["target_temp_f"]
            hysteresis = self.config["hysteresis"]
            min_on = self.config["relay_min_on_time"]
            min_off = self.config["relay_min_off_time"]
            min_temp = self.config.get("energy_saving_min_temp", 60.0)
        
        # Energy saving override
        if is_energy_saving:
            # Only allow heating to maintain minimum temperature
            if self.current_temp_f <= min_temp and not self.relay.get_state():
                # Check minimum off time
                if self.relay.time_in_state() >= min_off:
                    self.relay.turn_on()
                    logger.info(f"Energy saving active, minimum temp reached {self.current_temp_f:.1f}°F, turning on heat")
                    self.event_logger.log_event("on", self.current_temp_f, self.current_humidity)
            elif self.relay.get_state() and self.current_temp_f >= (min_temp + 1.0):
                # Turn off when above minimum temp + safety margin
                if self.relay.time_in_state() >= min_on:
                    self.relay.turn_off()
                    logger.info(f"Energy saving active, minimum temp restored {self.current_temp_f:.1f}°F, turning off heat")
                    self.event_logger.log_event("off", self.current_temp_f, self.current_humidity)
            return
        
        # Normal control logic when not in energy saving mode
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
        """Update OLED display with energy saving and thermal data"""
        try:
            with self.config_lock:
                target_temp = self.config["target_temp_f"]
            
            # Get thermal data if available
            thermal_data = None
            if self.thermal_analysis and self.config.get("thermal_analysis_enabled", True):
                thermal_data = self.thermal_analysis.get_thermal_data()
            
            self.display.show_status(
                self.current_temp_f,
                target_temp,
                self.current_humidity,
                self.relay.get_state(),
                0.0,  # PID output not used anymore
                self.outside_temp,
                self.energy_saving_active,
                thermal_data
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
        
        # Get thermal data if available
        thermal_data = None
        if self.thermal_analysis and self.config.get("thermal_analysis_enabled", True):
            thermal_data = self.thermal_analysis.get_thermal_data()
        
        return {
            "current_temp_f": round(self.current_temp_f, 1) if self.current_temp_f else None,
            "target_temp_f": target_temp,
            "humidity": round(self.current_humidity, 1) if self.current_humidity else None,
            "heating_on": self.relay.get_state(),
            "outside_temp_f": round(self.outside_temp, 1) if self.outside_temp else None,
            "energy_saving_active": self.energy_saving_active,
            "energy_saving_override": self.energy_saving_override,
            "thermal_data": thermal_data,
            "timestamp": datetime.now().isoformat()
        }
    
    def run(self):
        """Main control loop - optimized for Pi Zero 2W"""
        logger.info("Starting thermostat control loop (Pi Zero 2W optimized)")
        
        last_display_update = 0
        
        # Cache intervals to reduce lock contention
        sensor_interval = self.config["sensor_read_interval"]
        display_interval = self.config["display_update_interval"]
        
        try:
            while self.running:
                now = time.time()
                
                # Read sensor at configured interval
                if now - self.last_sensor_read >= sensor_interval:
                    if self.update_temperature():
                        self.control_heating()
                        last_display_update = 0  # Force display update
                    self.last_sensor_read = now
                    
                    # Check outside temperature less frequently (every sensor read)
                    self.update_outside_temperature()
                
                # Update display at configured interval
                if now - last_display_update >= display_interval:
                    self.update_display()
                    last_display_update = now
                
                # Longer sleep for Pi Zero 2W to reduce CPU usage
                time.sleep(0.5)  # Increased from 0.1 to 0.5
                
                # Recreate intervals only when needed (every 10 loops)
                if int(now) % 10 == 0:
                    with self.config_lock:
                        sensor_interval = self.config["sensor_read_interval"]
                        display_interval = self.config["display_update_interval"]
        
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
    
    @app.route('/api/outside-temp', methods=['GET'])
    def api_outside_temp():
        """Get current outside temperature"""
        if controller:
            return jsonify({
                "outside_temp_f": round(controller.outside_temp, 1) if controller.outside_temp else None,
                "last_check": controller.last_outside_temp_check,
                "timestamp": datetime.now().isoformat()
            })
        return jsonify({"error": "Controller not initialized"}), 500
    
    @app.route('/api/energy-saving', methods=['GET', 'POST'])
    def api_energy_saving():
        """Get or set energy saving mode status"""
        if not controller:
            return jsonify({"error": "Controller not initialized"}), 500
        
        if request.method == 'GET':
            return jsonify({
                "energy_saving_active": controller.energy_saving_active,
                "energy_saving_override": controller.energy_saving_override,
                "override_start_time": controller.override_start_time,
                "outside_temp_f": round(controller.outside_temp, 1) if controller.outside_temp else None,
                "inside_temp_f": round(controller.current_temp_f, 1) if controller.current_temp_f else None,
                "timestamp": datetime.now().isoformat()
            })
        elif request.method == 'POST':
            data = request.get_json() or {}
            
            # Handle override request
            if data.get('override', False):
                controller.set_energy_saving_override()
                return jsonify({
                    "status": "ok",
                    "message": "Energy saving override activated",
                    "override_duration_hours": controller.config.get("energy_saving_override_duration", 3600) / 3600
                })
            else:
                return jsonify({"error": "Only override action supported"}), 400
    
    @app.route('/api/thermal-data', methods=['GET'])
    def api_thermal_data():
        """Get thermal analysis data"""
        if controller and controller.thermal_analysis:
            thermal_data = controller.thermal_analysis.get_thermal_data()
            return jsonify({
                "thermal_data": thermal_data,
                "energy_saving_active": controller.energy_saving_active,
                "timestamp": datetime.now().isoformat()
            })
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
        logger.info(f"Starting web server on {WEB_HOST}:{WEB_PORT} (Pi Zero 2W optimized)")
        try:
            # Lightweight config for Pi Zero 2W
            from werkzeug.serving import make_server
            server = make_server(
                WEB_HOST, 
                WEB_PORT, 
                app, 
                threaded=False,  # Reduced threading for Pi Zero 2W
                processes=1     # Single process for Pi Zero 2W
            )
            server.socket.setsockopt(1, 15, 1)  # SO_REUSEADDR
            logger.info(f"Web server initialized on {WEB_HOST}:{WEB_PORT} (lightweight mode)")
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
