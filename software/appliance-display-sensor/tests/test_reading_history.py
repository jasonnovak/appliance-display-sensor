from dataclasses import replace
from datetime import UTC, datetime, timedelta
import unittest
from unittest.mock import patch

import test_calibration as calibration_helpers

from appliance_display_sensor.calibration import PREVIEW_TIMEOUT_SECONDS
from appliance_display_sensor.models import ApplianceState, DecodedDisplay, DigitReading
from appliance_display_sensor.pipeline import FrameProcessor, FrameResult
from appliance_display_sensor.reading_history import MAX_EVENTS, ReadingHistory
from appliance_display_sensor.stability import ReadingStabilizer


START = datetime(2026, 10, 18, 18, 0, tzinfo=UTC)


def state(minutes=None, *, status=None):
    status = status or ('running' if minutes is not None else 'unknown')
    return ApplianceState(
        status=status, running=status == 'running', remaining_minutes=minutes,
        estimated_finish=START + timedelta(minutes=minutes) if minutes is not None else None,
        display_text=(
            'End' if status == 'complete' else str(minutes) if minutes is not None else None
        ),
        confidence=1.0,
    )


def result(candidate, *, stable=None, blank=False):
    display = DecodedDisplay(
        digits=(DigitReading(None, 1.0, blank, (), {}),), colon_on=False,
        colon_after=None, colon_confidence=0, confidence=1.0, valid=blank,
    )
    return FrameResult(display, candidate, stable if stable is not None else candidate, True)


class ReadingHistoryTests(unittest.TestCase):
    def observe(self, history, reading, second, error=None):
        history.observe(reading, error, second, stale_after_seconds=10,
                        observed_at=START + timedelta(seconds=second))

    def test_initial_pending_is_not_accepted_and_duplicates_are_suppressed(self):
        history = ReadingHistory()
        reading = result(state(40))
        self.observe(history, replace(reading, stable_state=None), 0)
        self.assertEqual(history.snapshot()['events'], [])
        for second in range(10):
            self.observe(history, reading, second)
        events = history.snapshot()['events']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['minutes'], 40)
        self.assertIsNone(events[0]['change_minutes'])
        self.assertEqual(events[0]['observed_at'], START.isoformat())

    def test_changes_preserve_both_directions_and_are_not_smoothed(self):
        history = ReadingHistory()
        for second, minutes in enumerate((40, 39, 19, 35)):
            self.observe(history, result(state(minutes)), second)
        events = history.snapshot()['events']
        self.assertEqual([e['minutes'] for e in events], [35, 19, 39, 40])
        self.assertEqual([e['change_minutes'] for e in events], [16, -20, -1, None])
        self.assertEqual(events[0]['previous_minutes'], 19)

    def test_grace_confirmations_and_completion_latch_follow_existing_stabilizer(self):
        history, stabilizer = ReadingHistory(), ReadingStabilizer(2, unknown_grace_seconds=3)
        def feed(candidate, second, blank=False):
            stable = stabilizer.observe(candidate, observed_at=START + timedelta(seconds=second))
            reading = replace(result(candidate, blank=blank), stable_state=stable)
            self.observe(history, reading, second)
        feed(state(21), 0)
        feed(state(21), 1)
        feed(state(), 2)  # Held countdown: no fake repeat or premature unknown.
        self.assertEqual(len(history.snapshot()['events']), 1)
        feed(state(), 5)
        feed(state(), 6)
        self.assertEqual(history.snapshot()['events'][0]['kind'], 'unknown')
        feed(state(19), 7)
        feed(state(19), 8)
        self.assertIsNone(history.snapshot()['events'][0]['change_minutes'])
        feed(state(0, status='complete'), 9)
        feed(state(0, status='complete'), 10)
        feed(state(), 11, blank=True)
        feed(state(), 12, blank=True)
        self.assertEqual(history.snapshot()['events'][0]['kind'], 'complete')
        self.assertEqual(len(history.snapshot()['events']), 4)

    def test_blank_and_unreadable_unknown_are_labelled_without_inferred_completion(self):
        for blank, expected in ((True, 'blank'), (False, 'unreadable')):
            history = ReadingHistory()
            self.observe(history, result(state(), blank=blank), 0)
            event = history.snapshot()['events'][0]
            self.assertEqual(event['kind'], 'unknown')
            self.assertEqual(event['reason'], expected)

    def test_capture_gap_resets_comparison_and_cannot_infer_intervening_state(self):
        history = ReadingHistory()
        self.observe(history, result(state(40)), 0)
        self.observe(history, result(state(20)), 11)
        events = history.snapshot()['events']
        self.assertEqual(events[1]['kind'], 'gap')
        self.assertEqual(events[1]['seconds'], 11)
        self.assertIsNone(events[0]['previous_minutes'])
        self.assertEqual(len(events), 3)

    def test_errors_are_deduplicated_sanitized_and_break_comparisons(self):
        history = ReadingHistory()
        self.observe(history, result(state(40)), 0)
        for second in (1, 2):
            self.observe(history, None, second, 'secret path and credentials')
        self.observe(history, result(state(19)), 3)
        report = history.snapshot()
        self.assertEqual(len(report['events']), 3)
        self.assertEqual(report['events'][1]['kind'], 'error')
        self.assertIsNone(report['events'][0]['change_minutes'])
        self.assertNotIn('secret', str(report))

    def test_bounded_history_snapshot_is_independent_and_clear_resets(self):
        history = ReadingHistory()
        for second in range(100):
            self.observe(history, result(state(second)), second)
        report = history.snapshot()
        self.assertEqual(len(report['events']), MAX_EVENTS)
        self.assertEqual(report['dropped'], 100 - MAX_EVENTS)
        report['events'][0]['minutes'] = -999
        self.assertEqual(history.snapshot()['events'][0]['minutes'], 99)
        history.clear()
        self.assertEqual(history.snapshot()['events'], [])
        self.assertEqual(history.snapshot()['dropped'], 0)


