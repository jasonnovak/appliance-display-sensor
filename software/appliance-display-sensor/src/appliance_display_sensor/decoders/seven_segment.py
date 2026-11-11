from __future__ import annotations

import cv2
import numpy as np

from appliance_display_sensor.config import DisplayConfig
from appliance_display_sensor.models import DecodedDisplay, DigitReading, Rect
from appliance_display_sensor.seven_segment_glyphs import GLYPH_SEGMENTS, SEGMENT_ORDER


def segment_rectangles(
    width: int,
    height: int,
    thickness_ratio: float,
    slant_ratio: float = 0.0,
    sample_boxes: tuple[tuple[float, float, float, float], ...] | None = None,
) -> dict[str, Rect]:
    """Return sampling rectangles for a conventional or horizontally slanted digit.

    A positive slant ratio models segments that shift left from the top of the
    digit toward the bottom. A negative value models the opposite direction.
    """

    if sample_boxes is not None:
        rectangles = {}
        for name, (x, y, w, h) in zip("abcdefg", sample_boxes):
            left, top = round(x * width), round(y * height)
            right, bottom = round((x + w) * width), round((y + h) * height)
            rectangles[name] = Rect(left, top, right - left, bottom - top)
        return rectangles

    thickness = max(2, int(round(width * thickness_ratio)))
    bottom_delta = -int(round(width * slant_ratio))
    base_width = max(thickness + 2, width - abs(bottom_delta))
    top_origin = max(0, -bottom_delta)
    horizontal_width = max(2, int(round(base_width * 0.52)))
    horizontal_x = int(round((base_width - horizontal_width) / 2))
    vertical_height = max(2, int(round(height * 0.25)))
    left_x = int(round(base_width * 0.13 - thickness / 2))
    right_x = int(round(base_width * 0.87 - thickness / 2))

    def slant_at(center_y: float) -> int:
        # Anchor the top horizontal segment and apply the full configured shift
        # at the bottom horizontal segment.
        progress = min(1.0, max(0.0, (center_y - 0.08) / 0.84))
        return int(round(top_origin + bottom_delta * progress))

    def clamped_x(value: int, rect_width: int) -> int:
        return min(max(0, value), max(0, width - rect_width))

    def horizontal(center_y: float) -> Rect:
        y = int(round(height * center_y - thickness / 2))
        x = clamped_x(horizontal_x + slant_at(center_y), horizontal_width)
        return Rect(x, max(0, y), horizontal_width, thickness)

    def vertical(center_x: int, start_y: float) -> Rect:
        y = int(round(height * start_y))
        center_y = start_y + (vertical_height / height) / 2
        x = clamped_x(center_x + slant_at(center_y), thickness)
        return Rect(x, y, thickness, vertical_height)

    return {
        "a": horizontal(0.08),
        "b": vertical(right_x, 0.16),
        "c": vertical(right_x, 0.59),
        "d": horizontal(0.92),
        "e": vertical(left_x, 0.59),
        "f": vertical(left_x, 0.16),
        "g": horizontal(0.50),
    }


class SevenSegmentDecoder:
    """Decode a calibrated, fixed seven-segment display region."""

    def __init__(self, config: DisplayConfig):
        self.config = config
        if not config.allowed_glyphs:
            raise ValueError("display.allowed_glyphs must not be empty")

    def decode(self, image: np.ndarray) -> DecodedDisplay:
        display = self._crop(image, self.config.roi, "display.roi")
        channel = self._select_channel(display)
        binary = self._threshold(channel)

        digits = tuple(
            self._decode_digit(binary, box, index)
            for index, box in enumerate(self.config.digit_boxes)
        )

        colon_on = False
        colon_confidence = 1.0
        if self.config.colon_box is not None:
            colon_region = self._crop(binary, self.config.colon_box, "display.colon_box")
            colon_fill = float(np.mean(colon_region > 0))
            colon_on = colon_fill >= self.config.colon_min_fill
            if colon_on:
                colon_confidence = min(1.0, colon_fill / self.config.colon_min_fill)
            else:
                colon_confidence = max(0.0, 1.0 - colon_fill / self.config.colon_min_fill)

        valid = all(digit.valid for digit in digits)
        confidence_values = [digit.confidence for digit in digits]
        if self.config.colon_box is not None:
            confidence_values.append(colon_confidence)
        confidence = min(confidence_values) if confidence_values else 0.0

        return DecodedDisplay(
            digits=digits,
            colon_on=colon_on,
            colon_after=self.config.colon_after,
            colon_confidence=colon_confidence,
            confidence=confidence,
            valid=valid,
        )

    def _select_channel(self, image: np.ndarray) -> np.ndarray:
        if image.ndim == 2:
            return image
        if image.ndim != 3 or image.shape[2] < 3:
            raise ValueError("input image must be grayscale or BGR")

        channel = self.config.channel
        if channel == "blue":
            return image[:, :, 0]
        if channel == "green":
            return image[:, :, 1]
        if channel == "red":
            return image[:, :, 2]
        if channel == "max":
            return np.max(image[:, :, :3], axis=2).astype(np.uint8)
        return cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)

    def _threshold(self, channel: np.ndarray) -> np.ndarray:
        if self.config.threshold_method == "otsu":
            _, binary = cv2.threshold(channel, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return binary
        _, binary = cv2.threshold(
            channel,
            self.config.threshold_value,
            255,
            cv2.THRESH_BINARY,
        )
        return binary

    def _decode_digit(self, binary: np.ndarray, box: Rect, index: int) -> DigitReading:
        digit_region = self._crop(binary, box, f"display.digit_boxes[{index}]")
        sample_rects = segment_rectangles(
            digit_region.shape[1],
            digit_region.shape[0],
            self.config.segment_thickness_ratio,
            self.config.segment_slant_ratio,
            self.config.segment_sample_boxes,
        )
        scores = {
            segment: float(np.mean(self._crop(digit_region, rect, f"segment {segment}") > 0))
            for segment, rect in sample_rects.items()
        }
        active = tuple(
            segment for segment in SEGMENT_ORDER if scores[segment] >= self.config.min_segment_fill
        )

        candidates: list[tuple[float, str | None]] = []
        for value in self.config.allowed_glyphs:
            expected_on = GLYPH_SEGMENTS[value]
            quality = sum(
                scores[segment] if segment in expected_on else 1.0 - scores[segment]
                for segment in SEGMENT_ORDER
            ) / len(SEGMENT_ORDER)
            candidates.append((quality, value))

        candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        best_quality, best_value = candidates[0]
        return DigitReading(
            value=best_value,
            confidence=best_quality,
            valid=best_quality >= self.config.min_digit_confidence,
            active_segments=active,
            segment_scores=scores,
        )

    @staticmethod
    def _crop(image: np.ndarray, rect: Rect, field_name: str) -> np.ndarray:
        if rect.x2 > image.shape[1] or rect.y2 > image.shape[0]:
            raise ValueError(
                f"{field_name} {rect} falls outside image bounds "
                f"{image.shape[1]}x{image.shape[0]}"
            )
        return image[rect.y : rect.y2, rect.x : rect.x2]
