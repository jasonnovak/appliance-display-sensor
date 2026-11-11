from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from appliance_display_sensor.decoders.seven_segment import segment_rectangles
from appliance_display_sensor.models import Rect
from appliance_display_sensor.seven_segment_glyphs import GLYPH_SEGMENTS, normalize_glyph


def render_display(
    *,
    size: tuple[int, int],
    digit_boxes: Sequence[Rect],
    digits: Sequence[str | int | None],
    colon_box: Rect | None = None,
    colon_on: bool = False,
    thickness_ratio: float = 0.12,
    slant_ratio: float = 0.0,
    foreground_bgr: tuple[int, int, int] = (255, 30, 20),
    background_bgr: tuple[int, int, int] = (5, 5, 5),
) -> np.ndarray:
    """Render a deterministic test image that uses the decoder's sampling geometry."""

    width, height = size
    if len(digit_boxes) != len(digits):
        raise ValueError("digit_boxes and digits must have equal lengths")
    image = np.full((height, width, 3), background_bgr, dtype=np.uint8)

    for box, value in zip(digit_boxes, digits, strict=True):
        glyph = normalize_glyph(value)
        active = GLYPH_SEGMENTS[glyph]
        for segment, sample in segment_rectangles(
            box.width,
            box.height,
            thickness_ratio,
            slant_ratio,
        ).items():
            if segment not in active:
                continue
            top_left = (box.x + sample.x, box.y + sample.y)
            bottom_right = (box.x + sample.x2 - 1, box.y + sample.y2 - 1)
            cv2.rectangle(image, top_left, bottom_right, foreground_bgr, thickness=-1)

    if colon_on and colon_box is not None:
        radius = max(2, min(colon_box.width, colon_box.height) // 7)
        center_x = colon_box.x + colon_box.width // 2
        upper_y = colon_box.y + colon_box.height // 3
        lower_y = colon_box.y + (colon_box.height * 2) // 3
        cv2.circle(image, (center_x, upper_y), radius, foreground_bgr, thickness=-1)
        cv2.circle(image, (center_x, lower_y), radius, foreground_bgr, thickness=-1)

    return image


def parse_synthetic_text(text: str, positions: int) -> tuple[list[str | None], bool]:
    cleaned = text.strip()
    if cleaned.casefold() == "blank":
        return [None] * positions, False
    if cleaned.count(":") > 1:
        raise ValueError("synthetic text may contain at most one colon")
    colon_on = ":" in cleaned
    glyph_text = cleaned.replace(":", "")
    if not glyph_text:
        raise ValueError("synthetic text must contain at least one glyph")
    if len(glyph_text) > positions:
        raise ValueError(f"synthetic text has more than {positions} digit positions")
    glyphs: list[str | None] = [None] * (positions - len(glyph_text))
    glyphs.extend(normalize_glyph(character) for character in glyph_text)
    return glyphs, colon_on
