"""Conservative, snapshot-only pixel-setting advice; never applies configuration."""
from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

from appliance_display_sensor.config import DisplayConfig
from appliance_display_sensor.decoders.seven_segment import SevenSegmentDecoder
from appliance_display_sensor.models import DecodedDisplay, Rect
from appliance_display_sensor.seven_segment_glyphs import GLYPH_SEGMENTS


def _exact_reading(reading: DecodedDisplay) -> bool:
    return bool(reading.valid and reading.text) and all(
        frozenset(digit.active_segments) == GLYPH_SEGMENTS[digit.value]
        for digit in reading.digits
    )


def suggest_pixels(crop: np.ndarray, display: DisplayConfig) -> dict[str, object]:
    """Try at most ten fixed-cutoff candidates on an already bounded display crop.

    Otsu separates dark/lit pixels; also try the midpoint of those class means.
    Exact segment patterns and agreement between plausible candidates are required.
    Match scores rank sampling fit, not the probability that a value is correct.
    """
    local = replace(display, roi=Rect(0, 0, crop.shape[1], crop.shape[0]))
    current = SevenSegmentDecoder(local).decode(crop)
    candidates: list[dict[str, object]] = []
    checked = 0
    for channel in dict.fromkeys((display.channel, "blue", "green", "red", "gray", "max")):
        decoder = SevenSegmentDecoder(replace(local, channel=channel))
        pixels = decoder._select_channel(crop)
        cutoff, binary = cv2.threshold(pixels, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        lit = pixels[binary > 0]
        dark = pixels[binary == 0]
        if not lit.size or not dark.size:
            continue
        if float(lit.mean()) - float(dark.mean()) < 20:
            continue
        midpoint = round((float(lit.mean()) + float(dark.mean())) / 2)
        # Prefer the interior midpoint on equal match scores, rather than a
        # cutoff sitting directly on the background brightness/noise floor.
        for value in dict.fromkeys((midpoint, int(cutoff))):
            checked += 1
            settings = replace(
                local, channel=channel, threshold_method="fixed", threshold_value=value,
            )
            reading = SevenSegmentDecoder(settings).decode(crop)
            if not _exact_reading(reading):
                continue
            candidates.append({
                "channel": channel, "threshold_method": "fixed", "threshold_value": value,
                "text": reading.text, "confidence": round(reading.confidence, 4),
            })
    base = {
        "current_text": current.text, "current_confidence": round(current.confidence, 4),
        "candidates_checked": checked, "valid_candidates": len(candidates),
        "recommendation": None,
    }
    if not candidates:
        return {**base, "reason": "no_clear_reading"}
    candidates.sort(key=lambda item: float(item["confidence"]), reverse=True)
    best = candidates[0]
    # Do not silently choose between equally plausible but different values, or
    # propose replacing an already exact reading with a different value.
    plausible = {item["text"] for item in candidates
                 if float(item["confidence"]) >= float(best["confidence"]) - 0.03}
    if len(plausible) != 1 or (_exact_reading(current) and current.text != best["text"]):
        return {**base, "reason": "disagreement"}
    if _exact_reading(current) and current.confidence >= float(best["confidence"]) - 0.01:
        return {**base, "reason": "current_settings_fit"}
    return {**base, "reason": "suggested", "recommendation": best}
