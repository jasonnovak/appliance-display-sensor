from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

import test_calibration as calibration_helpers
from appliance_display_sensor.alignment import profile_signature
from appliance_display_sensor.calibration import optical_profile


class AlignmentHealthTests(unittest.TestCase):
    session = calibration_helpers.CalibrationTests.session

    def test_unconfigured_does_not_capture_or_write_a_reference(self):
        session, _ = self.session()
        original = session.config_path.read_bytes()
        before = set(session.config_path.parent.iterdir())
        with patch.object(session._alignment, 'capture', side_effect=AssertionError('no capture')):
            report = session.alignment_health()
        self.assertEqual(report, {'status': 'not_configured', 'configured': False,
                                  'movement_latched': False})
        self.assertEqual(set(session.config_path.parent.iterdir()), before)
        self.assertEqual(session.config_path.read_bytes(), original)

    def test_heartbeat_and_web_use_same_status_without_exposing_anchor_pixels(self):
        session, config = self.session()
        session._last_frame_at = 100
        session._alignment.signature = profile_signature(optical_profile(config))
        session._alignment.snapshot = Mock(return_value={
            'status': 'aligned', 'configured': True, 'movement_latched': False,
            'anchor_box': [1, 2, 30, 40], 'match_score': 0.95, 'shift_pixels': [0, 0],
        })
        with patch('appliance_display_sensor.calibration.time.monotonic', return_value=100):
            self.assertEqual(session.alignment_health()['status'], 'aligned')
            self.assertEqual(session.state()['health']['alignment']['status'], 'aligned')
            self.assertNotIn('anchor_box', session.alignment_health())
            self.assertNotIn('match_score', session.alignment_health())
            session._active = True
            session._last_preview_change = 100
            self.assertEqual(session.alignment_health()['status'], 'paused')
            session._active = False
            session._pending_config = config
            self.assertEqual(session.alignment_health()['status'], 'paused')
            session._pending_config = None
            session._error = 'processing error'
            self.assertEqual(session.alignment_health()['status'], 'stale')
            session._error = None
            session._saved_config = replace(config, display=replace(config.display,
                                                                   threshold_value=95))
            self.assertEqual(session.alignment_health()['status'], 'needs_reference')
            session._saved_config = config
        with patch('appliance_display_sensor.calibration.time.monotonic', return_value=111):
            self.assertEqual(session.alignment_health()['status'], 'stale')
            self.assertEqual(session.state()['health']['alignment']['status'], 'stale')

    def test_snapshot_does_not_run_matching_or_clear_a_latched_movement(self):
        session, _ = self.session()
        session._alignment.latched = True
        session._alignment.status = 'uncheckable'
        with patch.object(session._alignment, 'update', side_effect=AssertionError('no matching')):
            for _ in range(3):
                self.assertTrue(session.alignment_health()['movement_latched'])
        self.assertTrue(session._alignment.latched)

    def test_live_camera_wires_alignment_callback_without_enabling_or_capturing_reference(self):
        from appliance_display_sensor.cli import _run_camera

        session, config = self.session()
        with (
            patch('appliance_display_sensor.cli.MqttPublisher') as publisher,
            patch('appliance_display_sensor.cli.Picamera2Input') as camera,
            patch('appliance_display_sensor.cli.CalibrationSession', return_value=session),
            patch('appliance_display_sensor.cli.CalibrationServer'),
            patch('appliance_display_sensor.cli.HealthReporter') as reporter,
        ):
            camera.return_value.__enter__.return_value.frames.return_value = []
            self.assertEqual(_run_camera(
                config=config, config_path=session.config_path, interval=0, max_frames=1,
                diagnostics_dir=None, no_mqtt=False, compact=True,
            ), 0)
            snapshot = reporter.call_args.kwargs['alignment']()
            self.assertEqual(snapshot['status'], 'not_configured')
            self.assertFalse(session._alignment.path.exists())
            reporter.return_value.start.assert_called_once()
            reporter.return_value.close.assert_called_once()
            publisher.return_value.close.assert_called_once()
