# Smart Karawala - Oven IoT Controller & Edge Data Bridge Specification

> **Fixed System Architecture & API Contract**  
> This specification defines the hardware, network, relay safety duty cycle, Raspberry Pi edge endpoints, and central backend endpoints for the Smart Karawala drying oven.

---

## 1. System Architecture & Topology

```
+---------------------------------------------------------------------------------------------------+
|                                      DRYING OVEN HARDWARE                                         |
|                                                                                                   |
|  +---------------------------------------------------------------------------------------------+  |
|  | SENSORS & ACTUATORS                                                                         |  |
|  | - SHT31 Temp / Humidity     - DS18B20 Chamber Temp     - MQ-136 Gas Sensor                  |  |
|  | - HX711 Load Cell (Weight)  - 16x2 LCD Display         - Relay 1: Heater (Nichrome Element) |  |
|  | - Relay 2: Exhaust Fan      - Relay 3: Internal Light                                       |  |
|  +----------------------------------------------+----------------------------------------------+  |
|                                                 | Wires (Digital / Analog / I2C / SPI)             |
|                                                 v                                                 |
|  +---------------------------------------------------------------------------------------------+  |
|  | ARDUINO NANO (nano_dryfish_controller.ino)                                                   |  |
|  | - Reads all raw sensor pins & updates on-oven LCD display.                                  |  |
|  | - Direct driver for relay coils and HX711.                                                  |  |
|  | - Emits '===== SENSOR DATA =====' text blocks via USB Serial (9600 Baud).                   |  |
|  | - Accepts single-byte commands: '1'/'0' (Heater), 'f'/'e' (Fan), 'l'/'k' (Light), 't' (Tare)|  |
|  +----------------------------------------------+----------------------------------------------+  |
|                                                 | USB Cable (/dev/ttyUSB0 or /dev/ttyACM0)        |
|                                                 v                                                 |
|  +---------------------------------------------------------------------------------------------+  |
|  | RASPBERRY PI (Inside / Attached to Oven) - Controller & Edge Data Bridge                    |  |
|  | - Boots automatically on oven power-on; connects to Wi-Fi.                                  |  |
|  | - Runs 'pi_oven_bridge.py' edge daemon (FastAPI on Port 5000).                             |  |
|  | - ENFORCES RELAY DUTY CYCLE: 60s ON / 10s REST to prevent relay failure / element burnout.   |  |
|  | - Captures CSI / USB Camera video for live streaming.                                      |  |
|  | - Self-hosts local REST API + MJPEG video stream on local Wi-Fi.                            |  |
|  | - Bridges sensor data to central backend via HTTP POST.                                     |  |
|  +---------------------------------------------------------------------------------------------+  |
+-------------------------------------------------+-------------------------------------------------+
                                                  |
                         +------------------------+------------------------+
                         | (Local Wi-Fi Network)                           | (Over Internet / 4G / WAN)
                         v                                                 v
+-------------------------------------------------+     +-------------------------------------------------+
| LOCAL CLIENTS (Same Wi-Fi)                      |     | CLOUD / REMOTE BACKEND & CLIENTS                |
|                                                 |     |                                                 |
| 1. Verification Station (Next.js)               |     | 1. Central Backend (Port 8002)                  |
|    - Direct telemetry: http://<PI_IP>:5000/api/ |     |    - Receives telemetry:                        |
|    - Direct camera: http://<PI_IP>:5000/api/... |     |      POST /api/iot/bridge/telemetry             |
|                                                 |     |    - Proxies camera over WAN:                   |
| 2. Local Mobile Debugging                       |     |      GET /api/iot/camera/stream                 |
|    - Direct low-latency MJPEG preview.          |     | 2. Flutter Mobile App                           |
|                                                 |     |    - Communicates with Backend API.             |
|                                                 |     | 3. Cloudflare Tunnel / ngrok                    |
|                                                 |     |    - Secure HTTPS URL for remote camera stream. |
+-------------------------------------------------+     +-------------------------------------------------+
```

---

## 2. Relay Duty Cycle Protection (60s ON / 10s REST)

### Why Relay Duty Cycling Is Mandatory
High-power heating elements (1000W–2000W) draw heavy resistive/inductive currents. When a mechanical relay is held continuously closed for hours:
1. Relay contacts suffer continuous thermal arcing and contact welding.
2. The relay coil overheats and burns out prematurely.
3. Rapid element fatigue degrades heating efficiency.

