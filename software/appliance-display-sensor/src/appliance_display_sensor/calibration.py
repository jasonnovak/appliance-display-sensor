from __future__ import annotations

import copy
import json
import os
import shutil
import threading
import time
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import NamedTemporaryFile
from collections.abc import Callable, Mapping

import cv2
import numpy as np

from appliance_display_sensor.config import AppConfig, load_config
from appliance_display_sensor.alignment import AlignmentMonitor, profile_signature
from appliance_display_sensor.calibration_suggestions import suggest_pixels
from appliance_display_sensor.calibration_feedback import inspect_readability
from appliance_display_sensor.diagnostics import render_diagnostic
from appliance_display_sensor.decoders.seven_segment import SevenSegmentDecoder
from appliance_display_sensor.health import SystemHealth
from appliance_display_sensor.pipeline import FrameProcessor, FrameResult
from appliance_display_sensor.reading_quality import ReadingQuality
from appliance_display_sensor.reading_history import ReadingHistory
from appliance_display_sensor.models import Rect


MAX_REQUEST_BYTES = 64 * 1024
PREVIEW_TIMEOUT_SECONDS = 10 * 60
PREVIEW_MAX_WIDTH = 1152
PROFILE_FORMAT = "appliance-display-sensor-optical-profile"
PROFILE_VERSION = 2
MAX_DIAGNOSTIC_PIXELS = 1_000_000
MAX_DIAGNOSTIC_BYTES = 8 * 1024 * 1024


def _rect_value(rect: object | None) -> list[int] | None:
    if rect is None:
        return None
    return [rect.x, rect.y, rect.width, rect.height]  # type: ignore[attr-defined]


def _public_config(config: AppConfig) -> dict[str, object]:
    camera = config.input.camera
    return {
        "camera": (
            {
                "resolution": [camera.width, camera.height],
                "rotation": camera.rotation,
                "exposure_time_us": camera.exposure_time_us,
                "analogue_gain": camera.analogue_gain,
                "autofocus_mode": camera.autofocus_mode,
                "lens_position": camera.lens_position,
                "capture_burst_count": camera.capture_burst_count,
            }
            if camera is not None
            else None
        ),
        "display": {
            "roi": _rect_value(config.display.roi),
            "digit_boxes": [_rect_value(box) for box in config.display.digit_boxes],
            "colon_box": _rect_value(config.display.colon_box),
            "colon_after": config.display.colon_after,
            "channel": config.display.channel,
            "threshold_method": config.display.threshold_method,
            "threshold_value": config.display.threshold_value,
            "min_segment_fill": config.display.min_segment_fill,
            "colon_min_fill": config.display.colon_min_fill,
            "min_digit_confidence": config.display.min_digit_confidence,
            "segment_thickness_ratio": config.display.segment_thickness_ratio,
            "segment_slant_ratio": config.display.segment_slant_ratio,
            "segment_sample_boxes": (
                dict(zip("abcdefg", config.display.segment_sample_boxes))
                if config.display.segment_sample_boxes is not None else None
            ),
        },
        "stability": {
            "unknown_grace_seconds": config.stability.unknown_grace_seconds,
        },
        "semantics": {"countdown_format": config.semantics.countdown_format},
    }


def optical_profile(config: AppConfig) -> dict[str, object]:
    """Export only calibration fields, never identity, network, paths or credentials."""
    public = _public_config(config)
    public.pop("semantics")  # Version 1 optical profiles never change duration interpretation.
    camera = dict(public["camera"] or {})
    geometry = (
        {"resolution": camera.pop("resolution"), "rotation": camera.pop("rotation")}
        if camera else None
    )
    public["camera"] = camera
    version = PROFILE_VERSION
    if public["display"]["segment_sample_boxes"] is None:
        # Preserve existing exported profiles and alignment-reference signatures.
        public["display"].pop("segment_sample_boxes")
        version = 1
    return {
        "format": PROFILE_FORMAT, "version": version,
        "camera_geometry": geometry, "calibration": public,
    }