class ReadingHistorySessionTests(unittest.TestCase):
    session = calibration_helpers.CalibrationTests.session
    image = calibration_helpers.CalibrationTests.image

    def test_read_only_collection_and_settings_handoff_reset(self):
        session, config = self.session()
        original = session.config_path.read_bytes()
        image = self.image(config)
        processor = FrameProcessor(config)
        for _ in range(2):
            session.update_frame(image, processor.process(image), config_revision=0)
        self.assertEqual(session.state()['reading_history']['events'][0]['minutes'], 65)
        for change in (lambda: session.preview({}), lambda: session.save({}), session.cancel):
            old_revision = session.state()['revision']
            change()
            pending, revision = session.take_pending_config_with_revision()
            self.assertEqual(session.state()['reading_history']['events'], [])
            reading = processor.process(image)
            session.update_frame(image, reading, config_revision=old_revision)
            self.assertEqual(session.state()['reading_history']['events'], [])
            session.update_frame(image, reading, config_revision=revision)  # settling frame
            self.assertEqual(session.state()['reading_history']['events'], [])
            session.update_frame(image, reading, config_revision=revision)
            self.assertEqual(len(session.state()['reading_history']['events']), 1)
            self.assertIsNotNone(pending)
        # The save above writes YAML formatting; collection itself never writes configuration.
        saved = session.config_path.read_bytes()
        session.update_frame(image, processor.process(image), config_revision=revision)
        self.assertEqual(session.config_path.read_bytes(), saved)
        self.assertIn(b'do-not-expose', original)
        self.assertNotIn('do-not-expose', str(session.state()['reading_history']))

    def test_expired_test_has_no_history_in_saved_mode(self):
        session, config = self.session()
        image = self.image(config)
        processor = FrameProcessor(config)
        with patch('appliance_display_sensor.calibration.time.monotonic', return_value=100):
            session.preview({})
            _, revision = session.take_pending_config_with_revision()
            for _ in range(3):
                session.update_frame(image, processor.process(image), config_revision=revision)
            self.assertEqual(session.state()['reading_history']['mode'], 'test')
            self.assertEqual(len(session.state()['reading_history']['events']), 1)
        with patch('appliance_display_sensor.calibration.time.monotonic',
                   return_value=101 + PREVIEW_TIMEOUT_SECONDS):
            report = session.state()['reading_history']
            self.assertEqual(report['mode'], 'saved')
            self.assertEqual(report['events'], [])
            self.assertFalse(report['collecting'])