### Exact Duty Cycle Specification
When the drying session requires heat (in `AUTO` mode when `temperature < target_temperature`, or in `MANUAL` mode when `heater = true`):

```
       |<-------- 60 Seconds -------->|<- 10s ->|<-------- 60 Seconds -------->|<- 10s ->|
RELAY  +------------------------------+         +------------------------------+         +---
STATE: |          PULSE: ON           |  REST   |          PULSE: ON           |  REST   | ON
       +                              +---------+                              +---------+
TIME:  0s                            60s       70s                            130s      140s
```

1. **HEATING_PULSE Phase (60 Seconds)**:
   - Physical relay coil is energized (Arduino command `'1'`).
   - Oven heating element delivers heat into the chamber.
2. **RESTING Phase (10 Seconds)**:
   - Physical relay coil is de-energized (Arduino command `'0'`).
   - Element and relay contacts cool down for 10 seconds; heat dissipates evenly via chamber convection.
3. **IDLE Phase (Heater OFF)**:
   - When chamber temperature reaches target temperature or session finishes:
   - Physical relay is immediately turned **OFF** (`'0'`).
   - Duty cycle resets to `IDLE` (no pulsing).

> [!IMPORTANT]
> **Edge Safety Guarantee**: The 60s ON / 10s REST timer runs locally on the Raspberry Pi inside `pi_oven_bridge.py`. Even if Wi-Fi drops or the central backend crashes, the Raspberry Pi hardware safety ensures the relay is never stuck ON.

---

## 3. Raspberry Pi Edge Endpoints (Self-Hosted on Port 5000)

The Raspberry Pi runs `pi_oven_bridge.py` and listens on `http://<RASPBERRY_PI_IP>:5000`.

### Endpoint Summary

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/telemetry` | Full real-time sensor readings, relay status, duty cycle state |
| `GET` | `/api/sensors` | Alias for `/api/telemetry` |
| `POST` | `/api/actuators` | Command heater (with duty cycle), fan, and light |
| `POST` | `/api/tare` | Tare the HX711 load cell (zero empty tray) |
| `POST` | `/api/command` | Send single legacy command (`heater_on`, `fan_off`, etc.) |
| `GET` | `/api/camera/stream` | Live MJPEG video stream (compatible with any browser/`<img>`) |
| `GET` | `/api/camera/snapshot` | Single JPEG frame capture for YOLO / AI verification |
| `GET` | `/api/health` | Edge diagnostics (Arduino connection, Wi-Fi, uptime) |

---

### Detailed Raspberry Pi Endpoints

#### 1. `GET /api/telemetry`
Returns the current parsed sensor data and real-time duty cycle state.

**Response (`200 OK`)**:
```json
{
  "device_id": "RPI-OVEN-001",
  "online": true,
  "timestamp": "2026-09-27T10:15:30.123456+00:00",
  "temperature": 48.5,
  "humidity": 52.0,
  "ds_temperature": 47.9,
  "gas": 280,
  "raw_weight": 82450,
  "weight": 0.485,
  "actuators": {
    "heater_commanded": true,
    "heater_physical_relay": true,
    "fan": true,
    "light": false,
    "duty_cycle": {
      "enabled": true,
      "heater_requested": true,
      "physical_relay_on": true,
      "phase": "HEATING_PULSE",
      "phase_elapsed_seconds": 24.3,
      "phase_remaining_seconds": 35.7,
      "on_duration_seconds": 60.0,
      "rest_duration_seconds": 10.0
    }
  },
  "system": {
    "serial_connected": true,
    "port": "/dev/ttyUSB0",
    "backend_synced": true,
    "last_sync_error": null,
    "uptime_seconds": 3410
  }
}
```

#### 2. `POST /api/actuators`
Directly set commanded actuator states.

**Request Body**:
```json
{
  "heater": true,
  "fan": true,
  "light": false
}
```
*Note: Any omitted field remains unchanged.*

**Response (`200 OK`)**:
```json
{
  "success": true,
  "actuators": {
    "heater": true,
    "fan": true,
    "light": false
  },
  "duty_cycle": {
    "enabled": true,
    "phase": "HEATING_PULSE",
    "phase_remaining_seconds": 60.0
  }
}
```

#### 3. `POST /api/tare`
Zero the empty fish tray. Sends `'t'` to Arduino and sets runtime zero.

**Response (`200 OK`)**:
```json
{
  "success": true,
  "raw_zero": 78959,
  "message": "Scale tared successfully"
}
```

#### 4. `GET /api/camera/stream`
Returns an `multipart/x-mixed-replace; boundary=frame` stream of JPEG images.
- Can be directly embedded in HTML: `<img src="http://192.168.8.120:5000/api/camera/stream" />`
- Native support in Flutter `Image.network` and Next.js verification station.

#### 5. `GET /api/camera/snapshot`
Returns a single JPEG image (`image/jpeg`) capture with current timestamp watermark.

---

## 4. Central Backend Endpoints (`SmartDryingEnvironmentMonitoring` Port 8002)

The central backend runs on `http://<BACKEND_HOST>:8002`.

