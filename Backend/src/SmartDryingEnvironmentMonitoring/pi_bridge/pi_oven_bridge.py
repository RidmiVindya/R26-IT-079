#!/usr/bin/env python3
"""
Smart Karawala - Raspberry Pi Oven Controller & Edge Data Bridge
----------------------------------------------------------------
Roles:
1. Connects to Arduino Nano via USB Serial (/dev/ttyUSB0, /dev/ttyACM0).
2. Reads & parses sensor telemetry (temperature, humidity, weight, gas).
3. Enforces Relay Duty Cycle Protection (60s ON / 10s REST) to prevent relay welding.
4. Self-hosts a REST API & MJPEG camera stream on port 5000 (accessible on local Wi-Fi).
5. Automatically bridges telemetry to the central backend over Wi-Fi / Internet.
"""

import os
import sys
import time
import glob
import math
import logging
import threading
from typing import Optional
from datetime import datetime, timezone

import requests
import serial
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("pi_oven_bridge")

# Configuration from Environment Variables
SERIAL_PORT = os.getenv("SERIAL_PORT", "")  # Auto-detected if empty
BAUD_RATE = int(os.getenv("BAUD_RATE", 9600))
SERVER_PORT = int(os.getenv("SERVER_PORT", 5000))
BACKEND_URL = os.getenv("BACKEND_URL", "http://192.168.8.100:8002").rstrip("/")
PUSH_TO_BACKEND = os.getenv("PUSH_TO_BACKEND", "true").lower() in ("1", "true", "yes")
PUSH_INTERVAL_SECONDS = float(os.getenv("PUSH_INTERVAL_SECONDS", 2.0))

# Load cell calibration defaults
RAW_ZERO = int(os.getenv("HX711_RAW_ZERO", 78959))
COUNTS_PER_KG = float(os.getenv("HX711_COUNTS_PER_KG", 381866.0))
DEVICE_ID = os.getenv("DEVICE_ID", "RPI-OVEN-001")

# Relay Protection Duty Cycle Settings (1 min ON, 10 sec REST)
DUTY_CYCLE_ON_SECONDS = float(os.getenv("HEATER_DUTY_CYCLE_ON_SECONDS", 60.0))
DUTY_CYCLE_REST_SECONDS = float(os.getenv("HEATER_DUTY_CYCLE_REST_SECONDS", 10.0))

# Camera Device Index
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", 0))

# ============================================================================
# 1. State Management & Thread Locks
# ============================================================================
state_lock = threading.Lock()
serial_lock = threading.Lock()

arduino_serial: Optional[serial.Serial] = None
runtime_raw_zero = RAW_ZERO

latest_reading = {
    "device_id": DEVICE_ID,
    "online": False,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "temperature": 30.0,
    "humidity": 55.0,
    "ds_temperature": 30.0,
    "gas": 250,
    "raw_weight": RAW_ZERO,
    "weight": 0.0,
    "actuators": {
        "heater_commanded": False,
        "heater_physical_relay": False,
        "fan": False,
        "light": False,
        "duty_cycle": {
            "enabled": True,
            "on_seconds": DUTY_CYCLE_ON_SECONDS,
            "rest_seconds": DUTY_CYCLE_REST_SECONDS,
            "phase": "IDLE",  # "HEATING_PULSE", "RESTING", "IDLE"
            "phase_elapsed": 0.0,
            "phase_remaining": 0.0,
        }
    },
    "system": {
        "serial_connected": False,
        "port": "",
        "backend_synced": False,
        "last_sync_error": None,
        "uptime_seconds": 0
    }
}

START_TIME = time.time()


# ============================================================================
# 2. Hardware / Serial Communication
# ============================================================================
def find_arduino_port() -> str:
    if SERIAL_PORT and os.path.exists(SERIAL_PORT):
        return SERIAL_PORT
    patterns = [
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
        "/dev/cu.usbserial*",
        "/dev/cu.usbmodem*",
        "/dev/cu.wchusbserial*"
    ]
    for pat in patterns:
        ports = glob.glob(pat)
        if ports:
            return ports[0]
    return ""


