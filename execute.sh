#!/bin/bash
# Run the Pi Thermostat Controller

cd "$(dirname "$0")"

# Optional: activate virtual environment if it exists
if [ -f ~/luma-project/env/bin/activate ]; then
    source ~/luma-project/env/bin/activate
fi

# Run the thermostat controller
python3 ./thermostat.py
