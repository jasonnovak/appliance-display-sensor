from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from appliance_display_sensor.runtime_health import ALIGNMENT_STATES, HealthReporter, RuntimeHealth


def frame(status="running", *, blank=False, valid=True, stable_status=None):
    return SimpleNamespace(
        candidate_state=SimpleNamespace(status=status),
        stable_state=SimpleNamespace(status=stable_status or status),
        display=SimpleNamespace(
            valid=valid, digits=[SimpleNamespace(value=None if blank else "7")],
        ),
    )


class RuntimeHealthTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch("appliance_display_sensor.runtime_health.time.monotonic", return_value=0)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.health = RuntimeHealth()

    def observe(self, at, reading, **kwargs):
        self.now.return_value = at
        self.health.observe(reading, **kwargs)
        return self.health.snapshot(**kwargs)

    def test_waiting_stalled_startup_and_recovery(self):
        self.assertEqual(self.health.snapshot()["camera_status"], "waiting")
        self.assertIsNone(self.health.snapshot()["last_readable"])
        self.now.return_value = 16
        self.assertEqual(self.health.snapshot()["camera_status"], "stale")
        healthy = self.observe(17, frame())
        self.assertEqual(healthy["camera_status"], "live")
        self.assertEqual(healthy["display_readability"], "readable")
        self.assertEqual(healthy["reading_age_seconds"], 0)

    def test_blank_after_completion_does_not_report_problem_or_refresh_reading(self):
        completed = self.observe(1, frame("complete"))
        for at in range(2, 150):
            blank = self.observe(at, frame("unknown", blank=True, stable_status="complete"))
        self.assertEqual(blank["display_readability"], "blank")
        self.assertFalse(blank["reading_problem"])
        self.assertEqual(blank["last_readable"], completed["last_readable"])
        self.assertEqual(blank["reading_age_seconds"], 148)

    def test_sustained_unreadable_uses_candidates_even_while_stable_value_is_held(self):
        self.observe(0, frame())
        for at in range(1, 61):
            snapshot = self.observe(at, frame("unknown", valid=False, stable_status="running"))
            self.assertFalse(snapshot["reading_problem"])
        snapshot = self.observe(61, frame("unknown", valid=False))
        self.assertTrue(snapshot["reading_problem"])
        self.assertEqual(snapshot["reading_age_seconds"], 61)
        recovered = self.observe(62, frame())
        self.assertFalse(recovered["reading_problem"])

    def test_blank_invalid_minutes_and_stall_are_distinct(self):
        self.assertEqual(
            self.observe(0, frame("unknown", blank=True))["display_readability"], "blank",
        )
        self.assertEqual(self.observe(1, frame("unknown"))["display_readability"], "unreadable")
        self.now.return_value = 70
        stale = self.health.snapshot()
        self.assertEqual(stale["camera_status"], "stale")
        self.assertEqual(stale["display_readability"], "stale")
        self.assertFalse(stale["reading_problem"])
        self.assertFalse(self.observe(71, frame("unknown"))["reading_problem"])

    def test_calibration_interrupts_problem_timer_and_does_not_refresh_saved_reading(self):
        self.observe(0, frame())
        for at in range(1, 61):
            self.observe(at, frame("unknown"))
        self.now.return_value = 61
        self.assertEqual(
            self.health.snapshot(calibrating=True)["display_readability"], "calibrating",
        )
        self.assertFalse(self.health.snapshot(calibrating=True)["reading_problem"])
        tested = self.observe(62, frame(), calibrating=True)
        self.assertEqual(tested["reading_age_seconds"], 62)
        self.assertFalse(self.observe(63, frame("unknown"))["reading_problem"])

    def test_capture_error_is_not_blank_and_reporter_can_report_without_more_frames(self):
        self.observe(0, frame())
        publish = Mock()
        reporter = HealthReporter(self.health, publish)
        reporter.system = Mock()
        reporter.system.snapshot.return_value = {"temperature_c": None}
        self.now.return_value = 30
        reporter.report_once()
        self.assertEqual(publish.call_args.args[0]["camera_status"], "stale")
        self.assertEqual(publish.call_args.args[0]["frame_age_seconds"], 30)
        self.health.capture_error()
        reporter.report_once()
        self.assertEqual(publish.call_args.args[0]["camera_status"], "error")

    def alignment_report(self, callback=None, *, calibrating=False):
        publish = Mock()
        reporter = HealthReporter(self.health, publish, alignment=callback,
                                  calibrating=lambda: calibrating)
        reporter.system = Mock()
        reporter.system.snapshot.return_value = {}
        reporter.report_once()
        return publish.call_args.args[0]

    def test_alignment_disabled_unconfigured_and_all_current_statuses_are_explicit(self):
        self.observe(0, frame())
        self.assertEqual(self.alignment_report()['mount_alignment'], 'disabled')
        for status in ALIGNMENT_STATES:
            callback = Mock(return_value={
                'status': status, 'configured': True, 'movement_latched': False,
            })
            self.assertEqual(self.alignment_report(callback)['mount_alignment'], status)
        report = self.alignment_report(lambda: {'status': 'not_configured', 'configured': False})
        self.assertEqual(report['mount_alignment'], 'not_configured')
        self.assertEqual(report['camera_status'], 'live')
        self.assertEqual(report['display_readability'], 'readable')

    def test_darkness_preserves_movement_warning_without_claiming_a_current_match(self):
        self.observe(0, frame())
        for latched, expected in ((True, 'movement_unverified'), (False, 'uncheckable')):
            callback = Mock(return_value={
                'status': 'uncheckable', 'configured': True, 'movement_latched': latched,
            })
            self.assertEqual(self.alignment_report(callback)['mount_alignment'], expected)

    def test_camera_outage_and_calibration_override_cached_alignment(self):
        self.observe(0, frame())
        callback = Mock(return_value={'status': 'aligned', 'configured': True})
        self.assertEqual(self.alignment_report(callback, calibrating=True)['mount_alignment'],
                         'paused')
        self.now.return_value = 20
        self.assertEqual(self.alignment_report(callback)['mount_alignment'], 'stale')
        self.health.capture_error()
        self.assertEqual(self.alignment_report(callback)['mount_alignment'], 'stale')

    def test_alignment_failure_does_not_drop_heartbeat_or_leak_private_data(self):
        self.observe(0, frame())
        for callback in (Mock(side_effect=RuntimeError('secret path/password')),
                         lambda: {'status': 'unexpected private data'}, lambda: None):
            report = self.alignment_report(callback)
            self.assertEqual(report['mount_alignment'], 'error')
            self.assertEqual(report['camera_status'], 'live')
            self.assertNotIn('private', str(report))
            self.assertNotIn('secret', str(report))
        report = self.alignment_report(lambda: {
            'status': 'aligned', 'configured': True, 'template': 'private pixels',
            'anchor_box': [1, 2, 30, 40], 'password': 'secret',
        })
        self.assertEqual(report['mount_alignment'], 'aligned')
        self.assertNotIn('private', str(report))
        self.assertNotIn('secret', str(report))
        self.assertNotIn('anchor_box', report)