def ensure_serial_connection() -> bool:
    global arduino_serial
    with serial_lock:
        if arduino_serial is not None and arduino_serial.is_open:
            return True
        port = find_arduino_port()
        if not port:
            return False
        try:
            arduino_serial = serial.Serial(
                port=port,
                baudrate=BAUD_RATE,
                timeout=1.0,
                write_timeout=1.0
            )
            time.sleep(2.0)  # Arduino auto-reset settling time
            arduino_serial.reset_input_buffer()
            logger.info(f"Connected to Arduino Nano on {port}")
            with state_lock:
                latest_reading["system"]["serial_connected"] = True
                latest_reading["system"]["port"] = port
            return True
        except Exception as exc:
            arduino_serial = None
            with state_lock:
                latest_reading["system"]["serial_connected"] = False
                latest_reading["system"]["port"] = ""
            logger.warning(f"Serial connection failed: {exc}")
            return False


def send_raw_command(char_command: str) -> bool:
    """Send single-character command to Arduino ('1','0','f','e','l','k','t')."""
    global arduino_serial
    with serial_lock:
        if arduino_serial is None or not arduino_serial.is_open:
            if not ensure_serial_connection():
                return False
        try:
            arduino_serial.write(char_command.encode("utf-8"))
            arduino_serial.flush()
            logger.debug(f"Sent byte to Arduino: {char_command}")
            return True
        except Exception as exc:
            logger.error(f"Failed to send byte '{char_command}': {exc}")
            if arduino_serial:
                try:
                    arduino_serial.close()
                except Exception:
                    pass
            arduino_serial = None
            return False


# ============================================================================
# 3. Relay Duty Cycle Protection Manager (1 min ON, 10 sec REST)
# ============================================================================
# When heater_commanded is True:
# - Turn physical relay ON for 60s
# - Turn physical relay OFF for 10s (Resting)
# - Repeat continuously until heater_commanded is False.
# If heater_commanded is False:
# - Turn physical relay OFF immediately.
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
                # Start fresh heating pulse
                self.current_phase = "HEATING_PULSE"
                self.phase_start_time = time.monotonic()
                self._apply_physical_relay(True)
                logger.info("[RELAY CYCLE] Heater ON requested -> Started 60s heating pulse")
            else:
                # Immediately turn off
                self.current_phase = "IDLE"
                self._apply_physical_relay(False)
                logger.info("[RELAY CYCLE] Heater OFF requested -> Relay OFF (Idle)")

    def _apply_physical_relay(self, on: bool):
        self.physical_relay_state = on
        send_raw_command("1" if on else "0")

    def tick(self):
        with self.lock:
            if not self.heater_requested:
                if self.physical_relay_state:
                    self._apply_physical_relay(False)
                self.current_phase = "IDLE"
                return

            now = time.monotonic()
            elapsed = now - self.phase_start_time

            if self.current_phase == "HEATING_PULSE":
                if elapsed >= DUTY_CYCLE_ON_SECONDS:
                    # Switch to REST phase
                    self.current_phase = "RESTING"
                    self.phase_start_time = now
                    self._apply_physical_relay(False)
                    logger.info(f"[RELAY CYCLE] 60s pulse complete -> Resting 10s to protect relay")
            elif self.current_phase == "RESTING":
                if elapsed >= DUTY_CYCLE_REST_SECONDS:
                    # Switch back to HEATING_PULSE
                    self.current_phase = "HEATING_PULSE"
                    self.phase_start_time = now
                    self._apply_physical_relay(True)
                    logger.info(f"[RELAY CYCLE] 10s rest complete -> Resuming 60s heating pulse")

    def get_status(self) -> dict:
        with self.lock:
            now = time.monotonic()
            elapsed = max(0.0, now - self.phase_start_time) if self.current_phase != "IDLE" else 0.0
            total_duration = DUTY_CYCLE_ON_SECONDS if self.current_phase == "HEATING_PULSE" else (
                DUTY_CYCLE_REST_SECONDS if self.current_phase == "RESTING" else 0.0
            )
            remaining = max(0.0, total_duration - elapsed) if total_duration > 0 else 0.0
            return {
                "enabled": True,
                "heater_requested": self.heater_requested,
                "physical_relay_on": self.physical_relay_state,
                "phase": self.current_phase,
                "phase_elapsed_seconds": round(elapsed, 1),
                "phase_remaining_seconds": round(remaining, 1),
                "on_duration_seconds": DUTY_CYCLE_ON_SECONDS,
                "rest_duration_seconds": DUTY_CYCLE_REST_SECONDS,
            }