### Endpoint Summary

| Method | Endpoint | Role |
|---|---|---|
| `POST` | `/api/iot/bridge/telemetry` | **Primary Bridge Ingestion**: Raspberry Pi pushes telemetry here; backend returns actuator commands |
| `GET` | `/api/iot/bridge/commands` | Polling endpoint for Raspberry Pi to fetch desired states |
| `GET` | `/api/iot/camera/stream` | Proxies live camera feed through backend for remote internet clients |
| `GET` | `/api/iot/live` | Current reading + active session status for Mobile/Web |
| `POST` | `/api/iot/sessions/{batch_id}/start` | Start AUTO/MANUAL drying session |
| `POST` | `/api/iot/sessions/{batch_id}/stop` | Stop active drying session |
| `PUT` | `/api/iot/sessions/{batch_id}/manual-actuators` | Manual operator override for heater/fan/light |
| `POST` | `/api/iot/tare` | Tare scale via session controller |

---

### Detailed Backend Bridge Endpoints

#### 1. `POST /api/iot/bridge/telemetry`
Called by the Raspberry Pi every 2 seconds. Ingests telemetry into the database and returns the desired actuator commands.

**Request from Raspberry Pi**:
```json
{
  "device_id": "RPI-OVEN-001",
  "temperature": 48.5,
  "humidity": 52.0,
  "ds_temperature": 47.9,
  "gas": 280,
  "raw_weight": 82450,
  "weight": 0.485,
  "heater": true,
  "fan": true,
  "light": false,
  "relay_duty_cycle": {
    "phase": "HEATING_PULSE",
    "phase_remaining_seconds": 35.7
  }
}
```

**Response to Raspberry Pi (`200 OK`)**:
```json
{
  "success": true,
  "session_active": true,
  "status": "DRYING",
  "commands": {
    "heater": true,
    "fan": true,
    "light": false,
    "duty_cycle_on_seconds": 60,
    "duty_cycle_rest_seconds": 10
  }
}
```
*The Raspberry Pi automatically aligns its actuators to match these returned commands!*

#### 2. `GET /api/iot/camera/stream`
Streams the live video feed by proxying the Raspberry Pi camera stream when `PI_BRIDGE_URL` is configured in `.env`.
- Remote users over the Internet can view the camera stream through the backend without configuring router port forwarding!

---

## 5. Live Streaming: Local Wi-Fi vs. Over Internet

```
                  +--------------------------------+
                  |  Raspberry Pi Camera (CSI/USB) |
                  +---------------+----------------+
                                  |
               +------------------+------------------+
               |                                     |
               v (Local Wi-Fi)                       v (Internet / Cloud)
     +-------------------+                 +----------------------+
     | Local Wi-Fi Stream|                 | Cloudflare Tunnel    |
     | http://<PI_IP>:   |                 | (cloudflared)        |
     | 5000/api/camera/  |                 +-----------+----------+
     | stream            |                             |
     +---------+---------+                             v
               |                           +----------------------+
               v                           | Secure HTTPS Stream  |
     Direct Local Viewing                  | https://oven-camera. |
     (0 internet latency,                  | yourdomain.com       |
      works offline)                       +-----------+----------+
                                                       |
                                                       v
                                            Mobile App & Remote Web
                                            (Works anywhere in the world)
```

