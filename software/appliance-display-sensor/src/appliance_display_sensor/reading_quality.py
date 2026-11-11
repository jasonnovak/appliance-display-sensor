"""Bounded, memory-only counts of fresh decoder observations, not held states."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from appliance_display_sensor.pipeline import FrameResult


KINDS = ("readable", "blank", "unreadable", "error")
WINDOW_SECONDS = 300


@dataclass
class _Bucket:
    second: int
    first_at: float
    last_at: float
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(KINDS, 0))


class ReadingQuality:
    """Caller serializes access. At most 301 one-second buckets, regardless of FPS."""

    def __init__(self) -> None:
        self._buckets: deque[_Bucket] = deque(maxlen=WINDOW_SECONDS + 1)

    def clear(self) -> None:
        self._buckets.clear()

    def _trim(self, now: float) -> None:
        # Discard the whole boundary bucket: never report observations older than
        # five minutes. This can omit up to one extra second at the boundary.
        while self._buckets and self._buckets[0].first_at <= now - WINDOW_SECONDS:
            self._buckets.popleft()

    def observe(self, result: FrameResult | None, error: str | None, now: float) -> None:
        self._trim(now)
        if error or result is None:
            kind = "error"
        elif result.candidate_state.status in {"running", "complete"}:
            kind = "readable"
        elif result.display.valid and all(d.value is None for d in result.display.digits):
            kind = "blank"
        else:
            kind = "unreadable"
        second = int(now)
        if not self._buckets or self._buckets[-1].second != second:
            self._buckets.append(_Bucket(second, now, now))
        bucket = self._buckets[-1]
        bucket.last_at = now
        bucket.counts[kind] += 1

    def snapshot(self, now: float) -> dict[str, object]:
        self._trim(now)
        counts = {kind: sum(b.counts[kind] for b in self._buckets) for kind in KINDS}
        total = sum(counts.values())
        return {
            "window_seconds": WINDOW_SECONDS,
            "total": total,
            "counts": counts,
            "percentages": {
                kind: round(counts[kind] * 100 / total, 1) if total else None for kind in KINDS
            },
            "span_seconds": (
                round(self._buckets[-1].last_at - self._buckets[0].first_at, 1)
                if self._buckets else 0
            ),
            "last_sample_age_seconds": (
                round(max(0, now - self._buckets[-1].last_at), 1) if self._buckets else None
            ),
        }