duty_manager = RelayDutyCycleManager()


# ============================================================================
# 4. Background Serial Reader Thread
# ============================================================================
def raw_to_kg(raw: Optional[int]) -> Optional[float]:
    if raw is None or COUNTS_PER_KG <= 0:
        return None
    kg = (raw - runtime_raw_zero) / COUNTS_PER_KG
    if not math.isfinite(kg):
        return None
    if kg < 0:
        if kg < -0.05:
            return None
        kg = 0.0
    return round(kg, 3)


def serial_reader_loop():
    logger.info("Starting serial reader loop...")
    buffer_lines = []
    reading_block = False

    while True:
        try:
            duty_manager.tick()

            if not ensure_serial_connection():
                time.sleep(1.0)
                continue

            with serial_lock:
                if arduino_serial is None or not arduino_serial.is_open:
                    time.sleep(0.5)
                    continue
                try:
                    line = arduino_serial.readline().decode("utf-8", errors="ignore").strip()
                except Exception as exc:
                    logger.warning(f"Serial read error: {exc}")
                    line = ""

            if not line:
                time.sleep(0.05)
                continue

            if "SENSOR DATA" in line:
                reading_block = True
                buffer_lines = [line]
                continue

            if reading_block:
                buffer_lines.append(line)
                if "----" in line or "====" in line or len(buffer_lines) >= 8:
                    reading_block = False
                    _parse_and_update(buffer_lines)
                    buffer_lines = []

        except Exception as exc:
            logger.error(f"Unexpected error in serial reader: {exc}")
            time.sleep(1.0)


def _parse_and_update(lines: list):
    global runtime_raw_zero
    temp = None
    humidity = None
    ds_temp = None
    gas = 250
    raw_weight = None

    for line in lines:
        try:
            if line.startswith("SHT Temp:"):
                temp = float(line.split(":", 1)[1].replace("C", "").strip())
            elif line.startswith("Humidity:"):
                humidity = float(line.split(":", 1)[1].replace("%", "").strip())
            elif line.startswith("DS Temp:"):
                ds_temp = float(line.split(":", 1)[1].replace("C", "").strip())
            elif line.startswith("Gas:"):
                gas = int(line.split(":", 1)[1].strip())
            elif line.startswith("Load Cell Raw:"):
                raw_weight = int(line.split(":", 1)[1].strip())
        except Exception:
            pass

    with state_lock:
        if temp is not None:
            latest_reading["temperature"] = temp
        if humidity is not None:
            latest_reading["humidity"] = humidity
        if ds_temp is not None:
            latest_reading["ds_temperature"] = ds_temp
        latest_reading["gas"] = gas
        if raw_weight is not None:
            latest_reading["raw_weight"] = raw_weight
            latest_reading["weight"] = raw_to_kg(raw_weight)

        duty_status = duty_manager.get_status()
        latest_reading["online"] = True
        latest_reading["timestamp"] = datetime.now(timezone.utc).isoformat()
        latest_reading["actuators"]["heater_commanded"] = duty_status["heater_requested"]
        latest_reading["actuators"]["heater_physical_relay"] = duty_status["physical_relay_on"]
        latest_reading["actuators"]["duty_cycle"] = duty_status
        latest_reading["system"]["uptime_seconds"] = int(time.time() - START_TIME)


