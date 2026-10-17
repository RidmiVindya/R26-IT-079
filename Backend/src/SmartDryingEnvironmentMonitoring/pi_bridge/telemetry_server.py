#!/usr/bin/env python3
"""
Smart Karawala - Enhanced Raspberry Pi Telemetry Server & Data Bridge
---------------------------------------------------------------------
Features:
1. Reads and parses Arduino Nano serial data (/dev/ttyUSB0, 9600 baud)
   Supports format: DATA:{"sht_temp":...,"humidity":...,"ds_temp":...,"gas":...,"load_cell":...,"heater":...,"light":...,"fan":...}
2. Relay Duty Cycle Protection:
   Heater runs 60s ON -> 10s REST -> 60s ON -> 10s REST... to safeguard relay contacts & element.
3. Edge REST API on Port 8081 (fully compatible with dryFish_verification_station):
   - GET  /api/telemetry
   - GET  /api/control?action=<heater_on|heater_off|fan_on|fan_off|light_on|light_off|tare>
   - POST /api/control (JSON: {"command": "heater_on"})
4. Automatic Central Backend Data Bridge:
   Background thread continuously pushes live telemetry to the central backend
   (SmartDryingEnvironmentMonitoring at http://<BACKEND_HOST>:8002/api/iot/bridge/telemetry)
   and synchronizes commanded actuator states!
"""

import http.server
import socketserver
import json
import time
import threading
import serial
import os
import urllib.request
import urllib.error
from urllib.parse import parse_qs, urlparse

# Configuration
PORT = int(os.getenv("PORT", 8081))
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
BAUD_RATE = int(os.getenv("BAUD_RATE", 9600))

# Central Backend Bridge Configuration
# Defaults to your laptop IP (172.20.10.3) running backend on port 8002
BACKEND_URL = os.getenv("BACKEND_URL", "http://172.20.10.3:8002").rstrip("/")
ENABLE_BACKEND_PUSH = os.getenv("ENABLE_BACKEND_PUSH", "true").lower() in ("1", "true", "yes")
PUSH_INTERVAL_SECONDS = float(os.getenv("PUSH_INTERVAL_SECONDS", 2.0))

# Relay Duty Cycle Settings (1 min ON, 10 sec REST)
DUTY_CYCLE_ON_SECONDS = float(os.getenv("HEATER_DUTY_CYCLE_ON_SECONDS", 60.0))
DUTY_CYCLE_REST_SECONDS = float(os.getenv("HEATER_DUTY_CYCLE_REST_SECONDS", 10.0))

# Telemetry state
nano_data = {
    'sht_temp': 0.0,
    'humidity': 0.0,
    'ds_temp': 0.0,
    'gas': 0,
    'load_cell': 0,
    'heater': False,
    'light': False,
    'fan': False,
    'last_update': 0,
    'connected': False,
    'duty_cycle': {
        'phase': 'IDLE',
        'phase_elapsed_seconds': 0.0,
        'phase_remaining_seconds': 0.0,
        'on_duration_seconds': DUTY_CYCLE_ON_SECONDS,
        'rest_duration_seconds': DUTY_CYCLE_REST_SECONDS,
        'heater_requested': False,
        'physical_relay_on': False,
    }
}

ser_lock = threading.Lock()
commanded_light = False
commanded_fan = False
ser = None