### Mode 1: Within Local Wi-Fi (Direct Intranet)
- When the verification station laptop or mobile phone is connected to the same Wi-Fi as the Raspberry Pi:
- Use direct URL: `http://<PI_IP>:5000/api/camera/stream`
- Advantages: Zero internet bandwidth used, ultra-low latency (< 100ms), works even if Internet service provider is down.

### Mode 2: Over Internet / Without Local Wi-Fi (Remote Mode)
To view the stream from outside without complicated router port forwarding:

**Option A (Recommended): Cloudflare Tunnel (`cloudflared`)**
1. Install `cloudflared` on Raspberry Pi:
   ```bash
   curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
   sudo dpkg -i cloudflared.deb
   ```
2. Run quick tunnel:
   ```bash
   cloudflared tunnel --url http://localhost:5000
   ```
   Gives a public HTTPS URL like `https://xyz.trycloudflare.com/api/camera/stream` that works from any mobile network worldwide.

**Option B: Central Backend Proxy**
Set `PI_BRIDGE_URL=http://<PI_IP>:5000` in `Backend/src/SmartDryingEnvironmentMonitoring/.env`.
Remote clients simply view `http://<BACKEND_HOST>:8002/api/iot/camera/stream`.

---

## 6. Raspberry Pi Deployment & Auto-Start Setup

### Quick Setup on Raspberry Pi (One-Command)

1. Connect Raspberry Pi to Wi-Fi.
2. Plug Arduino Nano into Raspberry Pi USB port.
3. Plug Raspberry Pi Camera into CSI ribbon slot or USB port.
4. Clone or copy `pi_bridge/` folder to Raspberry Pi:
   ```bash
   cd ~/
   mkdir -p oven_bridge
   cd oven_bridge
   # Copy pi_oven_bridge.py, requirements.txt, oven-bridge.service
   chmod +x install_bridge.sh
   ./install_bridge.sh
   ```

### Systemd Auto-Start Service (`/etc/systemd/system/oven-bridge.service`)
The service is automatically started on boot and restarts if disconnected:
```ini
[Unit]
Description=Smart Karawala Raspberry Pi Oven Controller & Data Bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/oven_bridge
Environment="SERVER_PORT=5000"
Environment="BACKEND_URL=http://<BACKEND_IP>:8002"
Environment="PUSH_TO_BACKEND=true"
Environment="HEATER_DUTY_CYCLE_ON_SECONDS=60"
Environment="HEATER_DUTY_CYCLE_REST_SECONDS=10"
ExecStart=/home/pi/oven_bridge/.venv/bin/python3 /home/pi/oven_bridge/pi_oven_bridge.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Useful Commands on Raspberry Pi
- Check live status: `sudo systemctl status oven-bridge`
- View live logs & relay duty cycle ticks: `journalctl -u oven-bridge -f`
- Test telemetry endpoint: `curl http://localhost:5000/api/telemetry`
- Test camera frame: `curl -I http://localhost:5000/api/camera/snapshot`

---

## 7. Backend Configuration (`.env`)

In `Backend/src/SmartDryingEnvironmentMonitoring/.env`:
```env
SERIAL_PORT=/dev/cu.usbserial-A5069RR4
BAUD_RATE=9600
MONGO_URI=mongodb+srv://...
MONGO_DB_NAME=fish_drying_db

# Set Raspberry Pi IP address when connected to Wi-Fi
PI_BRIDGE_URL=http://192.168.8.120:5000

# Relay Duty Cycle Protection Settings
HEATER_DUTY_CYCLE_ON_SECONDS=60
HEATER_DUTY_CYCLE_REST_SECONDS=10
```

---

## 8. Verification & Test Checklist

- [x] **Arduino USB Detection**: `pi_oven_bridge.py` auto-detects `/dev/ttyUSB*` or `/dev/ttyACM*`.
- [x] **Relay Protection**: Duty cycle manager strictly limits heating pulses to 60s ON followed by 10s REST.
- [x] **Self-Hosted API**: Raspberry Pi serves `GET /api/telemetry` on port 5000.
- [x] **Camera Streaming**: MJPEG stream served at `GET /api/camera/stream` and snapshot at `GET /api/camera/snapshot`.
- [x] **Two-Way Synchronization**: Raspberry Pi pushes telemetry to `POST /api/iot/bridge/telemetry` and synchronizes actuator states.
- [x] **Zero Regressions**: Backend retains fallback to local USB serial when `PI_BRIDGE_URL` is omitted.
