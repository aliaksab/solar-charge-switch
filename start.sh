#!/bin/bash
# Startup script for Solar Charge Switch Controller

# Check if config file exists
if [ ! -f "config.json" ]; then
    echo "Error: config.json not found!"
    echo "Please create config.json before running."
    exit 1
fi

# Check if Python dependencies are installed
python3 -c "import flask, requests" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Installing Python dependencies..."
    pip3 install -r requirements.txt
fi

echo "Starting Solar Charge Switch Controller..."
echo "Press Ctrl+C to stop"

# Run both services in background (or use systemd in production)
python3 solar_charge_switch.py &
CONTROLLER_PID=$!

sleep 2

echo "Starting Web Interface..."
python3 web_app.py &
WEB_PID=$!

echo "Controller PID: $CONTROLLER_PID"
echo "Web Interface PID: $WEB_PID"
echo "Web interface available at: http://localhost:5050"

# Wait for interrupt
trap "kill $CONTROLLER_PID $WEB_PID; exit" INT TERM

wait

