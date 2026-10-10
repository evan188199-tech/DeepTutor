"""Time helpers shared across services."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso_z() -> str:
    """Current UTC time as an ISO-8601 stamp ending with a literal ``Z``.

    Canonical replacement for the historical inline
    ``datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"``
    stamps persisted into ``meta.json``/manifest files: the body stays a
    naive-UTC ``isoformat()`` string (no ``+00:00`` offset) and the ``Z``
    suffix marks it as UTC. Output is byte-identical to the inline form,
    including the dropped ``.ffffff`` part when the microsecond field is 0.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
