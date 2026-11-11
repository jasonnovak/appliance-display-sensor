"""Explain measured snapshot symptoms without guessing exposure, focus or appliance state."""
from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

from appliance_display_sensor.config import AppConfig
from appliance_display_sensor.decoders.seven_segment import SevenSegmentDecoder
from appliance_display_sensor.models import Rect
from appliance_display_sensor.pipeline import FrameProcessor
from appliance_display_sensor.seven_segment_glyphs import GLYPH_SEGMENTS


def _crossed_edges(mask: np.ndarray, box: Rect) -> list[str]:
    """Require lit pixels on BOTH sides of a boundary, not just close to it."""
    height, width = mask.shape
    x, y, x2, y2 = box.x, box.y, box.x2, box.y2
    edges = []
    for name, inside, outside in (
        ("left", mask[y:y2, x], mask[y:y2, x-1] if x > 0 else None),
        ("right", mask[y:y2, x2-1], mask[y:y2, x2] if x2 < width else None),
        ("top", mask[y, x:x2], mask[y-1, x:x2] if y > 0 else None),
        ("bottom", mask[y2-1, x:x2], mask[y2, x:x2] if y2 < height else None),
    ):
        if outside is not None:
            crossing = inside & outside
            # Require a segment-length run; isolated dots (especially a nearby
            # colon), specks and separate patches are not a clipped segment.
            boundaries = np.flatnonzero(np.diff(np.r_[False, crossing, False]))
            longest = max(boundaries[1::2] - boundaries[::2], default=0)
            fraction = 0.18 if name in {"left", "right"} else 0.10
            if longest >= max(3, inside.size * fraction):
                edges.append(name)
    return edges


def inspect_readability(crop: np.ndarray, config: AppConfig) -> dict[str, object]:
    if crop.size == 0 or crop.shape[0] * crop.shape[1] > 1_000_000:
        raise ValueError("Use a bounded display crop")
    display = replace(config.display, roi=Rect(0, 0, crop.shape[1], crop.shape[0]))
    local = replace(config, display=display)
    result = FrameProcessor(local).process(crop)
    decoder = SevenSegmentDecoder(display)
    pixels = decoder._select_channel(crop)
    lit = decoder._threshold(pixels) > 0
    # A saturated colour channel can include a wide halo around a sharp LED.
    # Boundary hints require a bright core in luminance too, so ordinary blue
    # spill around cyan digits is not mistaken for a clipped physical segment.
    luminance = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    background, peak = (float(v) for v in np.percentile(luminance, [50, 99.5]))
    core = (
        lit & (luminance > background + 0.7 * (peak - background))
        if peak - background >= 20 else np.zeros_like(lit)
    )
    issues: list[dict[str, str]] = []

    def add(code: str, message: str, target: str = "display") -> None:
        issues.append({"code": code, "target": target, "message": message})

    crop_edges = [name for name, edge in (
        ("top", core[0]), ("bottom", core[-1]), ("left", core[:, 0]), ("right", core[:, -1]),
    ) if np.count_nonzero(edge) >= max(3, edge.size * 0.03)]
    if crop_edges:
        add("crop_edge", "Bright segment pixels reach the " + ", ".join(crop_edges) +
            " edge of the display crop. Check for cut-off segments and leave a little margin.")

    all_blank = result.display.valid and all(d.value is None for d in result.display.digits)
    any_light = False
    digit_metrics = []
    for index, (box, reading) in enumerate(zip(display.digit_boxes, result.display.digits), 1):
        region = decoder._crop(pixels, box, "digit")
        binary = decoder._crop(lit, box, "digit")
        fraction = float(binary.mean())
        any_light |= fraction >= 0.01
        low, high = (float(v) for v in np.percentile(region, [10, 99]))
        target = f"digit-{index}"
        label = f"Digit {index}"
        digit_metrics.append({"digit": index, "lit_percent": round(fraction * 100, 1),
                              "pixel_contrast": round(high - low, 1)})
        edges = _crossed_edges(core, box)
        if edges:
            add("digit_edge", label + ": bright segment pixels cross the " + ", ".join(edges) +
                " box edge. Check the full digit outline; glare or a neighbour "
                "may also cause this.",
                target)
        if fraction >= 0.70:
            add("filled_box", label + ": most of the box is treated as lit. Check for glare, "
                "a bright background or a cutoff that is too low. "
                "Inspect the black-and-white view.",
                target)
        elif reading.value is None and fraction >= 0.03:
            add("missed_light", label + ": the box contains lit pixels but its samples read blank. "
                "Check whether the sampling strips sit inside the actual segments.", target)
        elif not reading.valid or (
            reading.value is not None and
            frozenset(reading.active_segments) != GLYPH_SEGMENTS[reading.value]
        ):
            add("segment_fit", label + ": sampled segments do not clearly fit a supported digit. "
                "Check the overlay alignment and slant. If aligned edges look soft, check focus; "
                "if segments are missing, check exposure and frame combining.", target)
        if fraction < 0.01 and high - low >= 20 and display.threshold_method == "fixed":
            if high <= display.threshold_value:
                add("cutoff_high", label + ": visible contrast falls below the fixed cutoff. "
                    "If this digit is lit on the appliance, try Find pixel settings or check the "
                    "colour channel before increasing exposure.", target)

    if all_blank:
        add("blank", "The samples read blank. If the appliance display is off, leave the settings "
            "alone. If it is lit, check the crop, colour channel and cutoff "
            "with a known countdown.")
    elif result.display.valid and result.candidate_state.status == "unknown":
        add("format", "The segment patterns are recognized but do not form a valid countdown or "
            "configured terminal message. Check Countdown format and missing digit positions.")
    if not any_light and not all_blank:
        add("little_light", "Very few pixels pass the cutoff. Check that the display is lit and "
            "inside the boxes before changing camera brightness.")

    return {
        "text": result.candidate_state.display_text,
        "status": result.candidate_state.status,
        "countdown_format": config.semantics.countdown_format,
        "colon_role": (
            "diagnostic_only" if config.semantics.countdown_format == "H:MM" else "format"
        ),
        "issues": issues[:12], "additional_issues": max(0, len(issues) - 12),
        "digit_metrics": digit_metrics,
        "summary": ("Check these possible causes." if issues else
                    "No obvious crop or pixel symptoms found in this snapshot."),
        "limitation": "Compare with the appliance itself. One image cannot confirm physical "
                      "alignment, focus, or reliable operation across a full cycle.",
    }
