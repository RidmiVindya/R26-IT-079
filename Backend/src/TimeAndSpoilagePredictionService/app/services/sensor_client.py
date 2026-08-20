"""HTTP client for Milan's IoT drying-oven service.

Milan's service exposes live sensor readings from the drying oven. We pull the
latest reading over his REST API. His /api/iot/live returns a JSON object like:

    {"temperature": 36.0, "humidity": 53.0, "ds_temperature": 35.0,
     "gas": 252, "raw_weight": 119900, "weight": 0.21,
     "heater": true, "light": false, "fan": true}

`gas` is the raw MQ-136 reading (used as mq136_value for spoilage risk).
`weight` is the live load-cell weight in kg (used as current_weight_kg).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class SensorServiceUnavailableError(Exception):
    """Raised when Milan's IoT service cannot be reached or returns no data."""


async def fetch_live_reading() -> dict[str, Any]:
    """Fetch the latest live sensor reading from Milan's service.

    Calls GET {MILAN_API_URL}/api/iot/live.

    Raises
    ------
    SensorServiceUnavailableError
        If his service is unreachable, errors, or returns null/empty data.
    """
    url = f"{settings.MILAN_API_URL}/api/iot/live"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
    except httpx.RequestError as exc:
        logger.warning("Could not reach IoT service at %s: %s", url, exc)
        raise SensorServiceUnavailableError(
            f"IoT sensor service unreachable at {settings.MILAN_API_URL}"
        ) from exc

    if resp.status_code >= 400:
        raise SensorServiceUnavailableError(
            f"IoT service returned {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    if not data or not isinstance(data, dict):
        # Milan's endpoint returns null when no reading is available.
        raise SensorServiceUnavailableError(
            "IoT service returned no sensor data (is the device/mock running?)"
        )
    return data