# ============================================================================
# Relay Duty Cycle Manager (60s ON / 10s REST)
# ============================================================================
class RelayDutyCycleManager:
    def __init__(self):
        self.heater_requested = False
        self.physical_relay_state = False
        self.current_phase = "IDLE"  # "HEATING_PULSE", "RESTING", "IDLE"
        self.phase_start_time = time.monotonic()
        self.lock = threading.Lock()

    def set_heater_request(self, requested: bool):
        with self.lock:
            if self.heater_requested == requested:
                return
            self.heater_requested = requested
            if requested:
                # Start 60s heating pulse
                self.current_phase = "HEATING_PULSE"
                self.phase_start_time = time.monotonic()
                self._apply_relay(True)
                print(f"[RELAY CYCLE] Heater ON requested -> Started {DUTY_CYCLE_ON_SECONDS}s heating pulse")
            else:
                # Immediately turn off
                self.current_phase = "IDLE"
                self._apply_relay(False)
                print("[RELAY CYCLE] Heater OFF requested -> Relay OFF (Idle)")

    def _apply_relay(self, on: bool):
        self.physical_relay_state = on
        send_nano_command("1" if on else "0")

    def tick(self):
        with self.lock:
            if not self.heater_requested:
                if self.physical_relay_state:
                    self._apply_relay(False)
                self.current_phase = "IDLE"
                return

            now = time.monotonic()
            elapsed = now - self.phase_start_time

            if self.current_phase == "HEATING_PULSE":
                if elapsed >= DUTY_CYCLE_ON_SECONDS:
                    # Switch to REST phase
                    self.current_phase = "RESTING"
                    self.phase_start_time = now
                    self._apply_relay(False)
                    print(f"[RELAY CYCLE] {DUTY_CYCLE_ON_SECONDS}s pulse completed -> Resting {DUTY_CYCLE_REST_SECONDS}s to protect relay")
            elif self.current_phase == "RESTING":
                if elapsed >= DUTY_CYCLE_REST_SECONDS:
                    # Resume HEATING_PULSE
                    self.current_phase = "HEATING_PULSE"
                    self.phase_start_time = now
                    self._apply_relay(True)
                    print(f"[RELAY CYCLE] {DUTY_CYCLE_REST_SECONDS}s rest completed -> Resuming {DUTY_CYCLE_ON_SECONDS}s heating pulse")

    def get_status(self) -> dict:
        with self.lock:
            now = time.monotonic()
            elapsed = max(0.0, now - self.phase_start_time) if self.current_phase != "IDLE" else 0.0
            total = DUTY_CYCLE_ON_SECONDS if self.current_phase == "HEATING_PULSE" else (
                DUTY_CYCLE_REST_SECONDS if self.current_phase == "RESTING" else 0.0
            )
            remaining = max(0.0, total - elapsed) if total > 0 else 0.0
            return {
                "phase": self.current_phase,
                "phase_elapsed_seconds": round(elapsed, 1),
                "phase_remaining_seconds": round(remaining, 1),
                "on_duration_seconds": DUTY_CYCLE_ON_SECONDS,
                "rest_duration_seconds": DUTY_CYCLE_REST_SECONDS,
                "heater_requested": self.heater_requested,
                "physical_relay_on": self.physical_relay_state,
            }


duty_manager = RelayDutyCycleManager()


# ============================================================================
# Serial Reader Loop
# ============================================================================
def serial_reader_thread():
    global ser, nano_data
    while True:
        try:
            duty_manager.tick()

            if ser is None or not ser.is_open:
                try:
                    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
                    time.sleep(2)  # Arduino settling time
                    ser.reset_input_buffer()
                    nano_data['connected'] = True
                    print(f"Connected to Arduino Nano on {SERIAL_PORT}")
                except Exception as e:
                    nano_data['connected'] = False
                    time.sleep(3)
                    continue

            line = ''
            with ser_lock:
                if ser.in_waiting:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()

            if not line:
                time.sleep(0.05)
                continue

            nano_data['last_update'] = time.time()

            # Primary JSON protocol: DATA:{"sht_temp":...}
            if line.startswith('DATA:{'):
                try:
                    json_str = line[5:]
                    parsed = json.loads(json_str)
                    nano_data['sht_temp'] = float(parsed.get('sht_temp', 0))
                    nano_data['humidity'] = float(parsed.get('humidity', 0))
                    nano_data['ds_temp'] = float(parsed.get('ds_temp', 0))
                    nano_data['gas'] = int(parsed.get('gas', 0))
                    nano_data['load_cell'] = int(parsed.get('load_cell', 0))
                    # Use authoritative commanded state for actuators (with Arduino feedback as fallback)
                    nano_data['light'] = commanded_light if commanded_light is not None else bool(parsed.get('light', 0))
                    nano_data['fan'] = commanded_fan if commanded_fan is not None else bool(parsed.get('fan', 0))
                    # The physical relay is driven by duty cycle manager
                    duty_info = duty_manager.get_status()
                    nano_data['heater'] = duty_info['heater_requested']
                    nano_data['duty_cycle'] = duty_info
                    continue
                except Exception:
                    pass

            # Legacy plaintext fallback parser
            if 'SHT Temp:' in line:
                try: nano_data['sht_temp'] = float(line.split(':')[1].replace('C','').strip())
                except: pass
            elif 'Humidity:' in line:
                try: nano_data['humidity'] = float(line.split(':')[1].replace('%','').strip())
                except: pass
            elif 'DS Temp:' in line:
                try: nano_data['ds_temp'] = float(line.split(':')[1].replace('C','').strip())
                except: pass
            elif 'Gas:' in line:
                try: nano_data['gas'] = int(line.split(':')[1].strip())
                except: pass
            elif 'Load Cell Raw:' in line:
                try: nano_data['load_cell'] = int(line.split(':')[1].strip())
                except: pass
            elif 'Heater/Dry Air:' in line:
                pass  # Managed by duty manager
            elif 'Light:' in line:
                nano_data['light'] = 'ON' in line.upper()
            elif 'Fan:' in line:
                nano_data['fan'] = 'ON' in line.upper()

        except Exception as e:
            print('Serial Reader Exception:', e)
            nano_data['connected'] = False
            if ser:
                try: ser.close()
                except: pass
                ser = None
            time.sleep(2)


