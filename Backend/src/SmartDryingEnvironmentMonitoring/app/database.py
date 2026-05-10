import os
from datetime import datetime, timezone
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "fish_drying_db")

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]

sensor_collection = db["drying_sensor_logs"]


def save_sensor_log(data: dict):
    record = {
        **data,
        "device_id": "ARDUINO-NANO-001",
        "batch_id": "BATCH-TEST-001",
        "timestamp": datetime.now(timezone.utc)
    }

    result = sensor_collection.insert_one(record)
    return str(result.inserted_id)