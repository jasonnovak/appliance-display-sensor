from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime

from appliance_display_sensor.config import DisplayConfig
from appliance_display_sensor.decoders import SevenSegmentDecoder
from appliance_display_sensor.duration import parse_remaining_minutes, state_from_display
from appliance_display_sensor.models import Rect
from appliance_display_sensor.seven_segment_glyphs import DEFAULT_ALLOWED_GLYPHS
from appliance_display_sensor.synthetic import parse_synthetic_text, render_display


DIGIT_BOXES = (
    Rect(25, 15, 70, 120),
    Rect(175, 15, 70, 120),
    Rect(285, 15, 70, 120),
)
COLON_BOX = Rect(120, 38, 24, 74)


def display_config() -> DisplayConfig:
    return DisplayConfig(
        decoder="seven_segment",
        roi=Rect(0, 0, 420, 150),
        digit_boxes=DIGIT_BOXES,
        colon_box=COLON_BOX,
        colon_after=1,
        channel="blue",
        threshold_method="fixed",
        threshold_value=160,
        min_segment_fill=0.30,
        colon_min_fill=0.02,
        min_digit_confidence=0.72,
        segment_thickness_ratio=0.12,
        segment_slant_ratio=0.0,
        allowed_glyphs=DEFAULT_ALLOWED_GLYPHS,
    )


class SevenSegmentDecoderTests(unittest.TestCase):
    def test_generates_named_blank_fixture(self) -> None:
        glyphs, colon_on = parse_synthetic_text("blank", len(DIGIT_BOXES))

        self.assertEqual(glyphs, [None, None, None])
        self.assertFalse(colon_on)

    def test_decodes_hours_and_minutes_with_colon(self) -> None:
        config = display_config()
        image = render_display(
            size=(420, 150),
            digit_boxes=DIGIT_BOXES,
            digits=(1, 2, 3),
            colon_box=COLON_BOX,
            colon_on=True,
        )

        decoded = SevenSegmentDecoder(config).decode(image)

        self.assertTrue(decoded.valid)
        self.assertEqual(decoded.text, "1:23")
        self.assertEqual(parse_remaining_minutes(decoded, no_colon_unit="minutes"), 83)

    def test_decodes_reference_hour_minute_format(self) -> None:
        config = display_config()
        image = render_display(
            size=(420, 150),
            digit_boxes=DIGIT_BOXES,
            digits=(1, 1, 0),
            colon_box=COLON_BOX,
            colon_on=True,
        )

        decoded = SevenSegmentDecoder(config).decode(image)

        self.assertEqual(decoded.text, "1:10")
        self.assertEqual(parse_remaining_minutes(decoded, no_colon_unit="minutes"), 70)

    def test_ignores_blank_leading_position_for_minute_display(self) -> None:
        config = display_config()
        image = render_display(
            size=(420, 150),
            digit_boxes=DIGIT_BOXES,
            digits=(None, 4, 1),
            colon_box=COLON_BOX,
            colon_on=False,
        )

        decoded = SevenSegmentDecoder(config).decode(image)
        state = state_from_display(
            decoded,
            no_colon_unit="minutes",
            now=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(decoded.text, "41")
        self.assertEqual(state.remaining_minutes, 41)
        self.assertEqual(state.status, "running")
        self.assertEqual(state.estimated_finish, datetime(2026, 8, 28, 12, 41, tzinfo=UTC))

    def test_decodes_a_profile_with_slanted_segments(self) -> None:
        config = replace(display_config(), segment_slant_ratio=0.18)
        image = render_display(
            size=(420, 150),
            digit_boxes=DIGIT_BOXES,
            digits=(None, 4, 1),
            colon_box=COLON_BOX,
            colon_on=False,
            slant_ratio=0.18,
        )

        decoded = SevenSegmentDecoder(config).decode(image)

        self.assertTrue(decoded.valid)
        self.assertEqual(decoded.text, "41")

    def test_blank_display_is_unknown_not_an_appliance_type_assumption(self) -> None:
        config = display_config()
        image = render_display(
            size=(420, 150),
            digit_boxes=DIGIT_BOXES,
            digits=(None, None, None),
            colon_box=COLON_BOX,
            colon_on=False,
        )

        decoded = SevenSegmentDecoder(config).decode(image)
        state = state_from_display(decoded, no_colon_unit="minutes")

        self.assertIsNone(decoded.text)
        self.assertEqual(state.status, "unknown")
        self.assertFalse(state.running)

    def test_decodes_end_as_configured_terminal_state(self) -> None:
        config = display_config()
        image = render_display(
            size=(420, 150),
            digit_boxes=DIGIT_BOXES,
            digits=("E", "n", "d"),
            colon_box=COLON_BOX,
            colon_on=False,
        )

        decoded = SevenSegmentDecoder(config).decode(image)
        state = state_from_display(
            decoded,
            no_colon_unit="minutes",
            terminal_texts=("End",),
            now=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(decoded.text, "End")
        self.assertEqual(state.status, "complete")
        self.assertEqual(state.remaining_minutes, 0)
        self.assertFalse(state.running)


if __name__ == "__main__":
    unittest.main()
