#!/usr/bin/env python3
"""
Simple script to read AHT10 temperature and humidity sensor on I2C bus 3
"""
import time
import logging

try:
    import smbus2
except ImportError:
    print("Error: smbus2 not installed. Run: sudo apt-get install python3-smbus")
    exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# AHT10 I2C address
AHT10_ADDRESS = 0x38
I2C_BUS = 3

def read_sensor(bus):
    """Read temperature and humidity from AHT10"""
    try:
        # Trigger measurement using i2c_msg
        logger.info("Triggering measurement...")
        trigger_msg = smbus2.i2c_msg.write(AHT10_ADDRESS, [0xAC, 0x33, 0x00])
        bus.i2c_rdwr(trigger_msg)
        time.sleep(0.1)
        
        # Read 6 bytes
        read_msg = smbus2.i2c_msg.read(AHT10_ADDRESS, 6)
        bus.i2c_rdwr(read_msg)
        data = list(read_msg)
        
        logger.info(f"Raw data: {' '.join([f'0x{b:02x}' for b in data])}")
        
        # Check if busy
        if data[0] & 0x80:
            logger.warning("Sensor busy, waiting...")
            time.sleep(0.1)
            read_msg = smbus2.i2c_msg.read(AHT10_ADDRESS, 6)
            bus.i2c_rdwr(read_msg)
            data = list(read_msg)
        
        # Extract humidity (20 bits)
        humidity_raw = ((data[1] << 16) | (data[2] << 8) | data[3]) >> 4
        humidity = (humidity_raw / 1048576.0) * 100.0
        
        # Extract temperature (20 bits)
        temperature_raw = ((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5]
        temperature = (temperature_raw / 1048576.0) * 200.0 - 50.0
        
        return temperature, humidity
    
    except Exception as e:
        logger.error(f"Failed to read sensor: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def main():
    """Main function"""
    try:
        logger.info(f"Opening I2C bus {I2C_BUS}")
        bus = smbus2.SMBus(I2C_BUS)
        
        # Try reading without initialization
        logger.info("Attempting to read sensor directly (no reset/init)...")
        temperature, humidity = read_sensor(bus)
        
        if temperature is not None and humidity is not None:
            print(f"\n{'='*40}")
            print(f"Temperature: {temperature:.2f} °C")
            print(f"Humidity:    {humidity:.2f} %")
            print(f"{'='*40}\n")
            logger.info("Reading completed successfully")
        else:
            logger.error("Failed to read sensor data")
        
        bus.close()
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
