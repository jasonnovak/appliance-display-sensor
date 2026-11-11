"""Opt-in static-anchor drift warnings. Never changes OCR geometry or appliance state."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import zipfile
import zlib
from pathlib import Path
from tempfile import NamedTemporaryFile

import cv2
import numpy as np

from appliance_display_sensor.models import Rect

CHECK_INTERVAL = 5.0
SEARCH_MARGIN = 32
MAX_REFERENCE_BYTES = 96 * 1024
MOVE_PIXELS = 4


def profile_signature(profile: object) -> str:
    return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()


def _features(image: np.ndarray) -> np.ndarray:
    gray = np.max(image[:, :, :3], axis=2).astype(np.uint8) if image.ndim == 3 else image
    if float(np.percentile(gray, 99)) - float(np.percentile(gray, 1)) < 15:
        raise ValueError("anchor_too_dark_or_plain")
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    dx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)
    dy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    magnitude = cv2.magnitude(dx, dy)
    if float(magnitude.mean()) < 3:
        raise ValueError("anchor_too_dark_or_plain")
    return cv2.normalize(magnitude, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def _overlaps(first: Rect, second: Rect) -> bool:
    return (first.x < second.x2 + 8 and first.x2 > second.x - 8
            and first.y < second.y2 + 8 and first.y2 > second.y - 8)


class AlignmentMonitor:
    def __init__(self, path: Path):
        self.path = path
        self.box: Rect | None = None
        self.template: np.ndarray | None = None
        self.signature: str | None = None
        self.frame_size: tuple[int, int] | None = None
        self.status = "not_configured"
        self.reason = "choose_static_anchor"
        self.score: float | None = None
        self.shift: tuple[int, int] | None = None
        self.latched = False
        self._last_check: float | None = None
        self._moved_count = 0
        self._aligned_count = 0
        self._previous_shift: tuple[int, int] | None = None
        try:
            if path.exists():
                if path.stat().st_size > MAX_REFERENCE_BYTES:
                    raise ValueError("reference_too_large")
                # Bound decompressed arrays before np.load; no pickle or arbitrary shapes.
                with zipfile.ZipFile(path) as archive:
                    if (len(archive.infolist()) != 2
                            or set(archive.namelist()) != {"metadata.npy", "template.npy"}
                            or sum(item.file_size for item in archive.infolist()) > 40_000):
                        raise ValueError("invalid_reference")
                    for name in ("metadata.npy", "template.npy"):
                        with archive.open(name) as entry:
                            if np.lib.format.read_magic(entry) != (1, 0):
                                raise ValueError("invalid_reference")
                            shape, _, dtype = np.lib.format.read_array_header_1_0(entry)
                            if name == "template.npy":
                                if (len(shape) != 2 or any(not 32 <= n <= 160 for n in shape)
                                        or dtype != np.uint8):
                                    raise ValueError("invalid_reference")
                            elif shape != () or dtype.kind != "U" or dtype.itemsize > 4096:
                                raise ValueError("invalid_reference")
                with np.load(path, allow_pickle=False) as saved:
                    metadata = json.loads(str(saved["metadata"].item()))
                    template = saved["template"]
                box = Rect.from_value(metadata["anchor_box"], field_name="anchor")
                if (metadata["version"] != 1 or not 32 <= box.width <= 160
                        or not 32 <= box.height <= 160 or template.dtype != np.uint8
                        or template.shape != (box.height, box.width)):
                    raise ValueError("invalid_reference")
                size = tuple(metadata["frame_size"])
                if (len(size) != 2 or any(type(v) is not int or v < 1 for v in size)
                        or box.x2 > size[0] or box.y2 > size[1]
                        or not isinstance(metadata["signature"], str)
                        or len(metadata["signature"]) != 64):
                    raise ValueError("invalid_reference")
                self.box, self.template = box, template
                self.frame_size, self.signature = size, metadata["signature"]
                self.status, self.reason = "checking", "waiting_for_fresh_checks"
        except (ValueError, OSError, KeyError, TypeError, EOFError, zipfile.BadZipFile,
                RecursionError, RuntimeError, zlib.error):
            self.status, self.reason = "reference_unavailable", "replace_reference"

    def _match(self, image: np.ndarray) -> tuple[float, tuple[int, int], bool]:
        box = self.box
        if box is None or self.template is None:
            raise ValueError("no_reference")
        left, top = max(0, box.x - SEARCH_MARGIN), max(0, box.y - SEARCH_MARGIN)
        right = min(image.shape[1], box.x2 + SEARCH_MARGIN)
        bottom = min(image.shape[0], box.y2 + SEARCH_MARGIN)
        search = _features(image[top:bottom, left:right])
        result = cv2.matchTemplate(search, self.template, cv2.TM_CCOEFF_NORMED)
        if not np.isfinite(result).all():
            raise ValueError("ambiguous_anchor")
        _, best, _, location = cv2.minMaxLoc(result)
        x, y = location
        others = result.copy()
        others[max(0, y - 4):y + 5, max(0, x - 4):x + 5] = -1
        unique = best - float(others.max()) >= 0.06
        return best, (left + x - box.x, top + y - box.y), unique

    def capture(self, image: np.ndarray, box: Rect, signature: str,
                changing_boxes: list[Rect]) -> None:
        if (box.x < 0 or box.y < 0 or not 32 <= box.width <= 160 or not 32 <= box.height <= 160
                or box.x2 > image.shape[1] or box.y2 > image.shape[0]):
            raise ValueError("Choose an anchor 32–160 camera pixels wide/high inside the image")
        if any(_overlaps(box, region) for region in changing_boxes):
            raise ValueError("Keep the anchor at least 8 pixels away from digits and colon")
        try:
            template = _features(image[box.y:box.y2, box.x:box.x2])
        except ValueError as exc:
            raise ValueError(
                "Anchor is too dark/plain; choose visible fixed text or texture",
            ) from exc
        corners = cv2.goodFeaturesToTrack(template, 32, 0.1, 4)
        if corners is None or len(corners) < 6:
            raise ValueError("Choose visible fixed text or texture, not a plain or single edge")
        # Validate without replacing the current reference if capture is ambiguous.
        candidate = AlignmentMonitor.__new__(AlignmentMonitor)
        candidate.box, candidate.template = box, template
        score, shift, unique = candidate._match(image)
        if score < 0.75 or not unique or math.hypot(*shift) > 2:
            raise ValueError("Anchor is ambiguous; choose a more distinctive fixed feature")
        metadata = {"version": 1, "anchor_box": [box.x, box.y, box.width, box.height],
                    "frame_size": [image.shape[1], image.shape[0]], "signature": signature}
        temporary_path = None
        try:
            with NamedTemporaryFile(
                dir=self.path.parent, suffix=".alignment.tmp", delete=False,
            ) as f:
                temporary_path = Path(f.name)
                np.savez_compressed(f, metadata=json.dumps(metadata), template=template)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        self.box, self.template, self.signature = box, template, signature
        self.frame_size = (image.shape[1], image.shape[0])
        self.status, self.reason = "checking", "waiting_for_fresh_checks"
        self.score, self.shift, self._last_check = None, None, None
        self.latched = False
        self._moved_count = self._aligned_count = 0
        self._previous_shift = None

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        self.__init__(self.path)

    def update(self, image: np.ndarray, signature: str, *, testing: bool = False) -> None:
        if self.template is None:
            return
        if testing or signature != self.signature or self.frame_size != image.shape[1::-1]:
            self.status, self.reason = "needs_reference", "settings_changed_or_test_active"
            self._moved_count = self._aligned_count = 0
            self._last_check = None
            return
        now = time.monotonic()
        if self._last_check is not None and now - self._last_check < CHECK_INTERVAL:
            return
        self._last_check = now
        try:
            score, shift, unique = self._match(image)
            self.score = round(score, 3)
            if score < 0.75 or not unique:
                raise ValueError("anchor_not_distinct")
            self.shift = shift
            if math.hypot(*shift) > MOVE_PIXELS:
                consistent = (self._previous_shift is not None and math.dist(
                    self._previous_shift, shift,
                ) <= 3)
                self._moved_count = self._moved_count + 1 if consistent else 1
                self._aligned_count = 0
                self._previous_shift = shift
                if self._moved_count >= 3:
                    self.latched = True
                self.status = "moved" if self.latched else "checking"
                self.reason = "movement_confirmed" if self.latched else "confirming_shift"
            else:
                self._moved_count = 0
                self._aligned_count += 1
                self._previous_shift = None
                if self._aligned_count >= 2:
                    self.latched = False
                self.status = "moved" if self.latched else (
                    "aligned" if self._aligned_count >= 2 else "checking"
                )
                self.reason = "confirming_return" if self.latched else "anchor_matches"
        except (ValueError, cv2.error):
            self.status, self.reason = "uncheckable", "dark_blurred_missing_or_ambiguous_anchor"
            self.score = None
            self.shift = None
            self._moved_count = self._aligned_count = 0
            self._previous_shift = None

    def snapshot(self) -> dict[str, object]:
        age = None if self._last_check is None else round(time.monotonic() - self._last_check, 1)
        status = "stale" if age is not None and age > 15 else self.status
        return {
            "status": status, "reason": self.reason, "configured": self.template is not None,
            "anchor_box": [self.box.x, self.box.y, self.box.width, self.box.height]
            if self.box else None,
            "match_score": self.score, "shift_pixels": list(self.shift) if self.shift else None,
            "movement_latched": self.latched, "check_age_seconds": age,
        }
