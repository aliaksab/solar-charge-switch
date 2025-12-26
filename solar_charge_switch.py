#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Solar-powered smart socket controller.

Features:
- Reads current solar power from SolarEdge Monitoring API
- Calculates rolling statistics to avoid cloud spikes
- Automatically turns a smart socket ON/OFF via Philips Hue v2 API
- CSV logging for later analysis
- Night mode (no switching at night)
- Automatic power threshold calculation from voltage & current
- Manual control mode support
"""

import time
import json
import csv
import logging
import signal
import sys
import os
import threading
from collections import deque
from statistics import mean, median
from datetime import datetime, time as dtime
from typing import Optional, Tuple, Dict, Any
from pathlib import Path

import requests


# ============================================================
# CONFIGURATION MANAGEMENT
# ============================================================

CONFIG_FILE = "config.json"
_config = None
_config_lock = threading.Lock()
_running = True

def load_config() -> Dict[str, Any]:
    """Load configuration from JSON file."""
    global _config
    try:
        with open(CONFIG_FILE, "r") as f:
            _config = json.load(f)
        return _config
    except FileNotFoundError:
        logging.error(f"Config file {CONFIG_FILE} not found!")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in config file: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error loading config: {e}")
        sys.exit(1)

def get_config() -> Dict[str, Any]:
    """Get current configuration (thread-safe)."""
    global _config
    with _config_lock:
        if _config is None:
            _config = load_config()
        return _config.copy()

def save_config(new_config: Dict[str, Any]) -> bool:
    """Save configuration to file (thread-safe)."""
    global _config
    try:
        with _config_lock:
            # Create backup
            if os.path.exists(CONFIG_FILE):
                backup_file = f"{CONFIG_FILE}.backup"
                with open(CONFIG_FILE, "r") as src, open(backup_file, "w") as dst:
                    dst.write(src.read())
            
            with open(CONFIG_FILE, "w") as f:
                json.dump(new_config, f, indent=2)
            _config = new_config
        return True
    except Exception as e:
        logging.error(f"Error saving config: {e}")
        return False

def update_config(updates: Dict[str, Any]) -> bool:
    """Update specific configuration keys."""
    config = get_config()
    for key, value in updates.items():
        keys = key.split(".")
        d = config
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value
    return save_config(config)


# ============================================================
# UTILITIES
# ============================================================

def setup_logging() -> None:
    """Setup logging based on config."""
    config = get_config()
    log_level = getattr(logging, config["logging"]["log_level"], logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

def is_night(now: datetime) -> bool:
    """Return True if current time is inside the night window."""
    config = get_config()
    night_config = config["night_mode"]
    if not night_config["enabled"]:
        return False
    
    start_str = night_config["start"]
    end_str = night_config["end"]
    start_time = dtime(*map(int, start_str.split(":")))
    end_time = dtime(*map(int, end_str.split(":")))
    
    if start_time < end_time:
        return start_time <= now.time() < end_time
    return now.time() >= start_time or now.time() < end_time

def hue_headers() -> dict:
    """Get headers for Hue API requests."""
    config = get_config()
    return {
        "hue-application-key": config["hue"]["app_key"],
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def calculate_thresholds() -> Tuple[int, int]:
    """Calculate ON and OFF power thresholds."""
    config = get_config()
    elec = config["electrical"]
    on_threshold = int(elec["grid_voltage_v"] * elec["max_current_a"] * elec["safety_margin"])
    off_threshold = int(on_threshold * (1 - elec["hysteresis"]))
    return on_threshold, off_threshold


# ============================================================
# API FUNCTIONS
# ============================================================

def get_solaredge_power(session: requests.Session) -> Tuple[Optional[float], Optional[str]]:
    """Read current power (W) from SolarEdge."""
    config = get_config()
    try:
        r = session.get(
            config["solaredge"]["url"],
            params={"api_key": config["solaredge"]["api_key"]},
            timeout=config["solaredge"]["timeout_s"],
        )
        r.raise_for_status()
        data = r.json()
        overview = data.get("overview", {})
        power = overview.get("currentPower", {}).get("power")
        ts = overview.get("lastUpdateTime")
        return float(power), ts
    except Exception as e:
        logging.warning("SolarEdge read failed: %s", e)
        return None, None

def get_hue_state(session: requests.Session) -> Optional[bool]:
    """Read current ON/OFF state from Hue."""
    config = get_config()
    try:
        r = session.get(
            config["hue"]["url"],
            headers=hue_headers(),
            timeout=config["hue"]["timeout_s"],
            verify=config["hue"]["verify_tls"],
        )
        r.raise_for_status()
        data = r.json()
        obj = data.get("data", [{}])[0]
        return obj.get("on", {}).get("on")
    except Exception as e:
        logging.warning("Hue state read failed: %s", e)
        return None

def set_hue_state(session: requests.Session, state: bool) -> bool:
    """Set ON/OFF state via Hue."""
    config = get_config()
    try:
        r = session.put(
            config["hue"]["url"],
            headers=hue_headers(),
            data=json.dumps({"on": {"on": state}}),
            timeout=config["hue"]["timeout_s"],
            verify=config["hue"]["verify_tls"],
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logging.error("Hue switch failed: %s", e)
        return False


# ============================================================
# CSV LOGGING
# ============================================================

def init_csv():
    """Initialize CSV log file."""
    config = get_config()
    csv_file = config["logging"]["csv_log_file"]
    try:
        if not os.path.exists(csv_file):
            with open(csv_file, "x", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp",
                    "power_w",
                    "avg_w",
                    "median_w",
                    "socket_on",
                    "auto_mode"
                ])
    except Exception as e:
        logging.error(f"Error initializing CSV: {e}")

def log_csv(ts, power, avg, med, state, auto_mode):
    """Log data to CSV file."""
    config = get_config()
    csv_file = config["logging"]["csv_log_file"]
    try:
        with open(csv_file, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([ts, power, avg, med, state, auto_mode])
    except Exception as e:
        logging.error(f"Error writing to CSV: {e}")


# ============================================================
# SIGNAL HANDLERS
# ============================================================

def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    global _running
    logging.info("Received shutdown signal, shutting down gracefully...")
    _running = False


# ============================================================
# MAIN LOOP
# ============================================================

def main():
    """Main control loop."""
    global _running
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Load config and setup logging
    load_config()
    setup_logging()
    init_csv()

    config = get_config()
    power_threshold_on, power_threshold_off = calculate_thresholds()
    
    logging.info("Calculated ON threshold: %d W", power_threshold_on)
    logging.info("Calculated OFF threshold: %d W", power_threshold_off)
    logging.info("Auto mode: %s", config["control"]["auto_mode"])

    buffer_size = config["sampling"]["window_s"] // config["sampling"]["sample_interval_s"]
    power_buffer = deque(maxlen=buffer_size)

    stable_on_since = None
    stable_off_since = None
    last_switch_time = None

    with requests.Session() as se, requests.Session() as hue:
        socket_on = get_hue_state(hue) or False
        logging.info("Initial socket state: %s", "ON" if socket_on else "OFF")

        while _running:
            now = datetime.now()
            config = get_config()
            
            # Recalculate thresholds in case config changed
            power_threshold_on, power_threshold_off = calculate_thresholds()
            auto_mode = config["control"]["auto_mode"]
            manual_state = config["control"].get("manual_socket_state")

            # Handle manual control override
            if not auto_mode and manual_state is not None:
                if socket_on != manual_state:
                    logging.info("Manual control: setting socket to %s", "ON" if manual_state else "OFF")
                    if set_hue_state(hue, manual_state):
                        socket_on = manual_state
                        last_switch_time = time.time()
                time.sleep(config["sampling"]["sample_interval_s"])
                continue

            # Read solar power
            power, update_ts = get_solaredge_power(se)
            if power is None:
                time.sleep(config["sampling"]["sample_interval_s"])
                continue

            power_buffer.append(power)
            avg_w = mean(power_buffer) if len(power_buffer) > 0 else power
            med_w = median(power_buffer) if len(power_buffer) > 0 else power

            log_csv(now.isoformat(), power, avg_w, med_w, socket_on, auto_mode)

            logging.info(
                "Power=%.0fW | avg=%.0fW | socket=%s | auto=%s",
                power, avg_w, "ON" if socket_on else "OFF", "ON" if auto_mode else "OFF"
            )

            # Night mode handling (only in auto mode)
            if auto_mode and is_night(now):
                if socket_on:
                    logging.info("Night mode → turning OFF")
                    if set_hue_state(hue, False):
                        socket_on = False
                        last_switch_time = time.time()
                time.sleep(config["sampling"]["sample_interval_s"])
                continue

            # Skip automatic control if not in auto mode
            if not auto_mode:
                time.sleep(config["sampling"]["sample_interval_s"])
                continue

            # Automatic control logic
            if not socket_on:
                if avg_w >= power_threshold_on:
                    stable_on_since = stable_on_since or time.time()
                    if time.time() - stable_on_since >= config["sampling"]["require_stable_on_s"]:
                        logging.info("Turning socket ON")
                        if set_hue_state(hue, True):
                            socket_on = True
                            last_switch_time = time.time()
                        stable_on_since = None
                else:
                    stable_on_since = None

            else:
                can_turn_off = (
                    last_switch_time is None or
                    time.time() - last_switch_time >= config["sampling"]["min_on_time_s"]
                )
                if avg_w <= power_threshold_off and can_turn_off:
                    stable_off_since = stable_off_since or time.time()
                    if time.time() - stable_off_since >= config["sampling"]["require_stable_off_s"]:
                        logging.info("Turning socket OFF")
                        if set_hue_state(hue, False):
                            socket_on = False
                            last_switch_time = time.time()
                        stable_off_since = None
                else:
                    stable_off_since = None

            time.sleep(config["sampling"]["sample_interval_s"])

    logging.info("Program terminated")


if __name__ == "__main__":
    main()
