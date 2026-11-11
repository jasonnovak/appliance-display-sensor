from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from appliance_display_sensor.config import DisplayConfig
from appliance_display_sensor.decoders.seven_segment import segment_rectangles
from appliance_display_sensor.models import ApplianceState, DecodedDisplay, Rect


def _draw_rect(image: np.ndarray, rect: Rect, color: tuple[int, int, int], thickness: int) -> None:
    cv2.rectangle(
        image,
        (rect.x, rect.y),
        (rect.x2 - 1, rect.y2 - 1),
        color,
        thickness,
    )


def render_diagnostic(
    image: np.ndarray,
    config: DisplayConfig,
    display: DecodedDisplay,
    *,
    candidate_state: ApplianceState | None = None,
    stable_state: ApplianceState | None = None,
) -> np.ndarray:
    """Return a privacy-conscious overlay cropped to the configured display ROI."""

    roi = config.roi
    if roi.x2 > image.shape[1] or roi.y2 > image.shape[0]:
        raise ValueError(f"display.roi {roi} falls outside image bounds")
    overlay = image[roi.y : roi.y2, roi.x : roi.x2].copy()

    for index, (box, reading) in enumerate(
        zip(config.digit_boxes, display.digits, strict=True)
    ):
        box_color = (80, 220, 80) if reading.valid else (40, 40, 230)
        _draw_rect(overlay, box, box_color, 1)

        samples = segment_rectangles(
            box.width,
            box.height,
            config.segment_thickness_ratio,
            config.segment_slant_ratio,
            config.segment_sample_boxes,
        )
        for segment, sample in samples.items():
            absolute = Rect(
                box.x + sample.x,
                box.y + sample.y,
                sample.width,
                sample.height,
            )
            active = reading.segment_scores[segment] >= config.min_segment_fill
            color = (255, 210, 40) if active else (90, 90, 90)
            _draw_rect(overlay, absolute, color, 1)

        value = "blank" if reading.value is None else reading.value
        cv2.putText(
            overlay,
            f"{index}:{value} {reading.confidence:.2f}",
            (box.x, min(overlay.shape[0] - 4, box.y + 14)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            box_color,
            1,
            cv2.LINE_AA,
        )

    if config.colon_box is not None:
        colon_color = (255, 210, 40) if display.colon_on else (90, 90, 90)
        _draw_rect(overlay, config.colon_box, colon_color, 1)

    candidate_text = candidate_state.display_text if candidate_state is not None else display.text
    candidate_status = candidate_state.status if candidate_state is not None else "unmapped"
    stable_status = stable_state.status if stable_state is not None else "pending"
    summary = (
        f"read={candidate_text or 'blank'} "
        f"candidate={candidate_status} stable={stable_status}"
    )
    cv2.putText(
        overlay,
        summary,
        (4, max(12, overlay.shape[0] - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.4,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return overlay


def save_diagnostic(path: str | Path, image: np.ndarray) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), image):
        raise RuntimeError(f"could not write diagnostic image: {output_path}")
    return output_path
