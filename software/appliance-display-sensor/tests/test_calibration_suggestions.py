from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

import numpy as np

from appliance_display_sensor.calibration_suggestions import suggest_pixels
from appliance_display_sensor.config import DisplayConfig
from appliance_display_sensor.models import Rect
from appliance_display_sensor.synthetic import render_display


class PixelSuggestionTests(unittest.TestCase):
    def setUp(self):
        self.display = DisplayConfig(
            decoder="seven_segment", roi=Rect(50, 30, 420, 150),
            digit_boxes=(Rect(25, 15, 70, 120), Rect(175, 15, 70, 120), Rect(285, 15, 70, 120)),
            colon_box=Rect(120, 38, 24, 74), colon_after=1,
            channel="red", threshold_method="fixed", threshold_value=250,
            min_segment_fill=0.30, colon_min_fill=0.01, min_digit_confidence=0.72,
            segment_thickness_ratio=0.12, segment_slant_ratio=0,
            allowed_glyphs=(None, "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "E", "n", "d"),
        )

    def image(self, digits=(1, 0, 5), colon_on=True):
        image = render_display(
            size=(420, 150), digit_boxes=self.display.digit_boxes, digits=digits,
            colon_box=self.display.colon_box, colon_on=colon_on,
        )
        # Blue LED with a dim background, below the saved cutoff and invisible
        # in the saved red channel. No full camera frame is needed.
        image[:, :, 1:] = 0
        image[:, :, 0] = np.where(image[:, :, 0] > 5, 180, 5)
        return image

    def test_recovers_blue_countdown_without_mutating_input_or_config(self):
        image = self.image()
        original = image.copy()
        result = suggest_pixels(image, self.display)
        self.assertEqual(result["reason"], "suggested")
        advice = result["recommendation"]
        self.assertEqual(advice["channel"], "blue")
        self.assertEqual(advice["text"], "1:05")
        self.assertEqual(advice["threshold_method"], "fixed")
        self.assertLess(advice["threshold_value"], 180)
        self.assertGreater(advice["threshold_value"], 5)
        self.assertLessEqual(result["candidates_checked"], 10)
        np.testing.assert_array_equal(image, original)
        self.assertEqual(self.display.channel, "red")

    def test_correct_channel_with_an_overly_high_cutoff_can_get_advice(self):
        result = suggest_pixels(self.image(), replace(self.display, channel="blue"))
        self.assertEqual(result["reason"], "suggested")
        self.assertEqual(result["recommendation"]["text"], "1:05")

    def test_good_saved_settings_do_not_get_needless_advice(self):
        result = suggest_pixels(
            self.image(), replace(self.display, channel="blue", threshold_value=80),
        )
        self.assertEqual(result["reason"], "current_settings_fit")
        self.assertIsNone(result["recommendation"])

    def test_blank_and_low_contrast_frames_do_not_produce_advice(self):
        for image in (np.zeros((150, 420, 3), np.uint8),
                      np.full((150, 420, 3), 240, np.uint8)):
            result = suggest_pixels(image, self.display)
            self.assertEqual(result["reason"], "no_clear_reading")
            self.assertIsNone(result["recommendation"])
        image = self.image()
        image[:, :, 0] = np.where(image[:, :, 0] > 5, 14, 5)
        self.assertIsNone(suggest_pixels(image, self.display)["recommendation"])

    def test_minute_only_and_terminal_text_can_be_suggested(self):
        for digits, text in (((None, 4, 1), "41"), (("E", "n", "d"), "End")):
            result = suggest_pixels(self.image(digits, False), self.display)
            self.assertEqual(result["recommendation"]["text"], text)

    def test_disagreeing_exact_channels_are_not_silently_selected(self):
        blue = self.image((None, 4, 1), False)
        other = self.image((None, 5, 2), False)
        blue[:, :, 2] = other[:, :, 0]
        result = suggest_pixels(blue, self.display)
        self.assertEqual(result["reason"], "disagreement")
        self.assertIsNone(result["recommendation"])

    def test_an_existing_exact_value_cannot_be_replaced_with_a_different_one(self):
        image = self.image((None, 4, 1), False)
        # Existing exact value remains authoritative even if another channel's
        # confidence is higher. A mismatch must be reviewed by a human.
        other = self.image((None, 5, 2), False)
        image[:, :, 2] = other[:, :, 0]
        result = suggest_pixels(image, replace(self.display, threshold_value=80))
        self.assertEqual(result["reason"], "disagreement")
        self.assertIsNone(result["recommendation"])

    def test_approximate_segment_matches_are_not_offered(self):
        with patch('appliance_display_sensor.calibration_suggestions._exact_reading',
                   return_value=False):
            self.assertEqual(
                suggest_pixels(self.image(), self.display)["reason"], "no_clear_reading",
            )


if __name__ == "__main__":
    unittest.main()
