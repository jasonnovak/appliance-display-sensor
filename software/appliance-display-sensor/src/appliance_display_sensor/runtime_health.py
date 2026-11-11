"""Small live-camera health heartbeat, independent of capture and the setup page."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from appliance_display_sensor.health import SystemHealth
from appliance_display_sensor.pipeline import FrameResult

LOGGER = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 10
HEALTH_EXPIRE_SECONDS = 45
UNREADABLE_AFTER_SECONDS = 60
ALIGNMENT_STATES = (
    "disabled", "not_configured", "reference_unavailable", "checking", "aligned", "moved",
    "uncheckable", "movement_unverified", "needs_reference", "paused", "stale", "error",
)


class RuntimeHealth:
    def __init__(self, *, stale_after_seconds: float = 15):
        self.stale_after_seconds = stale_after_seconds
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._frame_at: float | None = None
        self._readable_at: float | None = None
        self._readable_utc: str | None = None
        self._unreadable_since: float | None = None
        self._readability = "waiting"
        self._error = False

    def observe(self, result: FrameResult | None, *, calibrating: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            # A gap in capture breaks a claim of continuously unreadable frames.
            if self._frame_at is None or now - self._frame_at > self.stale_after_seconds:
                self._unreadable_since = None
            self._frame_at = now
            self._error = False
            if calibrating:
                self._readability = "calibrating"
            elif result is None:
                self._readability = "unreadable"
            elif result.candidate_state.status in {"running", "complete"}:
                self._readability = "readable"
                self._readable_at = now
                self._readable_utc = datetime.now(UTC).isoformat()
            elif result.display.valid and all(d.value is None for d in result.display.digits):
                self._readability = "blank"
            else:
                self._readability = "unreadable"
            if self._readability == "unreadable":
                if self._unreadable_since is None:
                    self._unreadable_since = now
            else:
                self._unreadable_since = None

    def capture_error(self) -> None:
        with self._lock:
            self._error = True
            self._unreadable_since = None

    def snapshot(self, *, calibrating: bool = False) -> dict[str, object]:
        now = time.monotonic()
        with self._lock:
            frame_age = None if self._frame_at is None else max(0, now - self._frame_at)
            if self._error:
                camera = "error"
            elif (
                now - self._started if frame_age is None else frame_age
            ) > self.stale_after_seconds:
                camera = "stale"
            else:
                camera = "waiting" if frame_age is None else "live"
            if calibrating:
                # A test may start between camera frames. It must interrupt the
                # problem timer immediately and never advance last saved reading.
                self._unreadable_since = None
            readability = (
                camera if camera != "live" else
                "calibrating" if calibrating else self._readability
            )
            unreadable_age = (
                max(0, now - self._unreadable_since)
                if readability == "unreadable" and self._unreadable_since is not None else 0
            )
            return {
                "camera_status": camera,
                "display_readability": readability,
                "frame_age_seconds": round(frame_age, 1) if frame_age is not None else None,
                "last_readable": self._readable_utc,
                "reading_age_seconds": (
                    round(max(0, now - self._readable_at), 1)
                    if self._readable_at is not None else None
                ),
                "unreadable_seconds": round(unreadable_age, 1),
                "reading_problem": unreadable_age >= UNREADABLE_AFTER_SECONDS,
            }


class HealthReporter:
    def __init__(
        self, health: RuntimeHealth, publish: Callable[[dict[str, object]], None],
        *, calibrating: Callable[[], bool] = lambda: False,
        alignment: Callable[[], Mapping[str, object]] | None = None,
    ):
        self.health = health
        self.publish = publish
        self.calibrating = calibrating
        self.alignment = alignment
        self.system = SystemHealth()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sensor-health", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def report_once(self) -> None:
        payload = self.health.snapshot(calibrating=self.calibrating())
        payload["system"] = self.system.snapshot()
        payload["mount_alignment"] = self._alignment_status(payload)
        self.publish(payload)

    def _alignment_status(self, health: Mapping[str, object]) -> str:
        if self.alignment is None:
            return "disabled"
        try:
            snapshot = self.alignment()
            status = snapshot.get("status")
            if status not in ALIGNMENT_STATES:
                return "error"
            if snapshot.get("configured"):
                if health.get("display_readability") == "calibrating":
                    return "paused"
                # A cached match must not look current after the camera stops.
                if health.get("camera_status") != "live":
                    return "stale"
            if status == "uncheckable" and snapshot.get("movement_latched") is True:
                return "movement_unverified"
            return str(status)
        except Exception:
            # An optional alignment callback must not suppress the main health heartbeat.
            # Keep raw exception details out of MQTT and the journal.
            return "error"

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.report_once()
            except Exception:
                # Health reporting must not interrupt capture. HA's expiry
                # marks missing heartbeats unavailable if reporting fails.
                LOGGER.warning("Health heartbeat failed", exc_info=True)
            self._stop.wait(HEARTBEAT_SECONDS)

    def close(self) -> None:
        self._stop.set()
        if self._thread.ident is not None:
            self._thread.join(timeout=2)
