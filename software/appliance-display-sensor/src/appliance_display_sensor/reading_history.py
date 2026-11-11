"""Small, local history of accepted state changes; never controls appliance state."""
from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

from appliance_display_sensor.pipeline import FrameResult


MAX_EVENTS = 30


class ReadingHistory:
    """Caller serializes access. Only counts/text/timestamps, no images or raw errors."""

    def __init__(self) -> None:
        self._events: deque[dict[str, object]] = deque(maxlen=MAX_EVENTS)
        self._last_key: tuple[str, int | None] | None = None
        self._last_frame_at: float | None = None
        self._dropped = 0

    def clear(self) -> None:
        self._events.clear()
        self._last_key = None
        self._last_frame_at = None
        self._dropped = 0

    def _append(self, event: dict[str, object], observed_at: datetime) -> None:
        if len(self._events) == MAX_EVENTS:
            self._dropped += 1
        self._events.append({"observed_at": observed_at.isoformat(), **event})

    def observe(
        self, result: FrameResult | None, error: str | None, now: float,
        *, stale_after_seconds: float, observed_at: datetime | None = None,
    ) -> None:
        stamp = observed_at or datetime.now(UTC)
        if self._last_frame_at is not None and now - self._last_frame_at > stale_after_seconds:
            self._append({"kind": "gap", "seconds": round(now - self._last_frame_at, 1)}, stamp)
            # Do not calculate a change across a capture gap or imply cycle continuity.
            self._last_key = None
        self._last_frame_at = now
        if error or result is None:
            if self._last_key != ("error", None):
                self._append({"kind": "error"}, stamp)
                self._last_key = ("error", None)
            return
        stable, candidate = result.stable_state, result.candidate_state
        if stable is None:
            return
        key = (stable.status, stable.remaining_minutes)
        # A held running/complete value must not masquerade as a fresh observation.
        if key != (candidate.status, candidate.remaining_minutes) or key == self._last_key:
            return
        if stable.status == "running":
            previous = (
                self._last_key[1] if self._last_key and self._last_key[0] == "running" else None
            )
            minutes = stable.remaining_minutes
            self._append({
                "kind": "countdown", "text": (candidate.display_text or "")[:32],
                "minutes": minutes, "previous_minutes": previous,
                "change_minutes": (
                    minutes - previous if minutes is not None and previous is not None else None
                ),
            }, stamp)
        elif stable.status == "complete":
            self._append({"kind": "complete", "text": (candidate.display_text or "")[:32]}, stamp)
        elif stable.status == "unknown":
            blank = result.display.valid and all(d.value is None for d in result.display.digits)
            self._append({"kind": "unknown", "reason": "blank" if blank else "unreadable"}, stamp)
        else:
            return
        self._last_key = key

    def snapshot(self) -> dict[str, object]:
        return {
            "limit": MAX_EVENTS, "dropped": self._dropped,
            "events": [dict(event) for event in reversed(self._events)],
        }