# ============================================================================
# 5. Background Cloud / Backend Push Thread
# ============================================================================
def backend_pusher_loop():
    """Continuously push telemetry to backend and apply returned actuator commands."""
    if not PUSH_TO_BACKEND:
        logger.info("Push to backend is disabled (PUSH_TO_BACKEND=false)")
        return

    logger.info(f"Starting backend telemetry pusher -> {BACKEND_URL}/api/iot/bridge/telemetry")
    endpoint = f"{BACKEND_URL}/api/iot/bridge/telemetry"

    while True:
        time.sleep(PUSH_INTERVAL_SECONDS)
        with state_lock:
            payload = dict(latest_reading)

        try:
            resp = requests.post(endpoint, json=payload, timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                with state_lock:
                    latest_reading["system"]["backend_synced"] = True
                    latest_reading["system"]["last_sync_error"] = None

                # Apply actuator commands sent back by backend
                commands = data.get("commands", {})
                if "heater" in commands:
                    duty_manager.set_heater_request(bool(commands["heater"]))
                if "fan" in commands:
                    apply_fan(bool(commands["fan"]))
                if "light" in commands:
                    apply_light(bool(commands["light"]))
            else:
                with state_lock:
                    latest_reading["system"]["backend_synced"] = False
                    latest_reading["system"]["last_sync_error"] = f"HTTP {resp.status_code}"
        except Exception as exc:
            with state_lock:
                latest_reading["system"]["backend_synced"] = False
                latest_reading["system"]["last_sync_error"] = str(exc)


def apply_fan(on: bool):
    with state_lock:
        latest_reading["actuators"]["fan"] = on
    send_raw_command("f" if on else "e")


def apply_light(on: bool):
    with state_lock:
        latest_reading["actuators"]["light"] = on
    send_raw_command("l" if on else "k")


# ============================================================================
# 6. Camera Live Streaming Service (MJPEG)
# ============================================================================
cv2 = None
camera_capture = None
camera_lock = threading.Lock()

try:
    import cv2
except ImportError:
    logger.warning("OpenCV (cv2) not installed. Live camera streaming endpoint will return placeholder frames.")


def get_camera_frame():
    """Capture one frame from the camera."""
    global camera_capture
    if cv2 is None:
        return None

    with camera_lock:
        if camera_capture is None:
            camera_capture = cv2.VideoCapture(CAMERA_INDEX)
            camera_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            camera_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            camera_capture.set(cv2.CAP_PROP_FPS, 20)

        if not camera_capture.isOpened():
            return None

        success, frame = camera_capture.read()
        if not success:
            return None

        # Add timestamp & temperature watermark
        with state_lock:
            temp = latest_reading.get("temperature", 0.0)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cv2.putText(
            frame, f"SMART KARAWALA | {ts} | {temp}C",
            (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
        )
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return jpeg.tobytes()


def generate_mjpeg_stream():
    """Generator for MJPEG HTTP video stream."""
    while True:
        frame_bytes = get_camera_frame()
        if frame_bytes is None:
            # Send placeholder or sleep
            time.sleep(0.1)
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )
        time.sleep(0.04)  # ~25 FPS


# ============================================================================
# 7. Self-Hosted FastAPI REST Endpoints (Raspberry Pi Edge API)
# ============================================================================
app = FastAPI(
    title="Smart Karawala - Raspberry Pi Oven Controller",
    description="Edge Controller and Data Bridge with Relay Duty Cycle Protection",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def index():
    return {
        "service": "Smart Karawala Oven Edge Controller",
        "device_id": DEVICE_ID,
        "status": "online",
        "endpoints": {
            "telemetry": "/api/telemetry",
            "sensors": "/api/sensors",
            "actuators": "/api/actuators",
            "tare": "/api/tare",
            "camera_stream": "/api/camera/stream",
            "camera_snapshot": "/api/camera/snapshot",
            "health": "/api/health"
        }
    }


@app.get("/api/telemetry")
@app.get("/api/sensors")
def get_telemetry():
    """Returns real-time sensor telemetry and actuator duty cycle status."""
    with state_lock:
        return dict(latest_reading)


@app.post("/api/actuators")
def set_actuators(payload: dict):
    """
    Directly control actuators:
    {"heater": true/false, "fan": true/false, "light": true/false}
    """
    results = {}
    if "heater" in payload:
        duty_manager.set_heater_request(bool(payload["heater"]))
        results["heater"] = bool(payload["heater"])

    if "fan" in payload:
        apply_fan(bool(payload["fan"]))
        results["fan"] = bool(payload["fan"])

    if "light" in payload:
        apply_light(bool(payload["light"]))
        results["light"] = bool(payload["light"])

    return {
        "success": True,
        "actuators": results,
        "duty_cycle": duty_manager.get_status()
    }


@app.post("/api/tare")
def tare_scale():
    """Tare load cell scale."""
    global runtime_raw_zero
    success = send_raw_command("t")
    time.sleep(0.5)
    with state_lock:
        raw = latest_reading.get("raw_weight", RAW_ZERO)
        runtime_raw_zero = raw
        latest_reading["weight"] = 0.0

    return {
        "success": success,
        "raw_zero": runtime_raw_zero,
        "message": "Scale tared successfully"
    }


@app.post("/api/command")
def raw_command(payload: dict):
    cmd = payload.get("command", "")
    mapping = {
        "heater_on": lambda: duty_manager.set_heater_request(True),
        "heater_off": lambda: duty_manager.set_heater_request(False),
        "fan_on": lambda: apply_fan(True),
        "fan_off": lambda: apply_fan(False),
        "light_on": lambda: apply_light(True),
        "light_off": lambda: apply_light(False),
        "tare": tare_scale,
    }
    if cmd in mapping:
        mapping[cmd]()
        return {"success": True, "command": cmd}
    raise HTTPException(status_code=400, detail=f"Unknown command: {cmd}")


@app.get("/api/camera/stream")
def camera_stream():
    """Live MJPEG video stream (works in any browser or <img> tag)."""
    return StreamingResponse(
        generate_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/api/camera/snapshot")
def camera_snapshot():
    """Single JPEG frame capture for YOLO inference or verification station."""
    frame_bytes = get_camera_frame()
    if frame_bytes is None:
        raise HTTPException(status_code=503, detail="Camera capture unavailable")
    return Response(content=frame_bytes, media_type="image/jpeg")


@app.get("/api/health")
def health():
    with state_lock:
        return {
            "status": "healthy" if latest_reading["online"] else "waiting_for_sensors",
            "uptime_seconds": int(time.time() - START_TIME),
            "serial_port": latest_reading["system"]["port"],
            "serial_connected": latest_reading["system"]["serial_connected"],
            "backend_synced": latest_reading["system"]["backend_synced"],
            "last_sync_error": latest_reading["system"]["last_sync_error"],
            "duty_cycle_phase": latest_reading["actuators"]["duty_cycle"]["phase"]
        }


# ============================================================================
# 8. Service Main Entry Point
# ============================================================================
def main():
    logger.info("=======================================================")
    logger.info(" Starting Smart Karawala Raspberry Pi Oven Controller ")
    logger.info("=======================================================")
    logger.info(f"Device ID: {DEVICE_ID}")
    logger.info(f"Relay Duty Cycle: {DUTY_CYCLE_ON_SECONDS}s ON / {DUTY_CYCLE_REST_SECONDS}s REST")
    logger.info(f"Self-hosted port: {SERVER_PORT}")
    logger.info(f"Central Backend: {BACKEND_URL} (Push: {PUSH_TO_BACKEND})")

    # Start Serial Reader thread
    t_serial = threading.Thread(target=serial_reader_loop, daemon=True)
    t_serial.start()

    # Start Cloud / Backend Pusher thread
    t_pusher = threading.Thread(target=backend_pusher_loop, daemon=True)
    t_pusher.start()

    # Run FastAPI Server
    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="warning")


if __name__ == "__main__":
    main()
