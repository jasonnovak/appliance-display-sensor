from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime

from appliance_display_sensor.duration import state_from_display
from appliance_display_sensor.models import DecodedDisplay, DigitReading


def decoded_text(text: str, *, colon: bool = False) -> DecodedDisplay:
    digits = tuple(
        DigitReading(
            value=None if character == " " else character,
            confidence=1.0,
            valid=True,
            active_segments=(),
            segment_scores={},
        )
        for character in text
    )
    return DecodedDisplay(
        digits=digits,
        colon_on=colon,
        colon_after=1,
        colon_confidence=1.0,
        confidence=1.0,
        valid=True,
    )


class DurationSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.observed_at = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

    def hmm(self, text, *, colon=False):
        return state_from_display(
            decoded_text(text, colon=colon), no_colon_unit="minutes",
            countdown_format="H:MM", terminal_texts=("End",), now=self.observed_at,
        )

    def test_fixed_layout_all_hour_minute_values_ignore_colon(self):
        for hours in range(10):
            for minutes in range(60):
                for colon in (False, True):
                    text = f"{hours}{minutes:02}"
                    with self.subTest(text=text, colon=colon):
                        state = self.hmm(text, colon=colon)
                        self.assertEqual(state.remaining_minutes, hours * 60 + minutes)
                        self.assertEqual(state.display_text, f"{hours}:{minutes:02}")
                        self.assertEqual(state.status, "running")

    def test_leading_blanks_and_terminal_ignore_phantom_colon(self):
        for colon in (False, True):
            for text, expected in ((" 21", 21), (" 01", 1), ("  1", 1), ("  0", 0)):
                state = self.hmm(text, colon=colon)
                self.assertEqual(state.remaining_minutes, expected)
                self.assertEqual(state.display_text, text.strip())
                self.assertEqual(state.status, "running")
            end = self.hmm("End", colon=colon)
            self.assertEqual(end.status, "complete")
            self.assertEqual(end.display_text, "End")

    def test_invalid_minutes_gaps_blank_and_wrong_box_count_remain_unknown(self):
        for text in ("160", "199", " 99", "1 2", "12 ", " 2 ", "   ", "En ", "21", "1123"):
            for colon in (False, True):
                with self.subTest(text=text, colon=colon):
                    state = self.hmm(text, colon=colon)
                    self.assertEqual(state.status, "unknown")
                    self.assertIsNone(state.remaining_minutes)

    def test_invalid_digit_cannot_become_terminal_or_countdown(self):
        for text in ("End", "112"):
            display = decoded_text(text)
            display = replace(display, digits=(replace(display.digits[0], valid=False),
                                               *display.digits[1:]))
            state = state_from_display(display, no_colon_unit="minutes",
                                       countdown_format="H:MM", terminal_texts=("End",))
            self.assertEqual(state.status, "unknown")

    def test_hmm_confidence_and_unit_do_not_depend_on_colon(self):
        display = replace(decoded_text(" 21"), colon_confidence=0.01, confidence=0.01)
        state = state_from_display(display, no_colon_unit="seconds", countdown_format="H:MM")
        self.assertEqual(state.remaining_minutes, 21)
        self.assertEqual(state.confidence, 1.0)

    def test_default_auto_preserves_three_digit_minutes_and_seconds(self):
        self.assertEqual(state_from_display(decoded_text("112"),
                                            no_colon_unit="minutes").remaining_minutes, 112)
        self.assertEqual(state_from_display(decoded_text("112", colon=True),
                                            no_colon_unit="minutes").remaining_minutes, 72)
        self.assertEqual(state_from_display(decoded_text("121"),
                                            no_colon_unit="seconds").remaining_minutes, 3)

    def test_numeric_zero_is_not_completion_by_default(self) -> None:
        state = state_from_display(
            decoded_text("0"),
            no_colon_unit="minutes",
            terminal_texts=("End",),
            now=self.observed_at,
        )

        self.assertEqual(state.status, "running")
        self.assertTrue(state.running)
        self.assertEqual(state.remaining_minutes, 0)
        self.assertEqual(state.estimated_finish, self.observed_at)

    def test_numeric_zero_can_be_configured_as_terminal(self) -> None:
        state = state_from_display(
            decoded_text("0"),
            no_colon_unit="minutes",
            terminal_texts=("0",),
            now=self.observed_at,
        )

        self.assertEqual(state.status, "complete")
        self.assertFalse(state.running)
        self.assertEqual(state.remaining_minutes, 0)


if __name__ == "__main__":
    unittest.main()
