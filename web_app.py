#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Web interface for solar charge switch controller.

Provides REST API and web UI for:
- Viewing current status and logs
- Controlling parameters
- Manual socket control
"""

import json
import csv
import os
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_from_directory
from pathlib import Path

# Import config functions from main module
from solar_charge_switch import (
    get_config, save_config, update_config, load_config,
    get_solaredge_power, get_hue_state, set_hue_state,
    calculate_thresholds, cleanup_old_logs
)
import requests

app = Flask(__name__)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_log_entries(limit=100):
    """Get recent log entries from CSV file."""
    config = get_config()
    csv_file = config["logging"]["csv_log_file"]
    
    if not os.path.exists(csv_file):
        return []
    
    try:
        entries = []
        with open(csv_file, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            for row in rows[-limit:]:
                entries.append({
                    "timestamp": row.get("timestamp", ""),
                    "power_w": float(row.get("power_w", 0)) if row.get("power_w") else 0,
                    "avg_w": float(row.get("avg_w", 0)) if row.get("avg_w") else 0,
                    "median_w": float(row.get("median_w", 0)) if row.get("median_w") else 0,
                    "socket_on": row.get("socket_on", "False").lower() == "true",
                    "auto_mode": row.get("auto_mode", "True").lower() == "true" if "auto_mode" in row else True
                })
        return entries
    except Exception as e:
        print(f"Error reading logs: {e}")
        return []


# ============================================================
# API ROUTES
# ============================================================

@app.route("/")
def index():
    """Serve main web interface."""
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """Get current system status."""
    try:
        config = get_config()
        
        # Get current power reading
        with requests.Session() as session:
            power, power_ts = get_solaredge_power(session)
            socket_on = get_hue_state(session)
        
        power_threshold_on, power_threshold_off = calculate_thresholds()
        
        return jsonify({
            "success": True,
            "status": {
                "power_w": power,
                "power_timestamp": power_ts,
                "socket_on": socket_on if socket_on is not None else False,
                "auto_mode": config["control"]["auto_mode"],
                "manual_socket_state": config["control"].get("manual_socket_state"),
                "power_threshold_on_w": power_threshold_on,
                "power_threshold_off_w": power_threshold_off,
                "is_night": False,  # Could be calculated if needed
                "config": {
                    "electrical": config["electrical"],
                    "sampling": config["sampling"],
                    "night_mode": config["night_mode"],
                    "logging": config["logging"]
                }
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/config", methods=["GET"])
def api_get_config():
    """Get current configuration."""
    try:
        return jsonify({
            "success": True,
            "config": get_config()
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/config", methods=["POST"])
def api_update_config():
    """Update configuration."""
    try:
        data = request.get_json()
        if not data or "updates" not in data:
            return jsonify({"success": False, "error": "Missing 'updates' in request body"}), 400
        
        # Update each key in the updates dict
        success = True
        for key, value in data["updates"].items():
            if not update_config({key: value}):
                success = False
        
        if success:
            return jsonify({"success": True, "config": get_config()})
        else:
            return jsonify({"success": False, "error": "Failed to update some config values"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/socket", methods=["POST"])
def api_control_socket():
    """Manually control socket (sets manual mode)."""
    try:
        data = request.get_json()
        if "state" not in data:
            return jsonify({"success": False, "error": "Missing 'state' in request body"}), 400
        
        state = bool(data["state"])
        
        # Set socket state
        with requests.Session() as session:
            if set_hue_state(session, state):
                # Update config to reflect manual control
                update_config({
                    "control.manual_socket_state": state,
                    "control.auto_mode": False
                })
                return jsonify({"success": True, "socket_on": state})
            else:
                return jsonify({"success": False, "error": "Failed to set socket state"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/auto_mode", methods=["POST"])
def api_auto_mode():
    """Enable or disable auto mode."""
    try:
        data = request.get_json()
        if "enabled" not in data:
            return jsonify({"success": False, "error": "Missing 'enabled' in request body"}), 400
        
        enabled = bool(data["enabled"])
        updates = {"control.auto_mode": enabled}
        
        if not enabled:
            # When disabling auto mode, preserve current socket state
            with requests.Session() as session:
                current_state = get_hue_state(session)
                if current_state is not None:
                    updates["control.manual_socket_state"] = current_state
        
        if update_config(updates):
            return jsonify({"success": True, "auto_mode": enabled})
        else:
            return jsonify({"success": False, "error": "Failed to update auto mode"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/logs")
def api_logs():
    """Get recent log entries."""
    try:
        limit = request.args.get("limit", 100, type=int)
        entries = get_log_entries(limit=limit)
        return jsonify({
            "success": True,
            "logs": entries,
            "count": len(entries)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/logs/cleanup", methods=["POST"])
def api_cleanup_logs():
    """Manually trigger log cleanup."""
    try:
        removed_count = cleanup_old_logs()
        return jsonify({
            "success": True,
            "removed_count": removed_count,
            "message": f"Cleaned up {removed_count} old log entries"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    # Load config on startup
    load_config()
    
    # Run Flask app
    # Use 0.0.0.0 to allow access from other devices on the network
    # Use port 5050 (or specify via environment variable)
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)

