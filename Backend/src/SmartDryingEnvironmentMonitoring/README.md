# Smart Drying Environment Monitoring

The service monitors Arduino sensor blocks and implements the drying-controller
state machine for one chamber. It is responsible for enforcing a control profile;
it does not calculate fish-specific targets.

## Controller states

```text
READY → DRYING → COOLING → COMPLETED
             └→ STOPPED
             └→ FAULT
```

- A control profile is received for a real `batch_id` before a session can start.
- `start` captures one valid positive scale reading exactly once. The immutable
  completion weight is `initial_weight_kg / 3`.
- In `AUTO`, temperature control uses the configured `±2°C` hysteresis. The
  fan responds to the received humidity target with a configurable hysteresis.
- In `MANUAL`, an operator can command only heater and fan while the session is
  actively drying. Entering MANUAL turns the heater off first.
- At completion the heater is explicitly turned off, the fan is enabled for the
  profile's `cooling_duration_seconds`, then both are turned off and the session
  becomes `COMPLETED`.
- Missing/invalid sensor data or failed serial actuator delivery puts an active
  session into `FAULT` and issues best-effort off commands.

## API contract

All paths have the `/api` prefix.

### 1. Receive a control profile from the parameter/prediction module

`POST /api/iot/control-profiles`

```json
{
  "batch_id": "BATCH-123",
  "target_temperature_c": "number supplied by the prediction module",
  "target_humidity_percent": "number supplied by the prediction module",
  "predicted_duration_minutes": "optional number supplied by the prediction module",
  "profile_version": "profile-version",
  "source": "prediction_module",
  "cooling_duration_seconds": 300
}
```

The strings above explain ownership, not literal JSON values. The request
validator requires a positive temperature and humidity between 0 and 100.
Targets must come from the team's agreed parameter/prediction profile.

### 2. Start or stop a session

`POST /api/iot/sessions/{batch_id}/start`

```json
{ "mode": "AUTO" }
```

The service takes a fresh sensor reading before starting. It rejects the request
if chamber temperature, humidity, or a positive batch weight is unavailable.

Both AUTO and MANUAL sessions finish drying when either the target duration is
reached or the batch reaches its completion weight (one third of its captured
starting weight). Completion turns the heater and light off, then runs the
exhaust fan for the cooling period.

`POST /api/iot/sessions/{batch_id}/stop`

### 3. Change mode or manually operate actuators

`PUT /api/iot/sessions/{batch_id}/mode`

```json
{ "mode": "MANUAL" }
```

`PUT /api/iot/sessions/{batch_id}/manual-actuators`

```json
{ "heater": true, "fan": false, "light": true }
```

### 4. Monitoring

- `GET /api/iot/live` — one current reading, current session, and AUTO/cooling tick.
- `GET /api/iot/readings?batch_id=BATCH-123&limit=300` — timestamped history for graphs.
- `GET /api/iot/sessions/{batch_id}` — persisted controller state.
- `GET /api/iot/sessions/{batch_id}/events` — lifecycle events; use
  `WEIGHT_COMPLETION_REACHED` or `DRYING_COMPLETED` for a Flutter notification.
- `POST /api/iot/tare` — blocked during DRYING and COOLING.
- `GET /api/iot/alerts/check` — compatibility endpoint; the background heartbeat also records deduplicated alerts.

The old `POST /api/iot/command` endpoint is deprecated. It only bridges `tare`,
heater, and fan requests to an active `MANUAL` session. It no longer permits
untracked relay control.

## Arduino protocol currently expected

The backend preserves the existing single-character command protocol:

| Action | Character |
|---|---|
| Heater on/off | `1` / `0` |
| Fan on/off | `f` / `e` |
| Light on/off | `l` / `k` |
| Tare | `t` |

The repository does not contain the Arduino firmware. The current backend can
only confirm that bytes were written to the serial port. Firmware must add a
command acknowledgement and return the resulting relay state before this can be
considered end-to-end verified.

## Configuration

```env
SERIAL_PORT=COM4
BAUD_RATE=9600
DEVICE_ID=ARDUINO-NANO-001
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=fish_drying_db
HX711_RAW_ZERO=78959
HX711_COUNTS_PER_KG=389300.0
TEMPERATURE_TOLERANCE_C=2
HUMIDITY_TOLERANCE_PERCENT=3
SENSOR_READ_TIMEOUT_SECONDS=3
SENSOR_SAVE_INTERVAL_SECONDS=10
```

`HX711_*` values must be calibrated against your actual scale. Install the empty
fish tray and call `POST /api/iot/tare` before adding fish; the service captures
that post-tare raw reading as its runtime zero and verifies a `0.000 kg` result.
The service uses
an in-memory fallback if MongoDB is unavailable; MongoDB is required for session
recovery and durable integration testing.
