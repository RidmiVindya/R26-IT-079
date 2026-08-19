"""Tracks the single active drying batch.

Per the integration requirement, only ONE batch is being dried at a time. This
store holds a pointer to that batch: its batchId, the fish type and starting
weight snapshotted from Jayani's batch data, and the drying start time (used to
compute elapsed hours and weight-loss rate).

Persistence is best-effort: the pointer is stored in MongoDB (collection
`active_drying_batch`) so it survives restarts, but if Mongo is unavailable we
fall back to an in-memory copy so the workflow still functions in a demo.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import settings
from app.database import mongodb

logger = logging.getLogger(__name__)

# Fixed document id so there is always at most one active-batch record.
_ACTIVE_DOC_ID = "current"

# In-memory fallback used when Mongo persistence is disabled.
_memory_active: Optional[dict[str, Any]] = None


def _collection():
    if mongodb.db is None:
        return None
    return mongodb.db[settings.MONGO_COLLECTION_ACTIVE_DRYING]


async def set_active_batch(
    batch_id: str,
    fish_type: str,
    initial_weight_kg: float,
    raw_batch: dict[str, Any],
    initial_temperature_c: Optional[float] = None,
    initial_total_hours: Optional[float] = None,
) -> dict[str, Any]:
    """Mark a batch as the active drying batch (replaces any previous one).

    `initial_temperature_c` / `initial_total_hours` are the recommended
    temperature and total drying time from the pre-drying prediction
    (POST /api/predict/initial), if the caller ran that step first. They seed
    the countdown shown before live sensor data can produce a meaningful
    re-estimate (see `active/drying-time`).
    """
    record = {
        "_id": _ACTIVE_DOC_ID,
        "batch_id": batch_id,
        "fish_type": fish_type,
        "initial_weight_kg": initial_weight_kg,
        "drying_started_at": datetime.now(timezone.utc),
        "initial_temperature_c": initial_temperature_c,
        "initial_total_hours": initial_total_hours,
        # Keep a snapshot of Jayani's batch for reference / debugging.
        "batch_snapshot": raw_batch,
    }

    global _memory_active
    _memory_active = record

    coll = _collection()
    if coll is not None:
        try:
            await coll.replace_one({"_id": _ACTIVE_DOC_ID}, record, upsert=True)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Could not persist active batch: %s", exc)

    return record


async def get_active_batch() -> Optional[dict[str, Any]]:
    """Return the current active drying batch, or None if none is set."""
    coll = _collection()
    if coll is not None:
        try:
            doc = await coll.find_one({"_id": _ACTIVE_DOC_ID})
            if doc:
                return doc
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Could not read active batch from Mongo: %s", exc)

    return _memory_active


async def clear_active_batch() -> None:
    """Remove the active drying batch pointer."""
    global _memory_active
    _memory_active = None

    coll = _collection()
    if coll is not None:
        try:
            await coll.delete_one({"_id": _ACTIVE_DOC_ID})
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Could not clear active batch: %s", exc)


def elapsed_drying_hours(active: dict[str, Any]) -> float:
    """Hours since drying started for the given active-batch record."""
    started = active.get("drying_started_at")
    if not isinstance(started, datetime):
        return 0.0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - started
    return max(0.0, delta.total_seconds() / 3600.0)