def _backup_optics(path: Path) -> AppConfig:
    """Validate backup optics without loading its old MQTT password file or identity."""
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Previous configuration must be a mapping")
    sanitized = {
        "version": raw.get("version", 1),
        "device": {"identifier": "calibration-backup", "name": "Calibration backup"},
        "input": raw.get("input", {}), "display": raw.get("display", {}),
        "stability": raw.get("stability", {}), "mqtt": {"enabled": False},
    }
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".yaml", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            yaml.safe_dump(sanitized, temporary)
        return load_config(temporary_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _detection_payload(result: FrameResult | None, error: str | None) -> dict[str, object]:
    if result is None:
        return {"error": error or "Waiting for the first camera frame"}
    return {
        "error": error,
        "text": result.candidate_state.display_text,
        "optical_text": result.display.text,
        "valid": result.display.valid,
        "confidence": round(result.candidate_state.confidence, 4),
        "colon_on": result.display.colon_on,
        "colon_confidence": round(result.display.colon_confidence, 4),
        "candidate_status": result.candidate_state.status,
        "stable_status": result.stable_state.status if result.stable_state else None,
        "digits": [
            {
                "value": digit.value,
                "valid": digit.valid,
                "confidence": round(digit.confidence, 4),
                "active_segments": list(digit.active_segments),
                "segment_scores": {
                    name: round(score, 4) for name, score in digit.segment_scores.items()
                },
            }
            for digit in result.display.digits
        ],
    }


def build_candidate_config(
    config_path: str | Path,
    updates: Mapping[str, object],
) -> tuple[AppConfig, dict[str, object]]:
    """Validate setup fields without exposing or replacing secret fields."""

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - dependency error path
        raise RuntimeError("PyYAML is required for calibration") from exc

    path = Path(config_path)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("configuration must be a mapping")
    raw: dict[str, object] = copy.deepcopy(loaded)

    camera_update = updates.get("camera", {})
    display_update = updates.get("display", {})
    stability_update = updates.get("stability", {})
    semantics_update = updates.get("semantics", {})
    if not isinstance(semantics_update, Mapping):
        raise ValueError("semantics must be a mapping")
    if not isinstance(camera_update, Mapping):
        raise ValueError("camera must be a mapping")
    if not isinstance(display_update, Mapping):
        raise ValueError("display must be a mapping")
    if not isinstance(stability_update, Mapping):
        raise ValueError("stability must be a mapping")

    input_raw = raw.setdefault("input", {})
    display_raw = raw.setdefault("display", {})
    stability_raw = raw.setdefault("stability", {})
    if not isinstance(input_raw, dict) or not isinstance(display_raw, dict):
        raise ValueError("input and display must be mappings")
    if not isinstance(stability_raw, dict):
        raise ValueError("stability must be a mapping")

    camera_fields = {
        "exposure_time_us",
        "analogue_gain",
        "autofocus_mode",
        "lens_position",
        "capture_burst_count",
    }
    display_fields = {
        "roi",
        "digit_boxes",
        "colon_box",
        "colon_after",
        "channel",
        "min_segment_fill",
        "colon_min_fill",
        "min_digit_confidence",
        "segment_thickness_ratio",
        "segment_slant_ratio",
        "segment_sample_boxes",
    }
    unexpected = set(camera_update) - camera_fields
    unexpected |= set(display_update) - display_fields - {"threshold_method", "threshold_value"}
    unexpected |= set(stability_update) - {"unknown_grace_seconds"}
    unexpected |= set(semantics_update) - {"countdown_format"}
    if unexpected:
        raise ValueError("unsupported calibration fields: " + ", ".join(sorted(unexpected)))

    for name in camera_fields:
        if name in camera_update:
            value = camera_update[name]
            if value is None:
                input_raw.pop(name, None)
            else:
                input_raw[name] = value
    for name in display_fields:
        if name in display_update:
            value = display_update[name]
            if value is None and name in {"colon_box", "colon_after", "segment_sample_boxes"}:
                display_raw.pop(name, None)
            else:
                display_raw[name] = value
    threshold = display_raw.setdefault("threshold", {})
    if not isinstance(threshold, dict):
        raise ValueError("display.threshold must be a mapping")
    if "threshold_method" in display_update:
        threshold["method"] = display_update["threshold_method"]
    if "threshold_value" in display_update:
        threshold["value"] = display_update["threshold_value"]
    if "unknown_grace_seconds" in stability_update:
        stability_raw["unknown_grace_seconds"] = stability_update["unknown_grace_seconds"]
    if "countdown_format" in semantics_update:
        semantics_raw = raw.setdefault("semantics", {})
        if not isinstance(semantics_raw, dict):
            raise ValueError("semantics must be a mapping")
        semantics_raw["countdown_format"] = semantics_update["countdown_format"]

    temporary_name: str | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".yaml",
            prefix=".calibration-",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            yaml.safe_dump(raw, temporary, sort_keys=False)
        validated = load_config(temporary_name)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return validated, raw


def save_candidate_config(config_path: str | Path, raw: Mapping[str, object]) -> Path:
    """Atomically save a validated candidate and retain one rollback copy."""

    import yaml

    path = Path(config_path)
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(yaml.safe_dump(dict(raw), sort_keys=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


class CalibrationSession:
    def __init__(
        self, config_path: str | Path, config: AppConfig,
        mqtt_health: Callable[[], Mapping[str, object]] | None = None,
    ):
        self.config_path = Path(config_path)
        self._lock = threading.Lock()
        self._encode_lock = threading.Lock()
        self._diagnostic_lock = threading.Lock()
        self._suggestion_lock = threading.Lock()
        self._saved_config = config
        self._preview_config = config
        self._preview_raw: dict[str, object] | None = None
        self._pending_config: AppConfig | None = None
        self._frame: np.ndarray | None = None
        self._result: FrameResult | None = None
        self._error: str | None = None
        self._active = False
        self._last_preview_change = 0.0
        self._frame_version = 0
        self._config_revision = 0
        self._reading_quality = ReadingQuality()
        self._reading_history = ReadingHistory()
        self._quality_skip_frame = False
        self._image_cache: dict[tuple[str | bool, int, int], bytes] = {}
        self._system_health = SystemHealth()
        self._mqtt_health = mqtt_health
        self._started_at = time.monotonic()
        self._last_frame_at: float | None = None
        self._last_reading_at: float | None = None
        self._alignment = AlignmentMonitor(self.config_path.with_suffix(
            self.config_path.suffix + ".alignment.npz",
        ))

    @property
    def active(self) -> bool:
        with self._lock:
            self._expire_preview_locked()
            return self._active

    def update_frame(
        self,
        image: np.ndarray,
        result: FrameResult | None,
        error: str | None = None,
        *,
        config_revision: int | None = None,
    ) -> None:
        with self._lock:
            self._frame = image.copy()
            self._result = result
            self._error = error
            self._frame_version += 1
            self._image_cache.clear()
            self._last_frame_at = time.monotonic()
            if (self._pending_config is None
                    and config_revision in (None, self._config_revision)):
                if self._quality_skip_frame:
                    # The image was captured before pending camera controls were
                    # applied. Start counting with the following captured image.
                    self._quality_skip_frame = False
                else:
                    self._reading_quality.observe(result, error, self._last_frame_at)
                    camera = self._preview_config.input.camera
                    self._reading_history.observe(
                        result, error, self._last_frame_at,
                        stale_after_seconds=max(10.0, 3 * camera.frame_interval_seconds)
                        if camera else 10.0,
                    )
            if not error:
                self._alignment.update(
                    image, profile_signature(optical_profile(self._saved_config)),
                    testing=self._active or self._pending_config is not None,
                )
            if result is not None and result.candidate_state.status != "unknown":
                self._last_reading_at = self._last_frame_at

    def state(self) -> dict[str, object]:
        system = self._system_health.snapshot()
        mqtt = dict(self._mqtt_health()) if self._mqtt_health else {
            "enabled": self._saved_config.mqtt.enabled, "connected": None,
        }
        with self._lock:
            self._expire_preview_locked()
            now = time.monotonic()
            frame_age = None if self._last_frame_at is None else now - self._last_frame_at
            reading_age = None if self._last_reading_at is None else now - self._last_reading_at
            camera = self._preview_config.input.camera
            stale_after = max(10.0, 3 * camera.frame_interval_seconds) if camera else 10.0
            camera_status = (
                "waiting" if frame_age is None else
                "stale" if frame_age > stale_after else
                "error" if self._error else "live"
            )
            frame_shape = list(self._frame.shape[:2][::-1]) if self._frame is not None else None
            alignment = self._alignment_snapshot_locked(now)
            return {
                "active": self._active,
                "frame_size": frame_shape,
                "config": _public_config(self._preview_config),
                "detection": _detection_payload(self._result, self._error),
                "revision": self._config_revision,
                "reading_quality": {
                    **self._reading_quality.snapshot(now),
                    "revision": self._config_revision,
                    "mode": "test" if self._active else "saved",
                    "collecting": self._pending_config is None and not self._quality_skip_frame,
                },
                "reading_history": {
                    **self._reading_history.snapshot(),
                    "revision": self._config_revision,
                    "mode": "test" if self._active else "saved",
                    "collecting": self._pending_config is None and not self._quality_skip_frame,
                },
                "recovery": {
                    "previous_available": self.config_path.with_suffix(
                        self.config_path.suffix + ".bak"
                    ).is_file(),
                },
                "preview_seconds_remaining": (
                    max(0, round(PREVIEW_TIMEOUT_SECONDS - (now - self._last_preview_change)))
                    if self._active else None
                ),
                "health": {
                    "camera_status": camera_status,
                    "frame_age_seconds": None if frame_age is None else round(frame_age, 1),
                    "reading_age_seconds": None if reading_age is None else round(reading_age, 1),
                    "service_uptime_seconds": round(now - self._started_at, 1),
                    "mqtt": mqtt, "system": system, "alignment": alignment,
                },
            }

    def alignment_health(self) -> dict[str, object]:
        """Cheap heartbeat snapshot: no image encoding, system sampling, or reference writes."""
        with self._lock:
            self._expire_preview_locked()
            snapshot = self._alignment_snapshot_locked(time.monotonic())
            # MQTT needs only status and latch context, never template pixels/geometry.
            return {key: snapshot[key] for key in ("status", "configured", "movement_latched")}

    def _alignment_snapshot_locked(self, now: float) -> dict[str, object]:
        alignment = self._alignment.snapshot()
        if alignment["configured"]:
            camera = self._preview_config.input.camera
            stale_after = max(10.0, 3 * camera.frame_interval_seconds) if camera else 10.0
            if self._active or self._pending_config is not None:
                alignment["status"] = "paused"
            elif (profile_signature(optical_profile(self._saved_config))
                  != self._alignment.signature):
                alignment["status"] = "needs_reference"
            elif (self._last_frame_at is None or now - self._last_frame_at > stale_after
                  or self._error):
                alignment["status"] = "stale"
        return alignment

    def export_profile(self) -> dict[str, object]:
        with self._lock:
            return optical_profile(self._saved_config)

    def alignment_reference(self, payload: Mapping[str, object]) -> dict[str, object]:
        if (set(payload) != {"anchor_box", "revision", "confirmed"}
                or payload["confirmed"] is not True or type(payload["revision"]) is not int):
            raise ValueError("Confirm the physical alignment before storing a reference")
        raw_box = payload["anchor_box"]
        if not isinstance(raw_box, list) or len(raw_box) != 4 or any(
            type(value) is not int for value in raw_box
        ):
            raise ValueError("Anchor needs four whole-number camera coordinates")
        box = Rect.from_value(raw_box, field_name="anchor")
        with self._lock:
            self._expire_preview_locked()
            if (self._active or self._pending_config is not None or self._error
                    or payload["revision"] != self._config_revision):
                raise ValueError("Finish testing/saving and confirm the current settings first")
            if (self._frame is None or self._last_frame_at is None
                    or time.monotonic() - self._last_frame_at > 5):
                raise ValueError("Wait for a fresh camera frame")
            display = self._saved_config.display
            boxes = list(display.digit_boxes)
            if display.colon_box:
                boxes.append(display.colon_box)
            changing = [Rect(display.roi.x + item.x, display.roi.y + item.y,
                             item.width, item.height) for item in boxes]
            try:
                self._alignment.capture(
                    self._frame, box,
                    profile_signature(optical_profile(self._saved_config)), changing,
                )
            except (OSError, cv2.error) as exc:
                raise ValueError("Could not store the anchor; current reference kept") from exc
        return self.state()

    def forget_alignment(self, payload: Mapping[str, object]) -> dict[str, object]:
        if set(payload) != {"confirmed"} or payload["confirmed"] is not True:
            raise ValueError("Confirm forgetting the alignment reference")
        with self._lock:
            try:
                self._alignment.clear()
            except OSError as exc:
                raise ValueError("Could not forget the reference; no calibration changed") from exc
        return self.state()

    def readability_feedback(self) -> dict[str, object]:
        # Share the pixel-advice lock to bound simultaneous snapshot CPU/memory.
        if not self._suggestion_lock.acquire(blocking=False):
            raise RuntimeError("A snapshot check is already running")
        try:
            with self._lock:
                self._expire_preview_locked()
                if self._pending_config is not None or self._error:
                    raise ValueError("Wait until camera settings are applied")
                if self._frame is None or self._last_frame_at is None:
                    raise ValueError("Wait for a camera frame")
                frame_age = time.monotonic() - self._last_frame_at
                if frame_age > 5:
                    raise ValueError("Wait for a fresh frame")
                config = self._preview_config
                roi = config.display.roi
                if roi.width * roi.height > MAX_DIAGNOSTIC_PIXELS:
                    raise ValueError("Display box exceeds the snapshot size limit")
                crop = SevenSegmentDecoder._crop(self._frame, roi, "display.roi").copy()
                revision, frame_number = self._config_revision, self._frame_version
                testing = self._active
            feedback = inspect_readability(crop, config)
            with self._lock:
                self._expire_preview_locked()
                if revision != self._config_revision:
                    raise ValueError("Settings changed during the snapshot check")
            return {**feedback, "revision": revision, "frame_number": frame_number,
                    "frame_age_seconds": round(frame_age, 1),
                    "mode": "test" if testing else "saved"}
        finally:
            self._suggestion_lock.release()

    def pixel_suggestions(self) -> dict[str, object]:
        if not self._suggestion_lock.acquire(blocking=False):
            raise RuntimeError("Pixel advice is already being prepared")
        try:
            with self._lock:
                self._expire_preview_locked()
                if self._active or self._pending_config is not None or self._error:
                    raise ValueError("Wait until saved settings are active and capture is healthy")
                if self._frame is None or self._last_frame_at is None:
                    raise ValueError("Wait for a camera frame")
                frame_age = time.monotonic() - self._last_frame_at
                if frame_age > 5:
                    raise ValueError("Wait for a fresh frame")
                config = self._saved_config
                if config.display.roi.width * config.display.roi.height > MAX_DIAGNOSTIC_PIXELS:
                    raise ValueError("Display box is too large for bounded pixel advice")
                crop = SevenSegmentDecoder._crop(
                    self._frame, config.display.roi, "display.roi",
                ).copy()
                revision = self._config_revision
                frame_number = self._frame_version
            suggestion = suggest_pixels(crop, config.display)
            with self._lock:
                if revision != self._config_revision or self._active:
                    raise ValueError("Settings changed while preparing advice; retry")
            return {
                **suggestion, "revision": revision, "frame_number": frame_number,
                "frame_age_seconds": round(frame_age, 1),
            }
        finally:
            self._suggestion_lock.release()

    def diagnostic_bundle(self) -> bytes:
        """Create a bounded, display-only evidence snapshot entirely in memory."""
        if not self._diagnostic_lock.acquire(blocking=False):
            raise RuntimeError("A diagnostic download is already being prepared; retry shortly")
        try:
            with self._lock:
                self._expire_preview_locked()
                if self._frame is None:
                    raise ValueError("No camera frame is available yet")
                config = self._preview_config
                roi = config.display.roi
                height, width = self._frame.shape[:2]
                if roi.x == 0 and roi.y == 0 and roi.width == width and roi.height == height:
                    raise ValueError("Select a display-only box before downloading diagnostics")
                if roi.width * roi.height > MAX_DIAGNOSTIC_PIXELS:
                    raise ValueError("Display box is too large for a bounded diagnostic download")
                crop = SevenSegmentDecoder._crop(self._frame, roi, "display.roi").copy()
                frame_version = self._frame_version
                frame_age = (
                    None if self._last_frame_at is None
                    else round(time.monotonic() - self._last_frame_at, 1)
                )
                testing = self._active
                pending = self._pending_config is not None
                accepted = (
                    self._result.stable_state.status
                    if self._result and self._result.stable_state else None
                )
            # Decode exactly this crop with exactly these settings; don't mix
            # images fetched on different frames or export any raw error text.
            display = replace(config.display, roi=Rect(0, 0, roi.width, roi.height))
            local_config = replace(config, display=display)
            result = FrameProcessor(local_config).process(crop)
            decoder = SevenSegmentDecoder(display)
            binary = decoder._threshold(decoder._select_channel(crop))
            overlay = render_diagnostic(
                crop, display, result.display, candidate_state=result.candidate_state,
            )
            mqtt = dict(self._mqtt_health()) if self._mqtt_health else {}
            report = {
                "format": "appliance-display-sensor-diagnostics", "version": 1,
                "created_utc": datetime.now(UTC).isoformat(),
                "mode": "test" if testing else "saved",
                "camera_settings_pending": pending,
                "frame_number": frame_version, "frame_age_seconds": frame_age,
                "crop_size": [roi.width, roi.height],
                "reading": _detection_payload(result, None),
                "semantics": {"countdown_format": config.semantics.countdown_format},
                "last_accepted_status": accepted,
                "alignment": self._alignment.snapshot(),
                "system": self._system_health.snapshot(),
                "mqtt": {
                    "enabled": bool(mqtt.get("enabled", config.mqtt.enabled)),
                    "connected": mqtt.get("connected") if isinstance(
                        mqtt.get("connected"), bool
                    ) else None,
                },
            }
            files = {
                "report.json": json.dumps(report, indent=2, allow_nan=False).encode("utf-8"),
                "optical-profile.json": json.dumps(
                    optical_profile(config), indent=2, allow_nan=False,
                ).encode("utf-8"),
                "README.txt": (
                    "Display-only diagnostic snapshot\n\n"
                    "Review all images before sharing: a misaligned display box can include "
                    "background or private information visible on the display.\n"
                    "Included: one display crop, its segment overlay, binary detection pixels, "
                    "recognition scores, optical settings, passive health and MQTT status.\n"
                    "Excluded: full camera frame, credentials, broker/network addresses, "
                    "device identity, filesystem paths, raw logs and error strings.\n"
                    "The optical profile describes the server's TESTED settings if test mode "
                    "was active, otherwise saved settings. Untested browser edits are excluded.\n"
                    "Frame age and pending camera settings are recorded in report.json. "
                    "This single snapshot is not evidence of long-term stability.\n"
                    "Images are newly encoded PNG pixels, without source EXIF metadata.\n"
                    "Digit/colon coordinates are relative to the cropped display. For offline "
                    "replay of display.png, use a separate test configuration with display ROI "
                    "[0,0,crop_width,crop_height]; do not replace your live camera profile.\n"
                    "The archive is generated on demand in memory, not stored on the Pi "
                    "or uploaded automatically.\n"
                ).encode("utf-8"),
            }
            # Serialize image encoding with live JPEG encoding to bound CPU/memory
            # on the reference Pi. No full-frame copy or log collection occurs.
            with self._encode_lock:
                for name, image in (("display.png", crop), ("segments.png", overlay),
                                    ("binary.png", binary)):
                    ok, encoded = cv2.imencode(".png", image)
                    if not ok:
                        raise RuntimeError("Could not encode a diagnostic display image")
                    files[name] = encoded.tobytes()
            output = BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, body in files.items():
                    # Fixed metadata avoids leaking host-local ZIP timestamps.
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, body)
            if output.tell() > MAX_DIAGNOSTIC_BYTES:
                raise ValueError("Diagnostic download exceeded its size limit")
            return output.getvalue()
        finally:
            self._diagnostic_lock.release()

    def import_profile(self, profile: Mapping[str, object]) -> dict[str, object]:
        # Strict versioned schema prevents silently importing a partial hybrid or
        # accepting private fields from a full application configuration file.
        json.dumps(profile, allow_nan=False)
        expected = self.export_profile()
        if set(profile) != set(expected):
            raise ValueError("Choose an exported optical profile, not a full configuration file")
        if profile["format"] != PROFILE_FORMAT:
            raise ValueError("This file is not an Appliance Display Sensor optical profile")
        if type(profile["version"]) is not int or profile["version"] not in (1, PROFILE_VERSION):
            raise ValueError("Unsupported optical profile version; no settings were changed")
        if profile["camera_geometry"] != expected["camera_geometry"]:
            raise ValueError(
                "Profile resolution or rotation differs from this camera; "
                "align/calibrate this camera instead"
            )
        calibration = profile["calibration"]
        if (
            not isinstance(calibration, Mapping)
            or set(calibration) != {"camera", "display", "stability"}
        ):
            raise ValueError("Profile must contain camera, display and stability calibration only")
        for section, fields in expected["calibration"].items():
            value = calibration[section]
            keys = set(fields)
            if section == "display":
                keys.discard("segment_sample_boxes")
                if profile["version"] == 2:
                    keys.add("segment_sample_boxes")
            if not isinstance(value, Mapping) or set(value) != keys:
                raise ValueError(f"Profile {section} fields are incomplete or unsupported")
        calibration = copy.deepcopy(calibration)
        if profile["version"] == 1:
            calibration["display"]["segment_sample_boxes"] = None
        response = self.preview(calibration)
        response["recovery_action"] = "import_test"
        return response

    def restore_previous(self) -> dict[str, object]:
        backup = self.config_path.with_suffix(self.config_path.suffix + ".bak")
        if not backup.is_file():
            raise ValueError("No previous saved calibration is available yet")
        # Only optical settings enter the normal validation/preview path. In
        # particular this cannot undo a recent broker-address or password change.
        response = self.import_profile(optical_profile(_backup_optics(backup)))
        response["recovery_action"] = "restore_test"
        return response

    def preview(self, updates: Mapping[str, object]) -> dict[str, object]:
        config, raw = build_candidate_config(self.config_path, updates)
        result = self._validate_latest_frame(config)
        with self._lock:
            self._preview_config = config
            self._preview_raw = raw
            self._pending_config = config
            self._active = True
            self._last_preview_change = time.monotonic()
            self._error = None
            self._config_revision += 1
            self._reset_reading_quality_locked()
            self._image_cache.clear()
            if result is not None:
                self._result = result
        return self.state()

    def save(self, updates: Mapping[str, object]) -> dict[str, object]:
        config, raw = build_candidate_config(self.config_path, updates)
        result = self._validate_latest_frame(config)
        backup = save_candidate_config(self.config_path, raw)
        with self._lock:
            self._saved_config = config
            self._preview_config = config
            self._preview_raw = raw
            self._pending_config = config
            self._active = False
            self._error = None
            self._config_revision += 1
            self._reset_reading_quality_locked()
            self._image_cache.clear()
            if result is not None:
                self._result = result
        payload = self.state()
        payload["backup"] = backup.name
        return payload

    def cancel(self) -> dict[str, object]:
        with self._lock:
            self._preview_config = self._saved_config
            self._preview_raw = None
            self._pending_config = self._saved_config
            self._active = False
            self._error = None
            self._config_revision += 1
            self._reset_reading_quality_locked()
            self._image_cache.clear()
        return self.state()

    def take_pending_config(self) -> AppConfig | None:
        return self.take_pending_config_with_revision()[0]

    def take_pending_config_with_revision(self) -> tuple[AppConfig | None, int]:
        """Capture the processing revision atomically with the settings handoff."""
        with self._lock:
            self._expire_preview_locked()
            pending = self._pending_config
            self._pending_config = None
            return pending, self._config_revision

    def _reset_reading_quality_locked(self) -> None:
        self._reading_quality.clear()
        self._reading_history.clear()
        self._quality_skip_frame = True

    def _expire_preview_locked(self) -> None:
        if (
            self._active
            and time.monotonic() - self._last_preview_change > PREVIEW_TIMEOUT_SECONDS
        ):
            self._preview_config = self._saved_config
            self._preview_raw = None
            self._pending_config = self._saved_config
            self._active = False
            self._error = "Unsaved preview expired after 10 minutes; saved settings restored"
            self._config_revision += 1
            self._reset_reading_quality_locked()
            self._image_cache.clear()

    def _validate_latest_frame(self, config: AppConfig) -> FrameResult | None:
        with self._lock:
            image = self._frame.copy() if self._frame is not None else None
        if image is None:
            roi = config.display.roi
            camera = config.input.camera
            if camera and (roi.x2 > camera.width or roi.y2 > camera.height):
                raise ValueError("Display box extends beyond the configured camera image")
            boxes = list(config.display.digit_boxes)
            if config.display.colon_box:
                boxes.append(config.display.colon_box)
            if any(box.x2 > roi.width or box.y2 > roi.height for box in boxes):
                raise ValueError("A digit or colon box extends beyond the whole-display box")
            return None
        try:
            return FrameProcessor(config).process(image)
        except (ValueError, RuntimeError) as exc:
            raise ValueError(f"settings do not fit the current camera frame: {exc}") from exc

    def image_jpeg(self, *, overlay: bool, binary: bool = False) -> bytes | None:
        # A Pi Zero cannot JPEG-encode a full frame independently for every
        # browser tab. Serialize encodes and cache at most once per camera frame.
        with self._encode_lock:
            with self._lock:
                key = ("binary" if binary else overlay, self._frame_version, self._config_revision)
                cached = self._image_cache.get(key)
                if cached is not None:
                    return cached
                image = self._frame.copy() if self._frame is not None else None
                config = self._preview_config
            if image is None:
                return None
            if binary:
                decoder = SevenSegmentDecoder(config.display)
                try:
                    crop = decoder._crop(image, config.display.roi, "display.roi")
                    image = decoder._threshold(decoder._select_channel(crop))
                except (ValueError, RuntimeError):
                    return None
            elif overlay:
                try:
                    result = FrameProcessor(config).process(image)
                    image = render_diagnostic(
                        image,
                        config.display,
                        result.display,
                        candidate_state=result.candidate_state,
                        stable_state=result.stable_state,
                    )
                except (ValueError, RuntimeError):
                    return None
            elif image.shape[1] > PREVIEW_MAX_WIDTH:
                scale = PREVIEW_MAX_WIDTH / image.shape[1]
                image = cv2.resize(
                    image,
                    (PREVIEW_MAX_WIDTH, round(image.shape[0] * scale)),
                    interpolation=cv2.INTER_AREA,
                )
            ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                return None
            body = encoded.tobytes()
            with self._lock:
                if key == (
                    "binary" if binary else overlay, self._frame_version, self._config_revision
                ):
                    self._image_cache[key] = body
            return body


class CalibrationServer:
    def __init__(self, host: str, port: int, session: CalibrationSession):
        handler = _handler_factory(session)
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="calibration-http",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=3)


def _handler_factory(session: CalibrationSession):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ApplianceDisplaySensor/0.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(
            self, status: int, body: bytes, content_type: str, *, filename: str | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: object) -> None:
            self._send(
                status,
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(
                    HTTPStatus.OK, CALIBRATION_HTML.encode("utf-8"), "text/html; charset=utf-8"
                )
                return
            if path == "/api/state":
                self._json(HTTPStatus.OK, session.state())
                return
            if path == "/api/profile":
                self._send(
                    HTTPStatus.OK,
                    json.dumps(session.export_profile(), indent=2, allow_nan=False).encode("utf-8"),
                    "application/json; charset=utf-8", filename="display-optical-profile.json",
                )
                return
            if path == "/api/readability-feedback":
                try:
                    response = session.readability_feedback()
                except (ValueError, RuntimeError, OSError, cv2.error):
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                        "error": "Check unavailable. Wait for a fresh frame and applied settings; "
                        "check the display box (maximum 1 million pixels), then retry.",
                    })
                else:
                    self._json(HTTPStatus.OK, response)
                return
            if path == "/api/suggestions":
                try:
                    response = session.pixel_suggestions()
                except (ValueError, RuntimeError, OSError, cv2.error):
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                        "error": "Advice unavailable. Finish testing, wait for a fresh camera "
                        "frame and check the display box (maximum 1 million pixels).",
                    })
                else:
                    self._json(HTTPStatus.OK, response)
                return
            if path == "/api/diagnostics.zip":
                try:
                    body = session.diagnostic_bundle()
                except (ValueError, RuntimeError, OSError, cv2.error):
                    # Don't expose exception text that may contain a path or
                    # library detail; failure must never fall back to a full frame.
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                        "error": "Diagnostic unavailable. Wait for a frame, check the "
                        "display-only box (maximum 1 million pixels), then retry.",
                    })
                else:
                    self._send(
                        HTTPStatus.OK, body, "application/zip", filename="display-diagnostics.zip",
                    )
                return
            if path in {"/api/frame.jpg", "/api/overlay.jpg", "/api/binary.jpg"}:
                image = session.image_jpeg(
                    overlay=path.endswith("overlay.jpg"), binary=path.endswith("binary.jpg")
                )
                if image is None:
                    self._json(
                        HTTPStatus.SERVICE_UNAVAILABLE, {"error": "camera frame unavailable"}
                    )
                else:
                    self._send(HTTPStatus.OK, image, "image/jpeg")
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            try:
                if (path in {"/api/alignment/reference", "/api/alignment/forget"}
                        and self.headers.get_content_type() != "application/json"):
                    raise ValueError("Alignment actions require an application/json request")
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("request is too large")
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("request body must be an object")
                if path == "/api/preview":
                    response = session.preview(payload)
                elif path == "/api/save":
                    response = session.save(payload)
                elif path == "/api/cancel":
                    response = session.cancel()
                elif path == "/api/profile/preview":
                    response = session.import_profile(payload)
                elif path == "/api/restore/preview":
                    response = session.restore_previous()
                elif path == "/api/alignment/reference":
                    response = session.alignment_reference(payload)
                elif path == "/api/alignment/forget":
                    response = session.forget_alignment(payload)
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                self._json(HTTPStatus.OK, response)
            except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    return Handler


CALIBRATION_HTML = Path(__file__).with_name("calibration_ui.html").read_text(encoding="utf-8")
