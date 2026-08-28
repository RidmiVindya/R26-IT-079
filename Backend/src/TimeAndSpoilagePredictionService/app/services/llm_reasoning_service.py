"""Plain-language reasoning over drying situations the rule-based models have
already assessed.

This is an ADDITIVE, ADVISORY layer:
  - It never decides a risk level and never decides whether the oven stops.
    The spoilage model and overdrying_monitor_service do both of those with
    deterministic rules, before this module is called.
  - A missing key, a timeout, or an API failure here can only mean "no
    explanation this time" - never a wrong risk level, a missed alert, or a
    skipped stop.
  - It is called only when there is something worth explaining, so a normal
    healthy run costs nothing.

Cost control
------------
Two independent guards:
  1. Only HIGH-risk situations are sent (see _REASONING_RISKS).
  2. Deduplication per (batch_id, kind): a condition that stays true for
     minutes produces one explanation, not one per poll. Without this, the
     UI polling /active/spoilage-risk every few seconds would bill a call
     every few seconds for the same unchanged situation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Only these risk levels are worth spending a call on.
_REASONING_RISKS = {"High"}
# One explanation per (batch_id, kind) within this window.
_REASONING_DEDUP_WINDOW = timedelta(minutes=5)

_last_reasoned_at: dict[tuple[str, str], datetime] = {}

# batch_id -> recent explanations, newest last. Bounded so a long run cannot
# grow this without limit.
_MAX_EXPLANATIONS_PER_BATCH = 20
_explanations: dict[str, list[dict]] = {}

_client = None
_client_unavailable = False


def _get_client():
    """Build the OpenAI client lazily, so a missing key disables this feature
    rather than breaking service startup."""
    global _client, _client_unavailable
    if _client is not None or _client_unavailable:
        return _client
    if not settings.OPENAI_API_KEY:
        _client_unavailable = True
        # WARNING rather than INFO: "the AI never explains anything" is a
        # silent gap an operator needs surfaced, and app logging is not
        # configured down to INFO.
        logger.warning("OPENAI_API_KEY not set; LLM reasoning is disabled.")
        return None
    try:
        from openai import OpenAI

        _client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception:
        _client_unavailable = True
        logger.exception("Could not initialise OpenAI client; LLM reasoning is disabled.")
    return _client


def clear_state(batch_id: str) -> None:
    """Drop dedup timers and stored explanations for a batch."""
    _explanations.pop(batch_id, None)
    for key in [k for k in _last_reasoned_at if k[0] == batch_id]:
        _last_reasoned_at.pop(key, None)


def get_explanations(batch_id: str) -> list[dict]:
    """Explanations produced so far for this batch, newest last."""
    return list(_explanations.get(batch_id, []))


def _should_reason(batch_id: str, kind: str, risk: str) -> bool:
    if not settings.LLM_REASONING_ENABLED:
        return False
    if risk not in _REASONING_RISKS:
        return False
    key = (batch_id, kind)
    now = datetime.now(timezone.utc)
    last = _last_reasoned_at.get(key)
    if last is not None and now - last < _REASONING_DEDUP_WINDOW:
        return False
    _last_reasoned_at[key] = now
    return True


def _build_prompt(kind: str, risk: str, reasons: list[str], details: dict[str, Any]) -> str:
    """Ground the model in exactly the numbers the rule-based check used, so
    it explains this assessment rather than forming its own."""
    detail_lines = [f"  {k}: {v}" for k, v in details.items() if v is not None]
    return "\n".join([
        "You are explaining an automated assessment from a fish-drying oven's "
        "monitoring system to the person operating it. Be concise (2-3 "
        "sentences), plain-language, and practical: what is happening, why it "
        "matters, and what to check. Do not invent readings or causes beyond "
        "what is given.",
        "",
        f"Assessment: {kind} - {risk} risk",
        "",
        "Why the system flagged it:",
        *[f"  - {r}" for r in reasons],
        "",
        "Readings it used:",
        *detail_lines,
    ])


def explain(
    batch_id: str,
    kind: str,
    risk: str,
    reasons: list[str],
    details: dict[str, Any],
) -> str | None:
    """Produce a plain-language explanation, or None if skipped/unavailable.

    Never raises: every failure path returns None, so a caller can treat a
    missing explanation as normal rather than an error.
    """
    if not _should_reason(batch_id, kind, risk):
        return None

    client = _get_client()
    if client is None:
        return None

    try:
        response = client.chat.completions.create(
            model=settings.OPENAI_REASONING_MODEL,
            messages=[{"role": "user", "content": _build_prompt(kind, risk, reasons, details)}],
            max_tokens=150,
            temperature=0.3,
        )
        explanation = (response.choices[0].message.content or "").strip()
    except Exception:
        logger.exception("LLM reasoning failed for batch %s (%s)", batch_id, kind)
        return None

    if not explanation:
        return None

    entry = {
        "kind": kind,
        "risk": risk,
        "created_at": datetime.now(timezone.utc),
        "explanation": explanation,
        "model": settings.OPENAI_REASONING_MODEL,
    }
    bucket = _explanations.setdefault(batch_id, [])
    bucket.append(entry)
    del bucket[:-_MAX_EXPLANATIONS_PER_BATCH]
    return explanation
