"""Small persistence layer with an in-memory fallback for local development."""

import os
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock

from dotenv import load_dotenv
from pymongo import DESCENDING, MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "fish_drying_db")

client = None
db = None
sensor_collection = None
session_collection = None
event_collection = None
alert_collection = None

if MONGO_URI:
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2_000)
        db = client[MONGO_DB_NAME]
        sensor_collection = db["drying_sensor_logs"]
        session_collection = db["drying_sessions"]
        event_collection = db["drying_control_events"]
        alert_collection = db["drying_alert_logs"]
    except Exception as exc:
        print(f"MongoDB setup failed; using in-memory state: {exc}")

_lock = RLock()
_sessions: dict[str, dict] = {}
_sensor_logs: list[dict] = []
_events: list[dict] = []
_alerts: list[dict] = []


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mongo_write(operation) -> None:
    try:
        if operation:
            operation()
    except Exception as exc:
        # Control decisions remain available locally when MongoDB is unavailable.
        print(f"MongoDB write failed: {exc}")


def save_sensor_log(data: dict) -> str:
    record = {**deepcopy(data), "timestamp": utcnow()}
    with _lock:
        _sensor_logs.append(record)
    _mongo_write(lambda: sensor_collection.insert_one(deepcopy(record)) if sensor_collection else None)
    return str(record.get("_id", "in-memory"))


def get_sensor_history(batch_id: str | None, limit: int = 300) -> list[dict]:
    limit = max(1, min(limit, 2_000))
    if sensor_collection is not None:
        try:
            query = {"batch_id": batch_id} if batch_id else {}
            records = list(sensor_collection.find(query, {"_id": 0}).sort("timestamp", DESCENDING).limit(limit))
            return list(reversed(records))
        except Exception as exc:
            print(f"MongoDB history read failed: {exc}")
    with _lock:
        records = [r for r in _sensor_logs if not batch_id or r.get("batch_id") == batch_id]
        return deepcopy(records[-limit:])


def create_session(session: dict) -> dict:
    record = deepcopy(session)
    with _lock:
        if record["batch_id"] in _sessions:
            raise ValueError("A session already exists for this batch")
        _sessions[record["batch_id"]] = record
    _mongo_write(lambda: session_collection.insert_one(deepcopy(record)) if session_collection else None)
    return deepcopy(record)


def get_session(batch_id: str) -> dict | None:
    with _lock:
        record = _sessions.get(batch_id)
        if record:
            return deepcopy(record)
    if session_collection is not None:
        try:
            record = session_collection.find_one({"batch_id": batch_id}, {"_id": 0})
            if record:
                with _lock:
                    _sessions[batch_id] = deepcopy(record)
                return record
        except Exception as exc:
            print(f"MongoDB session read failed: {exc}")
    return None


def get_active_session() -> dict | None:
    active_states = {"DRYING", "COOLING", "READY"}
    with _lock:
        for session in _sessions.values():
            if session.get("status") in active_states:
                return deepcopy(session)
    if session_collection is not None:
        try:
            record = session_collection.find_one({"status": {"$in": list(active_states)}}, {"_id": 0})
            if record:
                with _lock:
                    _sessions[record["batch_id"]] = deepcopy(record)
                return record
        except Exception as exc:
            print(f"MongoDB active-session read failed: {exc}")
    return None


def update_session(batch_id: str, **changes) -> dict:
    changes = deepcopy(changes)
    changes["updated_at"] = utcnow()
    with _lock:
        if batch_id not in _sessions:
            existing = get_session(batch_id)
            if not existing:
                raise KeyError("Drying session not found")
        _sessions[batch_id].update(changes)
        result = deepcopy(_sessions[batch_id])
    _mongo_write(
        lambda: session_collection.update_one({"batch_id": batch_id}, {"$set": deepcopy(changes)})
        if session_collection
        else None
    )
    return result


def save_event(batch_id: str, event_type: str, payload: dict | None = None) -> dict:
    record = {
        "batch_id": batch_id,
        "event_type": event_type,
        "payload": deepcopy(payload or {}),
        "timestamp": utcnow(),
    }
    with _lock:
        _events.append(record)
    _mongo_write(lambda: event_collection.insert_one(deepcopy(record)) if event_collection else None)
    return deepcopy(record)


def get_events(batch_id: str, limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 1_000))
    if event_collection is not None:
        try:
            records = list(event_collection.find({"batch_id": batch_id}, {"_id": 0}).sort("timestamp", DESCENDING).limit(limit))
            return list(reversed(records))
        except Exception as exc:
            print(f"MongoDB event read failed: {exc}")
    with _lock:
        return deepcopy([event for event in _events if event["batch_id"] == batch_id][-limit:])


def save_alert_records(alerts: list[dict]) -> list[str]:
    records = []
    with _lock:
        for alert in alerts:
            record = {**deepcopy(alert), "timestamp": utcnow()}
            _alerts.append(record)
            records.append(record)
    for record in records:
        _mongo_write(lambda record=record: alert_collection.insert_one(deepcopy(record)) if alert_collection else None)
    return [str(record.get("_id", "in-memory")) for record in records]