def send_nano_command(cmd_char):
    global ser
    with ser_lock:
        if ser and ser.is_open:
            try:
                ser.write(cmd_char.encode('utf-8'))
                ser.flush()
                return True
            except Exception as e:
                print('Failed to send command:', e)
    return False


# ============================================================================
# Central Backend Auto-Pusher Thread
# ============================================================================
def backend_pusher_thread():
    """Continuously push live readings to backend & pull actuator commands."""
    if not ENABLE_BACKEND_PUSH:
        print("[BACKEND BRIDGE] Push to backend is disabled")
        return

    bridge_endpoint = f"{BACKEND_URL}/api/iot/bridge/telemetry"
    print(f"[BACKEND BRIDGE] Starting auto-pusher -> {bridge_endpoint}")

    while True:
        time.sleep(PUSH_INTERVAL_SECONDS)
        duty_status = duty_manager.get_status()

        # Build payload for central backend
        payload = {
            "device_id": "RPI-OVEN-001",
            "temperature": nano_data['sht_temp'],
            "humidity": nano_data['humidity'],
            "ds_temperature": nano_data['ds_temp'],
            "gas": nano_data['gas'],
            "raw_weight": nano_data['load_cell'],
            "heater": duty_status['heater_requested'],
            "relay_physical_state": duty_status['physical_relay_on'],
            "relay_duty_cycle": duty_status,
            "fan": nano_data['fan'],
            "light": nano_data['light'],
        }

        try:
            req_data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                bridge_endpoint,
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status == 200:
                    resp_json = json.loads(resp.read().decode('utf-8'))
                    session_active = resp_json.get("session_active", False)
                    commands = resp_json.get("commands", {})
                    # Synchronize actuator commands from backend only when session is actively running
                    if session_active:
                        if "heater" in commands:
                            duty_manager.set_heater_request(bool(commands["heater"]))
                        if "fan" in commands:
                            f_on = bool(commands["fan"])
                            if f_on != nano_data['fan']:
                                nano_data['fan'] = f_on
                                send_nano_command("f" if f_on else "e")
                        if "light" in commands:
                            l_on = bool(commands["light"])
                            if l_on != nano_data['light']:
                                nano_data['light'] = l_on
                                send_nano_command("l" if l_on else "k")
                    else:
                        # Session is idle/paused - heater must remain safely OFF
                        duty_manager.set_heater_request(False)
                        # CRITICAL: Preserve chamber light for live verification camera inspection
                        if commands.get("light") is True and not nano_data['light']:
                            nano_data['light'] = True
                            send_nano_command("l")
        except Exception:
            # Backend may be starting or offline; continue edge operation silently
            pass


