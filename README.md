# Solar Charge Switch Controller

A Raspberry Pi-based system that automatically controls a smart socket (via Philips Hue) to charge your EV only when there's sufficient solar power available.

## Features

- **Automatic Control**: Monitors solar power output and automatically turns the socket ON/OFF based on calculated thresholds
- **Manual Control**: Disable automatic mode and manually control the socket
- **Web Interface**: Modern web UI for monitoring and controlling all parameters
- **Configuration Management**: JSON-based configuration file with runtime updates
- **CSV Logging**: Detailed logging of power readings and socket states
- **Night Mode**: Prevents switching during configured night hours
- **Hysteresis**: Prevents rapid toggling with configurable thresholds
- **Graceful Shutdown**: Handles SIGINT/SIGTERM signals properly

## Hardware Requirements

- Raspberry Pi (any model with network connectivity)
- Philips Hue Bridge and compatible smart socket/plug
- SolarEdge monitoring system with API access

## Installation

1. Clone or download this repository to your Raspberry Pi

2. Install Python dependencies:
```bash
pip3 install -r requirements.txt
```

3. Configure the system by editing `config.json`:
   - Update SolarEdge API credentials and site ID
   - Update Philips Hue Bridge URL and app key
   - Adjust electrical parameters (voltage, current, safety margins)
   - Configure sampling intervals and thresholds
   - Set night mode hours

## Configuration

The `config.json` file contains all system parameters:

- **electrical**: Grid voltage, max current, safety margins, hysteresis
- **solaredge**: API URL, API key, timeout settings
- **hue**: Bridge URL, app key, timeout, TLS settings
- **sampling**: Intervals, window sizes, stability requirements
- **night_mode**: Enable/disable, start/end times
- **control**: Auto mode flag, manual socket state
- **logging**: Log file path, log level

## Usage

### Running the Main Controller

Start the main control loop:
```bash
python3 solar_charge_switch.py
```

The controller will:
- Continuously monitor solar power output
- Calculate rolling averages to smooth out cloud fluctuations
- Automatically control the socket based on thresholds
- Log all readings to CSV

### Running the Web Interface

Start the web server:
```bash
python3 web_app.py
```

Then open your browser and navigate to:
```
http://<raspberry-pi-ip>:5050
```

The web interface provides:
- Real-time status display (power, socket state, thresholds)
- Manual socket control
- Auto mode toggle
- Configuration parameter editing
- Recent log viewing

### Auto-Start on Boot (systemd)

Create a systemd service file `/etc/systemd/system/solar-charge-switch.service`:

```ini
[Unit]
Description=Solar Charge Switch Controller
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/path/to/solar_charge_switch
ExecStart=/usr/bin/python3 /path/to/solar_charge_switch/solar_charge_switch.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable solar-charge-switch.service
sudo systemctl start solar-charge-switch.service
```

Similarly for the web app, create `/etc/systemd/system/solar-charge-web.service`:

```ini
[Unit]
Description=Solar Charge Switch Web Interface
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/path/to/solar_charge_switch
ExecStart=/usr/bin/python3 /path/to/solar_charge_switch/web_app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Manual Control

To manually control the socket without automatic switching:

1. Via Web Interface:
   - Toggle "Auto Mode" to OFF
   - Use "Turn ON" / "Turn OFF" buttons

2. Via Configuration:
   - Set `control.auto_mode` to `false` in `config.json`
   - Set `control.manual_socket_state` to `true` (ON) or `false` (OFF)

## API Endpoints

The web app provides REST API endpoints:

- `GET /api/status` - Get current system status
- `GET /api/config` - Get current configuration
- `POST /api/config` - Update configuration (body: `{"updates": {"key": value}}`)
- `POST /api/socket` - Manually set socket state (body: `{"state": true/false}`)
- `POST /api/auto_mode` - Enable/disable auto mode (body: `{"enabled": true/false}`)
- `GET /api/logs` - Get recent log entries (query: `?limit=100`)

## Logging

All readings are logged to `solar_charge_log.csv` with the following columns:
- timestamp: ISO format timestamp
- power_w: Current solar power (Watts)
- avg_w: Rolling average power (Watts)
- median_w: Rolling median power (Watts)
- socket_on: Socket state (true/false)
- auto_mode: Auto mode state (true/false)

## Safety Features

- **Safety Margin**: 8% default margin above calculated power requirement
- **Hysteresis**: 10% difference between ON and OFF thresholds prevents rapid toggling
- **Minimum ON Time**: Socket must stay ON for at least 5 minutes before it can be turned off
- **Stability Requirements**: Power must be above/below threshold for specified duration before switching

## Troubleshooting

- **Socket not responding**: Check Hue Bridge URL and app key in config.json
- **Solar power not updating**: Verify SolarEdge API key and site ID
- **Web interface not accessible**: Check firewall settings and ensure port 5050 is open
- **Configuration not saving**: Check file permissions on config.json

## License

This project is provided as-is for personal use.

