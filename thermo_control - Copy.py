#!/usr/bin/env python3
"""
Thermometer/Relay Control Script
Controls a water valve via GPIO relay
Workaround: Uses GPIO setup/cleanup cycle to control relay
"""
import RPi.GPIO as GPIO
import time
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/acohen/pi-thermo/thermo.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# GPIO Configuration
RELAY_PIN = 13

def relay_on(duration=5):
    """Turn relay ON by setting up GPIO"""
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(RELAY_PIN, GPIO.OUT)
        GPIO.output(RELAY_PIN, GPIO.LOW)
        logger.info(f"Relay ON for {duration} seconds")
        time.sleep(duration)
    except Exception as e:
        logger.error(f"Error turning relay ON: {e}")
        raise

def relay_off(duration=5):
    """Turn relay OFF by cleaning up GPIO"""
    try:
        GPIO.cleanup()
        logger.info(f"Relay OFF for {duration} seconds")
        time.sleep(duration)
    except Exception as e:
        logger.error(f"Error turning relay OFF: {e}")
        raise

def main():
    """Main control loop"""
    try:
        logger.info("Starting valve control loop (Ctrl+C to stop)")
        while True:
            relay_on(duration=5)
            relay_off(duration=5)
    
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        try:
            GPIO.cleanup()
            logger.info("Final cleanup completed - relay should be OFF")
        except Exception as e:
            logger.error(f"Error during final cleanup: {e}")

if __name__ == "__main__":
    main()
