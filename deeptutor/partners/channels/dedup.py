"""Volatile inbound message deduplication for push-based channels.

Chat platforms redeliver inbound events: webhook endpoints retry on slow
acks, and stream gateways replay recent events after reconnects. Processing
a redelivery a second time produces duplicate replies, so channels need a
short-window "already seen this message id" guard. This helper keeps state
in process memory only — it is intentionally volatile (no new storage
dependencies) and fails open for messages without an id, so first-delivery
semantics are preserved after restarts.
"""

from __future__ import annotations

from collections import OrderedDict
import time

#: How long a delivered message id is remembered. Platforms retry within
#: minutes; the window only needs to cover that retry horizon.
DEFAULT_INBOUND_DEDUP_TTL_S = 300.0

#: Hard cap on remembered ids so a busy channel cannot grow memory without
#: bound. Oldest entries are evicted first.
DEFAULT_INBOUND_DEDUP_MAX_IDS = 1000


class InboundDeduplicator:
    """Bounded, TTL-window tracker of recently seen inbound message ids."""

    def __init__(
        self,
        *,
        ttl_s: float = DEFAULT_INBOUND_DEDUP_TTL_S,
        max_ids: int = DEFAULT_INBOUND_DEDUP_MAX_IDS,
    ) -> None:
        self._ttl_s = float(ttl_s)
        self._max_ids = max(1, int(max_ids))
        # Ordered map id -> last-seen monotonic timestamp. Ordering by
        # recency lets expiry and size eviction share one pop-from-front.
        self._seen: OrderedDict[str, float] = OrderedDict()

    def is_duplicate(self, message_id: str | None, *, now: float | None = None) -> bool:
        """Return True when *message_id* was already seen inside the TTL window.

        A seen id refreshes its timestamp (sliding window) so an ongoing
        redelivery burst cannot outlive the guard. An empty or missing id is
        never a duplicate: without a stable id there is nothing to key on,
        and failing open keeps the first delivery processing.
        """
        key = str(message_id or "").strip()
        if not key:
            return False

        now_ts = time.monotonic() if now is None else float(now)
        self._evict_expired(now_ts)

        if key in self._seen:
            self._seen[key] = now_ts
            self._seen.move_to_end(key)
            return True

        self._seen[key] = now_ts
        while len(self._seen) > self._max_ids:
            self._seen.popitem(last=False)
        return False

    def _evict_expired(self, now_ts: float) -> None:
        while self._seen:
            oldest_key = next(iter(self._seen))
            if now_ts - self._seen[oldest_key] < self._ttl_s:
                break
            self._seen.popitem(last=False)
