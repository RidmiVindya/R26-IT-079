"""HTTP client for stopping a drying run on Milan's IoT oven service.

Uses his existing public endpoint:

    POST {MILAN_API_URL}/api/iot/sessions/{batch_id}/stop

That call turns the heater, fan, and light off and records the session as
STOPPED with the reason we pass, so an automatic stop is distinguishable from
an operator stop in his event log. Nothing here requires any change to his
service.

Note on the reason: his /stop endpoint takes no request body, so the reason we
record lives on our side (in the safety event we persist). His log will show
the stop itself; ours explains why we asked for it.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class OvenControlUnavailableError(Exception):
    """Raised when the oven service cannot be reached or refuses the stop."""


async def stop_oven(batch_id: str) -> dict:
    """Ask the oven to stop drying `batch_id`.

    Raises
    ------
    OvenControlUnavailableError
        If the oven service is unreachable or returns an error status. The
        caller must treat a failure here as "the oven may still be running"
        and surface it, never swallow it - this is a safety action.
    """
    url = f"{settings.MILAN_API_URL}/api/iot/sessions/{batch_id}/stop"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url)
    except httpx.RequestError as exc:
        logger.error("Could not reach oven service to stop %s: %s", batch_id, exc)
        raise OvenControlUnavailableError(
            f"Oven service unreachable at {settings.MILAN_API_URL}"
        ) from exc

    if resp.status_code >= 400:
        logger.error(
            "Oven service refused stop for %s: %s %s",
            batch_id, resp.status_code, resp.text[:200],
        )
        raise OvenControlUnavailableError(
            f"Oven service returned {resp.status_code}: {resp.text[:200]}"
        )

    logger.warning("Auto-stopped oven for batch %s (over-drying safety)", batch_id)
    return resp.json()
