import serial
import time
import os
from threading import RLock
from dotenv import load_dotenv

from app.settings import SENSOR_READ_TIMEOUT_SECONDS

load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM4")
BAUD_RATE = int(os.getenv("BAUD_RATE", 9600))

arduino = None
serial_lock = RLock()


def connect_arduino():
    global arduino

    with serial_lock:
        if arduino is not None and arduino.is_open:
            return True
        try:
            arduino = serial.Serial(
                port=SERIAL_PORT,
                baudrate=BAUD_RATE,
                timeout=1,
                write_timeout=1,
            )
            time.sleep(2)
            arduino.reset_input_buffer()
            print(f"Connected to Arduino on {SERIAL_PORT}")
            return True
        except Exception as e:
            arduino = None
            print(f"Arduino connection failed: {e}")
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


def read_sensor_block(timeout_seconds: float = SENSOR_READ_TIMEOUT_SECONDS):
    """
    Reads one complete SENSOR DATA block
    """

    if not is_arduino_connected():
        connect_arduino()
    deadline = time.monotonic() + max(timeout_seconds, 0.1)
    block = []
    started = False

    with serial_lock:
        if arduino is None or not arduino.is_open:
            return []
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
                if "-----------------------" in line:
                    return block
    print("Sensor block read timed out")
    return []


def send_command(command):
    global arduino

    with serial_lock:
        if arduino is None or not arduino.is_open:
            return False
        try:
            arduino.write(command.encode("utf-8"))
            arduino.flush()
            return True
        except Exception as e:
            print("Command send error:", e)
            return False
