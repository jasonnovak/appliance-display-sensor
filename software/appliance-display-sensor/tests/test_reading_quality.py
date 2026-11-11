from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_calibration as calibration_helpers

from appliance_display_sensor.reading_quality import ReadingQuality
from appliance_display_sensor.calibration import PREVIEW_TIMEOUT_SECONDS
from appliance_display_sensor.pipeline import FrameProcessor


def observation(status="unknown", *, valid=True, digits=(None, None, None)):
    return SimpleNamespace(
        candidate_state=SimpleNamespace(status=status),
        stable_state=SimpleNamespace(status="running"),
        display=SimpleNamespace(valid=valid, digits=[SimpleNamespace(value=d) for d in digits]),
    )


class ReadingQualityTests(unittest.TestCase):
    def test_counts_candidates_not_held_values_and_does_not_expose_text(self):
        quality = ReadingQuality()
        for result, error in [
            (observation("running"), None), (observation("complete"), None),
            (observation(), None), (observation(valid=False), None),
            (observation(digits=(1, None, 2)), None), (None, "private error detail"),
        ]:
            quality.observe(result, error, 100)
        report = quality.snapshot(101)
        self.assertEqual(report["counts"], {"readable": 2, "blank": 1, "unreadable": 2, "error": 1})
        self.assertEqual(report["total"], 6)
        self.assertEqual(report["percentages"]["readable"], 33.3)
        self.assertEqual(report["span_seconds"], 0)
        self.assertNotIn("private", str(report))
        self.assertNotIn("running", str(report))

    def test_empty_expiry_and_gaps_are_not_fabricated_observations(self):
        quality = ReadingQuality()
        self.assertIsNone(quality.snapshot(0)["percentages"]["readable"])
        quality.observe(observation("running"), None, 100)
        quality.observe(observation(), None, 110)
        self.assertEqual(quality.snapshot(200)["total"], 2)
        self.assertEqual(quality.snapshot(200)["last_sample_age_seconds"], 90)
        self.assertEqual(quality.snapshot(400)["counts"]["readable"], 0)
        self.assertEqual(quality.snapshot(410)["total"], 0)

    def test_memory_bounded_independent_of_frame_rate_and_clear(self):
        quality = ReadingQuality()
        result = observation("running")
        for second in range(650):
            for frame in range(100):
                quality.observe(result, None, second + frame / 100)
        self.assertLessEqual(len(quality._buckets), 301)
        self.assertLessEqual(quality.snapshot(650)["total"], 30000)
        quality.clear()
        self.assertEqual(quality.snapshot(650)["total"], 0)
        self.assertIsNone(quality.snapshot(650)["last_sample_age_seconds"])


class ReadingQualitySessionTests(unittest.TestCase):
    session = calibration_helpers.CalibrationTests.session
    image = calibration_helpers.CalibrationTests.image

    def test_state_is_read_only_and_preserves_blank_observations(self):
        session, config = self.session()
        original = session.config_path.read_bytes()
        image = self.image(config)
        result = FrameProcessor(config).process(image)
        with patch('appliance_display_sensor.calibration.time.monotonic', return_value=100):
            session.update_frame(image, result, config_revision=0)
            session.update_frame(
                image, FrameProcessor(config).process(image * 0), config_revision=0,
            )
            state = session.state()
            self.assertEqual(state['reading_quality']['counts']['readable'], 1)
            self.assertEqual(state['reading_quality']['counts']['blank'], 1)
            self.assertEqual(state['reading_quality']['mode'], 'saved')
        with patch('appliance_display_sensor.calibration.time.monotonic', return_value=500):
            self.assertEqual(session.state()['reading_quality']['total'], 0)
            self.assertEqual(session.state()['health']['camera_status'], 'stale')
        self.assertIsNone(session.take_pending_config())
        self.assertEqual(session.config_path.read_bytes(), original)

    def test_settings_changes_clear_counts_and_reject_in_flight_old_frames(self):
        session, config = self.session()
        image = self.image(config)
        result = FrameProcessor(config).process(image)
        revision = 0
        for change in (
            lambda: session.preview({'semantics': {'countdown_format': 'H:MM'}}),
            lambda: session.save({'semantics': {'countdown_format': 'H:MM'}}),
            session.cancel,
        ):
            session.update_frame(image, result, config_revision=revision)
            self.assertGreater(session.state()['reading_quality']['total'], 0)
            change()
            self.assertEqual(session.state()['reading_quality']['total'], 0)
            session.update_frame(image, result, config_revision=revision)
            pending, next_revision = session.take_pending_config_with_revision()
            self.assertIsNotNone(pending)
            # Old processing completion after new settings handoff must not count.
            session.update_frame(image, result, config_revision=revision)
            self.assertFalse(session.state()['reading_quality']['collecting'])
            session.update_frame(image, result, config_revision=next_revision)
            self.assertEqual(session.state()['reading_quality']['total'], 0)
            session.update_frame(image, result, config_revision=next_revision)
            self.assertEqual(session.state()['reading_quality']['total'], 1)
            revision = next_revision

    def test_expiring_preview_clears_its_counts_and_returns_saved_mode(self):
        session, config = self.session()
        image = self.image(config)
        result = FrameProcessor(config).process(image)
        with patch('appliance_display_sensor.calibration.time.monotonic', return_value=100):
            session.update_frame(image, result)
            session.preview({})
            _, revision = session.take_pending_config_with_revision()
            session.update_frame(image, result, config_revision=revision)
            session.update_frame(image, result, config_revision=revision)
            self.assertEqual(session.state()['reading_quality']['mode'], 'test')
            self.assertEqual(session.state()['reading_quality']['total'], 1)
        with patch('appliance_display_sensor.calibration.time.monotonic',
                   return_value=101 + PREVIEW_TIMEOUT_SECONDS):
            report = session.state()['reading_quality']
            self.assertEqual(report['total'], 0)
            self.assertEqual(report['mode'], 'saved')
            self.assertFalse(report['collecting'])