class LiveHealthWiringTests(unittest.TestCase):
    def test_live_camera_reports_without_calibration_server_and_closes_heartbeat(self):
        from pathlib import Path
        from appliance_display_sensor.cli import _run_camera
        from appliance_display_sensor.config import load_config
        from test_config import CAMERA_CONFIG
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(CAMERA_CONFIG)
            config = load_config(path)
            config = replace(config, mqtt=replace(config.mqtt, enabled=True),
                             calibration=replace(config.calibration, enabled=False))
            reading = frame()
            reading.stable_changed = False
            reading.candidate_state.to_dict = lambda **kwargs: {}
            reading.stable_state.to_dict = lambda **kwargs: {}
            with (
                patch("appliance_display_sensor.cli.MqttPublisher") as publisher,
                patch("appliance_display_sensor.cli.Picamera2Input") as camera,
                patch("appliance_display_sensor.cli.FrameProcessor") as processor,
                patch("appliance_display_sensor.cli.HealthReporter") as reporter,
                patch("appliance_display_sensor.cli._print_json"),
            ):
                camera.return_value.__enter__.return_value.frames.return_value = [None]
                processor.return_value.process.return_value = reading
                self.assertEqual(_run_camera(config=config, config_path=path, interval=0,
                    max_frames=1, diagnostics_dir=None, no_mqtt=False, compact=True), 0)
                self.assertTrue(publisher.call_args.kwargs["diagnostics"])
                self.assertIsNone(reporter.call_args.kwargs['alignment'])
                publisher.return_value.connect.assert_called_once_with(background=True)
                reporter.return_value.start.assert_called_once()
                reporter.return_value.close.assert_called_once()
                observed = reporter.call_args.args[0].snapshot()
                self.assertEqual(observed["display_readability"], "readable")
                publisher.return_value.close.assert_called_once()
