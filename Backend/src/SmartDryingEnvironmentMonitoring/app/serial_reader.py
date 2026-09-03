import serial
import time
import os
from threading import RLock
from dotenv import load_dotenv

from app.settings import SENSOR_BLOCK_CACHE_SECONDS, SENSOR_READ_TIMEOUT_SECONDS

load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/cu.usbserial-A5069RR4")
BAUD_RATE = int(os.getenv("BAUD_RATE", 9600))

# Opt-in software simulation for running without physical Arduino hardware.
# When MOCK_SENSORS is unset/false, all real-hardware behaviour below is
# byte-for-byte unchanged.
MOCK_SENSORS = os.getenv("MOCK_SENSORS", "false").strip().lower() in ("1", "true", "yes")

arduino = None
serial_lock = RLock()

# Roughly one block of text; more than this waiting means we are behind.
_STALE_BACKLOG_BYTES = 400

_last_block: list[str] = []
_last_block_at = 0.0

# Slowly-varying counter so mock readings drift a little between calls
# (deterministic — no random, so behaviour is reproducible).
_mock_tick = 0


def _mock_sensor_block():
    """
    Produce one simulated SENSOR DATA block in the exact text format the
    real Arduino emits, so sensor_parser.get_live_sensor_data() parses it
    identically to a real reading.
    """
    global _mock_tick
    _mock_tick += 1

    # Drift values within realistic drying-oven ranges.
    temp = 34.0 + (_mock_tick % 6)          # 34-39 C
    humidity = 55.0 - (_mock_tick % 10)     # 45-55 %
    ds_temp = 33.0 + (_mock_tick % 5)       # 33-37 C
    gas = 250 + (_mock_tick % 300)          # 250-549 (MQ-136 raw)
    # Weight decreases over time as fish dries. Read the zero/scale from
    # sensor_parser so a runtime tare (which moves the zero point, exactly
    # as a real load cell tare would) is reflected in the mock reading too.
    from app.sensor_parser import COUNTS_PER_KG, get_raw_zero
    kg = max(3.0, 8.0 - _mock_tick * 0.05)  # 8.0kg drifting down, floor 3.0kg
    raw_weight = int(get_raw_zero() + kg * COUNTS_PER_KG)

    return [
        "===== SENSOR DATA =====",
        f"SHT Temp: {temp:.1f} C",
        f"Humidity: {humidity:.1f} %",
        f"DS Temp: {ds_temp:.1f} C",
        f"Gas: {gas}",
        f"Load Cell Raw: {raw_weight}",
        "Heater/Dry Air: ON",
        "Light: OFF",
        "Fan: ON",
        "-----------------------",
    ]


def find_available_port():
    import glob, sys
    if os.path.exists(SERIAL_PORT):
        return SERIAL_PORT
    patterns = ['/dev/cu.usbserial*', '/dev/cu.usbmodem*', '/dev/cu.wchusbserial*', '/dev/ttyUSB*', '/dev/ttyACM*']
    for pat in patterns:
        ports = glob.glob(pat)
        if ports:
            return ports[0]
    return SERIAL_PORT

def connect_arduino():
    global arduino

    if MOCK_SENSORS:
        print("MOCK_SENSORS enabled; skipping real Arduino connection")
        return True

    with serial_lock:
        if arduino is not None and arduino.is_open:
            return True
        target_port = find_available_port()
        try:
            arduino = serial.Serial(
                port=target_port,
                baudrate=BAUD_RATE,
                timeout=1,
                write_timeout=1,
            )
            time.sleep(2)
            arduino.reset_input_buffer()
            print(f"Connected to Arduino on {target_port}")
            return True
        except Exception as e:
            arduino = None
            print(f"Arduino connection failed on {target_port}: {e}")
            return False


def close_arduino():
    global arduino
    with serial_lock:
        if arduino is not None:
            try:
                arduino.close()
            except Exception as exc:
                print(f"Arduino close error: {exc}")
        arduino = None


def is_arduino_connected() -> bool:
    if MOCK_SENSORS:
        return True
    return arduino is not None and arduino.is_open


def read_serial_line():
    global arduino

    if arduino is None or not arduino.is_open:
        return None
    try:
        line = arduino.readline().decode("utf-8", errors="ignore").strip()
        return line or None
    except Exception as e:
        print("Serial read error:", e)
        return None


def read_sensor_block(timeout_seconds: float = 0.5):
    """
    Reads one complete SENSOR DATA block
    """

    if MOCK_SENSORS:
        return _mock_sensor_block()

    global _last_block, _last_block_at

    block = []
    started = False
    deadline = time.monotonic() + timeout_seconds

    with serial_lock:
        if arduino is None or not arduino.is_open:
            return []

        # Serve the cached block when it is newer than one firmware cycle.
        # Several endpoints poll concurrently and this function holds
        # serial_lock for a whole read, so without the cache each waiting
        # caller would start its own read and they would queue up behind
        # each other for no benefit - the device has nothing newer to give.
        if _last_block and (time.monotonic() - _last_block_at) < 15.0:
            return list(_last_block)

        # Drop a backlog only when it is large enough to be genuinely stale
        # (more than roughly one block in waiting). Flushing unconditionally
        # discards the block that is already arriving and forces a wait for
        # the whole of the next firmware cycle.
        try:
            if arduino.in_waiting > _STALE_BACKLOG_BYTES:
                arduino.reset_input_buffer()
        except Exception as e:
            print("Serial buffer reset error:", e)

        while time.monotonic() < deadline:
            line = read_serial_line()
            if line is None:
                continue

            if "SENSOR DATA" in line:
                started = True
                block = [line]
                continue

            if started:
                block.append(line)
                if "----" in line or "====" in line or len(block) >= 8:
                    _last_block = list(block)
                    _last_block_at = time.monotonic()
                    return block
    print("Sensor block read timed out")
    return []


def send_command(command):
    global arduino

    if MOCK_SENSORS:
        print(f"MOCK_SENSORS enabled; pretending to send command: {command}")
        return True

    if arduino is None or not arduino.is_open:
        return False
    try:
        arduino.write(command.encode("utf-8"))
        return True
    except Exception as e:
        print("Command send error:", e)
        return False