# ============================================================================
# HTTP Request Handlers (Port 8081)
# ============================================================================
class TelemetryHandler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path.startswith('/api/telemetry') or self.path == '/':
            temp = nano_data['sht_temp']
            hum = nano_data['humidity']
            heat_index = round(temp + (0.05 * hum), 1)

            if hum < 50:
                drying_state = 'OPTIMAL_RAPID_DRYING'
                mold_risk = 'LOW'
            elif hum <= 65:
                drying_state = 'GOOD_STEADY_DRYING'
                mold_risk = 'LOW'
            else:
                drying_state = 'HIGH_HUMIDITY_WARNING'
                mold_risk = 'MODERATE'

            duty_info = duty_manager.get_status()

            data = {
                'success': True,
                'data': {
                    'temperature_c': temp,
                    'temperature_f': round((temp * 9/5) + 32, 1),
                    'humidity_percent': hum,
                    'ds_temp_c': nano_data['ds_temp'],
                    'gas_raw': nano_data['gas'],
                    'load_cell_raw': nano_data['load_cell'],
                    'heater_state': duty_info['heater_requested'],
                    'heater_physical_relay': duty_info['physical_relay_on'],
                    'duty_cycle': duty_info,
                    'light_state': nano_data['light'],
                    'fan_state': nano_data['fan'],
                    'heat_index_c': heat_index,
                    'drying_condition': drying_state,
                    'mold_risk': mold_risk,
                    'sensor_source': 'ARDUINO_NANO_USB_SERIAL',
                    'nano_connected': nano_data['connected'],
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                }
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))

        elif self.path.startswith('/api/control'):
            query = parse_qs(urlparse(self.path).query)
            cmd = query.get('cmd', [''])[0]
            action = query.get('action', [''])[0]
            action_name = action or cmd

            ok = self._execute_command(action_name)
            res = {'success': ok, 'command': action_name, 'duty_cycle': duty_manager.get_status()}

            self.send_response(200 if res['success'] else 400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ''
        try:
            payload = json.loads(post_data) if post_data else {}
        except Exception:
            payload = {}

        if self.path.startswith('/api/actuators'):
            global commanded_light, commanded_fan
            if "heater" in payload:
                duty_manager.set_heater_request(bool(payload["heater"]))
            if "light" in payload:
                l_val = bool(payload["light"])
                commanded_light = l_val
                nano_data['light'] = l_val
                send_nano_command('l' if l_val else 'k')
            if "fan" in payload:
                f_val = bool(payload["fan"])
                commanded_fan = f_val
                nano_data['fan'] = f_val
                send_nano_command('f' if f_val else 'e')

            res = {'success': True, 'actuators': payload, 'duty_cycle': duty_manager.get_status()}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))

        elif self.path.startswith('/api/command'):
            cmd = payload.get('command') or payload.get('action') or ''
            ok = self._execute_command(cmd)
            res = {'success': ok, 'command': cmd, 'duty_cycle': duty_manager.get_status()}
            self.send_response(200 if res['success'] else 400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))

        elif self.path.startswith('/api/tare'):
            ok = send_nano_command('t')
            res = {'success': ok, 'message': 'Scale tared'}
            self.send_response(200 if ok else 400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))

        elif self.path.startswith('/api/control'):
            cmd = payload.get('command') or payload.get('action') or ''
            ok = self._execute_command(cmd)
            res = {'success': ok, 'command': cmd, 'duty_cycle': duty_manager.get_status()}

            self.send_response(200 if res['success'] else 400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def _execute_command(self, action_name: str) -> bool:
        global commanded_light, commanded_fan
        if action_name in ('heater_on', '1'):
            duty_manager.set_heater_request(True)
            return True
        elif action_name in ('heater_off', '0'):
            duty_manager.set_heater_request(False)
            return True
        elif action_name in ('light_on', 'l', 'L'):
            commanded_light = True
            nano_data['light'] = True
            return send_nano_command('l')
        elif action_name in ('light_off', 'k', 'K'):
            commanded_light = False
            nano_data['light'] = False
            return send_nano_command('k')
        elif action_name in ('fan_on', 'f', 'F'):
            commanded_fan = True
            nano_data['fan'] = True
            return send_nano_command('f')
        elif action_name in ('fan_off', 'e', 'E'):
            commanded_fan = False
            nano_data['fan'] = False
            return send_nano_command('e')
        elif action_name in ('tare', 't', 'T'):
            return send_nano_command('t')
        return False


if __name__ == '__main__':
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(('0.0.0.0', PORT), TelemetryHandler) as httpd:
        print(f'Enhanced Telemetry & Relay Duty Cycle Server running on port {PORT}')
        print(f'Relay Duty Cycle: {DUTY_CYCLE_ON_SECONDS}s ON / {DUTY_CYCLE_REST_SECONDS}s REST')


        # Thread 1: Serial Reader
        t_serial = threading.Thread(target=serial_reader_thread, daemon=True)
        t_serial.start()

        # Thread 2: Backend Auto-Bridge Pusher
        t_bridge = threading.Thread(target=backend_pusher_thread, daemon=True)
        t_bridge.start()

        httpd.serve_forever()
