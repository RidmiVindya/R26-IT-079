"""HTTP client for Jayani's waste/salt/batch service.

This service owns batch data (fish type, weights, salting status). We read a
batch over her REST API so we stay loosely coupled — we never touch her
database or her code.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class BatchNotFoundError(Exception):
    """Raised when a batchId does not exist in Jayani's service."""


class BatchServiceUnavailableError(Exception):
    """Raised when Jayani's service cannot be reached."""


async def fetch_batch(batch_id: str) -> dict[str, Any]:
    """Fetch a single batch by its batchId from Jayani's service.

    Calls GET {JAYANI_API_URL}/api/batches/{batch_id} and returns the raw
    batch document (the `batch` object in her response envelope).

    Raises
    ------
    BatchNotFoundError
        If the batch does not exist (HTTP 404).
    BatchServiceUnavailableError
        If her service is unreachable or returns an unexpected error.
    """
    url = f"{settings.JAYANI_API_URL}/api/batches/{batch_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
    except httpx.RequestError as exc:
        logger.warning("Could not reach batch service at %s: %s", url, exc)
        raise BatchServiceUnavailableError(
            f"Batch service unreachable at {settings.JAYANI_API_URL}"
        ) from exc

    if resp.status_code == 404:
        raise BatchNotFoundError(f"Batch '{batch_id}' not found")
    if resp.status_code >= 400:
        raise BatchServiceUnavailableError(
            f"Batch service returned {resp.status_code}: {resp.text[:200]}"
        )

    body = resp.json()
    # Her get-by-id endpoint wraps the document: {"message": ..., "batch": {...}}
    batch = body.get("batch") if isinstance(body, dict) else None
    if not batch:
        raise BatchNotFoundError(f"Batch '{batch_id}' has no data")
    return batch


def normalize_fish_type(batch: dict[str, Any]) -> Optional[str]:
    """Return the batch's fish type normalized to lower-case, or None."""
    fish = batch.get("fishType") or batch.get("fish_type")
    if not isinstance(fish, str):
        return None
    return fish.strip().lower()
