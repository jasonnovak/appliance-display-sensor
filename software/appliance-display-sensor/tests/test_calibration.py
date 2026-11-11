from __future__ import annotations

import tempfile
import unittest
import copy
import json
import zipfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import cv2
import numpy as np

import yaml

from appliance_display_sensor.calibration import (
    CalibrationSession,
    CalibrationServer,
    build_candidate_config,
    save_candidate_config,
    PREVIEW_TIMEOUT_SECONDS,
)
from appliance_display_sensor.config import load_config
from appliance_display_sensor.pipeline import FrameProcessor
from appliance_display_sensor.synthetic import render_display
from appliance_display_sensor.models import Rect


CONFIG = """
version: 1
device:
  identifier: test-display
  name: Test Display
input:
  type: picamera2
  resolution: [640, 480]
  exposure_time_us: 8000
  analogue_gain: 1.0
  autofocus_mode: manual
  lens_position: 8.0
display:
  decoder: seven_segment
  roi: [100, 100, 420, 150]
  digit_boxes: [[25, 15, 70, 120], [175, 15, 70, 120], [285, 15, 70, 120]]
  colon_box: [120, 38, 24, 74]
  colon_after: 1
stability:
  confirmations: 2
calibration:
  enabled: true
  host: 127.0.0.1
  port: 8090
mqtt:
  enabled: true
  host: homeassistant.local
  username: setup-user
  password: do-not-expose
"""


class CalibrationTests(unittest.TestCase):
    def test_feedback_is_read_only_in_saved_and_applied_test_mode(self):
        session, config = self.session()
        image = self.image(config)
        original = session.config_path.read_bytes()
        with self.assertRaises(ValueError):
            session.readability_feedback()
        session.update_frame(image, FrameProcessor(config).process(image))
        report = session.readability_feedback()
        self.assertEqual(report['mode'], 'saved')
        self.assertEqual(report['text'], '1:05')
        self.assertIsNone(session.take_pending_config())
        session.preview({'semantics': {'countdown_format': 'H:MM'}})
        with self.assertRaises(ValueError):
            session.readability_feedback()
        pending = session.take_pending_config()
        session.update_frame(image, FrameProcessor(pending).process(image))
        self.assertEqual(session.readability_feedback()['mode'], 'test')
        self.assertTrue(session.active)
        self.assertEqual(session.config_path.read_bytes(), original)
        for private in ('do-not-expose', 'setup-user', 'homeassistant.local'):
            self.assertNotIn(private, json.dumps(report))

    def test_feedback_rejects_stale_error_busy_and_changed_settings(self):
        session, config = self.session()
        image = self.image(config)
        with patch('appliance_display_sensor.calibration.time.monotonic', return_value=100):
            session.update_frame(image, FrameProcessor(config).process(image))
        with patch('appliance_display_sensor.calibration.time.monotonic', return_value=106):
            with self.assertRaises(ValueError):
                session.readability_feedback()
        session.update_frame(image, None, 'private error')
        with self.assertRaises(ValueError):
            session.readability_feedback()
        session.update_frame(image, FrameProcessor(config).process(image))
        session._suggestion_lock.acquire()
        try:
            with self.assertRaises(RuntimeError):
                session.readability_feedback()
        finally:
            session._suggestion_lock.release()
        with patch('appliance_display_sensor.calibration.inspect_readability',
                   side_effect=lambda *_: (session.cancel() and {})):
            with self.assertRaises(ValueError):
                session.readability_feedback()

    def test_http_feedback_has_no_save_or_private_side_effects(self):
        session, config = self.session()
        server = CalibrationServer('127.0.0.1', 0, session)
        server.start()
        self.addCleanup(server.close)
        url = f'http://127.0.0.1:{server._server.server_address[1]}/api/readability-feedback'
        with self.assertRaises(HTTPError) as error:
            urlopen(url, timeout=3)
        self.assertEqual(error.exception.code, 503)
        image = self.image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        with urlopen(url, timeout=3) as response:
            self.assertEqual(json.load(response)['text'], '1:05')
        self.assertIsNone(session.take_pending_config())
        self.assertFalse(session.active)

    def test_countdown_format_preview_save_and_optical_recovery(self):
        session, config = self.session()
        original = session.config_path.read_bytes()
        optical = session.export_profile()
        testing = session.preview({"semantics": {"countdown_format": "H:MM"}})
        self.assertEqual(testing["config"]["semantics"]["countdown_format"], "H:MM")
        self.assertEqual(session.config_path.read_bytes(), original)
        session.save({"semantics": {"countdown_format": "H:MM"}})
        saved = load_config(session.config_path)
        self.assertEqual(saved.semantics.countdown_format, "H:MM")
        self.assertEqual(saved.display, config.display)
        self.assertEqual(saved.mqtt, config.mqtt)
        self.assertEqual(optical, session.export_profile())
        restored = session.import_profile(optical)
        self.assertEqual(restored["config"]["semantics"]["countdown_format"], "H:MM")
        image = self.image(saved)
        result = FrameProcessor(saved).process(image)
        session.update_frame(image, result)
        reading = session.state()["detection"]
        self.assertEqual(reading["text"], "1:05")
        self.assertIn("colon_on", reading)
        with self.assertRaises(ValueError):
            session.preview({"semantics": {"countdown_format": "HH:MM"}})

    def session(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.yaml"
        path.write_text(CONFIG, encoding="utf-8")
        config = load_config(path)
        return CalibrationSession(path, config), config

    def image(self, config):
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        roi = config.display.roi
        image[roi.y:roi.y2, roi.x:roi.x2] = render_display(
            size=(roi.width, roi.height), digit_boxes=config.display.digit_boxes,
            digits=(1, 0, 5), colon_box=config.display.colon_box, colon_on=True,
        )
        return image

    def test_health_distinguishes_waiting_live_and_stale(self):
        session, config = self.session()
        self.assertEqual(session.state()["health"]["camera_status"], "waiting")
        image = self.image(config)
        with patch("appliance_display_sensor.calibration.time.monotonic", return_value=100):
            session.update_frame(image, FrameProcessor(config).process(image))
            self.assertEqual(session.state()["health"]["camera_status"], "live")
        with patch("appliance_display_sensor.calibration.time.monotonic", return_value=115):
            health = session.state()["health"]
            self.assertEqual(health["camera_status"], "stale")
            self.assertEqual(health["reading_age_seconds"], 15)

    def test_blank_frame_does_not_refresh_last_readable_time(self):
        session, config = self.session()
        with patch("appliance_display_sensor.calibration.time.monotonic", return_value=100):
            image = self.image(config)
            session.update_frame(image, FrameProcessor(config).process(image))
        with patch("appliance_display_sensor.calibration.time.monotonic", return_value=105):
            blank = np.zeros_like(image)
            session.update_frame(blank, FrameProcessor(config).process(blank))
            self.assertEqual(session.state()["health"]["reading_age_seconds"], 5)
            self.assertEqual(session.state()["health"]["frame_age_seconds"], 0)

    def test_binary_preview_is_display_cropped_and_cached(self):
        session, config = self.session()
        image = self.image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        first = session.image_jpeg(overlay=False, binary=True)
        self.assertIs(first, session.image_jpeg(overlay=False, binary=True))
        decoded = cv2.imdecode(np.frombuffer(first, np.uint8), cv2.IMREAD_GRAYSCALE)
        self.assertEqual(decoded.shape, (150, 420))
        self.assertGreater(decoded.max(), 250)
        self.assertLess(decoded.min(), 5)

    def test_expired_preview_changes_revision_and_restores_saved_settings(self):
        session, _ = self.session()
        with patch("appliance_display_sensor.calibration.time.monotonic", return_value=100):
            testing = session.preview({"display": {"threshold_value": 95}})
            self.assertTrue(testing["active"])
        with patch(
            "appliance_display_sensor.calibration.time.monotonic",
            return_value=101 + PREVIEW_TIMEOUT_SECONDS,
        ):
            saved = session.state()
        self.assertFalse(saved["active"])
        self.assertGreater(saved["revision"], testing["revision"])
        self.assertNotEqual(saved["config"]["display"]["threshold_value"], 95)

    def test_mqtt_health_is_injected_without_config_secrets(self):
        session, _ = self.session()
        session._mqtt_health = lambda: {"enabled": True, "connected": False}
        health = session.state()["health"]["mqtt"]
        self.assertFalse(health["connected"])
        self.assertNotIn("password", str(session.state()))

    def test_optical_update_preserves_private_mqtt_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.yaml"
            path.write_text(CONFIG, encoding="utf-8")
            config, raw = build_candidate_config(
                path,
                {
                    "camera": {"exposure_time_us": 5000, "analogue_gain": 1.5},
                    "display": {"threshold_value": 110},
                    "stability": {"unknown_grace_seconds": 20},
                },
            )

        self.assertEqual(config.input.camera.exposure_time_us, 5000)
        self.assertEqual(config.display.threshold_value, 110)
        self.assertEqual(config.stability.unknown_grace_seconds, 20)
        self.assertEqual(raw["mqtt"]["password"], "do-not-expose")

    def test_export_uses_saved_calibration_not_unsaved_preview(self):
        session, config = self.session()
        session.preview({"display": {"threshold_value": 95}})
        profile = session.export_profile()
        self.assertEqual(
            profile["calibration"]["display"]["threshold_value"], config.display.threshold_value,
        )
        for private in ("do-not-expose", "setup-user", "homeassistant.local", "test-display"):
            self.assertNotIn(private, json.dumps(profile))
        self.assertEqual(profile["camera_geometry"], {"resolution": [640, 480], "rotation": 0})

    def test_import_tests_without_saving_and_keeps_current_identity_and_mqtt(self):
        session, _ = self.session()
        original = session.config_path.read_bytes()
        profile = session.export_profile()
        profile["calibration"]["display"]["threshold_value"] = 95
        profile["calibration"]["display"]["colon_min_fill"] = 0.04
        response = session.import_profile(profile)
        self.assertTrue(response["active"])
        self.assertEqual(response["config"]["display"]["threshold_value"], 95)
        self.assertEqual(response["config"]["display"]["colon_min_fill"], 0.04)
        self.assertEqual(session.config_path.read_bytes(), original)
        pending = session.take_pending_config()
        self.assertEqual(pending.device.identifier, "test-display")
        self.assertEqual(pending.mqtt.password, "do-not-expose")
        session.cancel()
        self.assertEqual(session.config_path.read_bytes(), original)

    def test_import_rejects_unknown_fields_versions_and_geometry_without_changes(self):
        session, _ = self.session()
        original = session.config_path.read_bytes()
        good = session.export_profile()
        bad_profiles = []
        for key, value in (("version", 2), ("version", True), ("format", "other")):
            candidate = copy.deepcopy(good)
            candidate[key] = value
            bad_profiles.append(candidate)
        for key, value in (("rotation", 180), ("resolution", [320, 240])):
            candidate = copy.deepcopy(good)
            candidate["camera_geometry"][key] = value
            bad_profiles.append(candidate)
        candidate = copy.deepcopy(good)
        candidate["mqtt"] = {"host": "evil"}
        bad_profiles.append(candidate)
        candidate = copy.deepcopy(good)
        candidate["calibration"]["device"] = {"identifier": "other"}
        bad_profiles.append(candidate)
        candidate = copy.deepcopy(good)
        candidate["calibration"]["camera"]["password"] = "evil"
        bad_profiles.append(candidate)
        candidate = copy.deepcopy(good)
        del candidate["calibration"]["display"]["roi"]
        bad_profiles.append(candidate)
        candidate = copy.deepcopy(good)
        candidate["calibration"]["camera"]["analogue_gain"] = float("nan")
        bad_profiles.append(candidate)
        for candidate in bad_profiles:
            with self.subTest(profile=candidate):
                with self.assertRaises(ValueError):
                    session.import_profile(candidate)
                self.assertFalse(session.active)
                self.assertEqual(session.config_path.read_bytes(), original)

    def test_restore_uses_only_previous_optics_even_with_stale_mqtt_password_file(self):
        session, _ = self.session()
        original = session.config_path.read_bytes()
        backup = session.config_path.with_suffix(".yaml.bak")
        raw = yaml.safe_load(original)
        raw["display"]["threshold"] = {"method": "fixed", "value": 95}
        raw["mqtt"] = {"host": "old-broker", "password_file": "missing-secret-file"}
        raw["device"] = {"identifier": "other-appliance", "name": "Other appliance"}
        backup.write_text(yaml.safe_dump(raw), encoding="utf-8")
        self.assertTrue(session.state()["recovery"]["previous_available"])
        response = session.restore_previous()
        self.assertTrue(response["active"])
        self.assertEqual(response["recovery_action"], "restore_test")
        self.assertEqual(response["config"]["display"]["threshold_value"], 95)
        self.assertEqual(session.config_path.read_bytes(), original)
        pending = session.take_pending_config()
        self.assertEqual(pending.mqtt.host, "homeassistant.local")
        self.assertEqual(pending.mqtt.password, "do-not-expose")
        self.assertEqual(pending.device.identifier, "test-display")

    def test_restore_missing_or_invalid_backup_preserves_saved_configuration(self):
        session, _ = self.session()
        original = session.config_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "No previous"):
            session.restore_previous()
        session.config_path.with_suffix(".yaml.bak").write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            session.restore_previous()
        self.assertFalse(session.active)
        self.assertEqual(session.config_path.read_bytes(), original)

    def test_import_invalid_geometry_fails_before_activating_test(self):
        session, config = self.session()
        image = self.image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        profile = session.export_profile()
        profile["calibration"]["display"]["roi"] = [500, 400, 420, 150]
        with self.assertRaises(ValueError):
            session.import_profile(profile)
        self.assertFalse(session.active)

    def test_import_invalid_geometry_is_rejected_before_first_frame(self):
        session, _ = self.session()
        profile = session.export_profile()
        profile["calibration"]["display"]["roi"] = [500, 400, 420, 150]
        with self.assertRaises(ValueError):
            session.import_profile(profile)
        self.assertFalse(session.active)

    def test_diagnostic_bundle_contains_only_cropped_images_and_public_fields(self):
        session, config = self.session()
        image = self.image(config)
        image[0:50, 0:50] = (0, 0, 255)  # Private scene marker outside display.
        original = session.config_path.read_bytes()
        session._mqtt_health = lambda: {
            "enabled": True, "connected": False,
            "error": "SECRET internal /home/private/path 192.168.1.11",
        }
        session.update_frame(image, FrameProcessor(config).process(image))
        archive = zipfile.ZipFile(BytesIO(session.diagnostic_bundle()))
        self.assertEqual(set(archive.namelist()), {
            "report.json", "optical-profile.json", "README.txt",
            "display.png", "segments.png", "binary.png",
        })
        for name in ("display.png", "segments.png", "binary.png"):
            pixels = cv2.imdecode(np.frombuffer(archive.read(name), np.uint8), cv2.IMREAD_UNCHANGED)
            self.assertEqual(pixels.shape[:2], (150, 420))
            self.assertNotIn(b"eXIf", archive.read(name))
        pixels = cv2.imdecode(
            np.frombuffer(archive.read("display.png"), np.uint8), cv2.IMREAD_COLOR,
        )
        self.assertTrue(np.array_equal(pixels, image[100:250, 100:520]))
        public = "".join(archive.read(name).decode() for name in
                         ("report.json", "optical-profile.json", "README.txt"))
        for secret in ("do-not-expose", "setup-user", "homeassistant.local", "test-display",
                       "SECRET", "/home/private", "192.168.1.11", str(session.config_path)):
            self.assertNotIn(secret, public)
        report = json.loads(archive.read("report.json"))
        self.assertEqual(report["reading"]["text"], "1:05")
        self.assertEqual(report["mode"], "saved")
        self.assertEqual(session.config_path.read_bytes(), original)
        self.assertFalse(session.active)

    def test_diagnostic_bundle_labels_tested_settings_without_saving_them(self):
        session, config = self.session()
        image = self.image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        original = session.config_path.read_bytes()
        session.preview({"display": {"threshold_value": 95}})
        archive = zipfile.ZipFile(BytesIO(session.diagnostic_bundle()))
        report = json.loads(archive.read("report.json"))
        profile = json.loads(archive.read("optical-profile.json"))
        self.assertEqual(report["mode"], "test")
        self.assertTrue(report["camera_settings_pending"])
        self.assertEqual(profile["calibration"]["display"]["threshold_value"], 95)
        self.assertEqual(session.config_path.read_bytes(), original)
        self.assertNotEqual(
            session.export_profile()["calibration"]["display"]["threshold_value"], 95,
        )

    def test_diagnostics_reject_missing_frame_full_frame_and_size_limits(self):
        session, config = self.session()
        with self.assertRaisesRegex(ValueError, "No camera"):
            session.diagnostic_bundle()
        image = self.image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        with patch("appliance_display_sensor.calibration.MAX_DIAGNOSTIC_PIXELS", 10):
            with self.assertRaisesRegex(ValueError, "too large"):
                session.diagnostic_bundle()
        with patch("appliance_display_sensor.calibration.MAX_DIAGNOSTIC_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "size limit"):
                session.diagnostic_bundle()
        session._preview_config = replace(
            config, display=replace(config.display, roi=Rect(0, 0, 640, 480)),
        )
        with self.assertRaisesRegex(ValueError, "display-only"):
            session.diagnostic_bundle()
        session._preview_config = config
        self.assertTrue(session.diagnostic_bundle().startswith(b"PK"))

    def test_diagnostic_generation_is_single_flight_and_recovers_after_busy(self):
        session, config = self.session()
        image = self.image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        session._diagnostic_lock.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "already"):
                session.diagnostic_bundle()
        finally:
            session._diagnostic_lock.release()
        self.assertTrue(session.diagnostic_bundle().startswith(b"PK"))

    def alignment_image(self, config):
        image = self.image(config)
        cv2.putText(image, 'ANCHOR', (110, 75), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (180, 180, 180), 2, cv2.LINE_AA)
        return image

    def test_alignment_reference_does_not_modify_config_or_pause_mqtt(self):
        session, config = self.session()
        image = self.alignment_image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        before = session.config_path.read_bytes()
        result = session.alignment_reference({
            "confirmed": True, "revision": 0, "anchor_box": [100, 40, 150, 50],
        })
        self.assertTrue(result["health"]["alignment"]["configured"])
        self.assertFalse(session.active)
        self.assertIsNone(session.take_pending_config())
        self.assertEqual(before, session.config_path.read_bytes())
        reference_path = session._alignment.path
        self.assertTrue(reference_path.exists())
        self.assertNotIn('template', json.dumps(result))
        session.forget_alignment({"confirmed": True})
        self.assertFalse(reference_path.exists())
        self.assertEqual(before, session.config_path.read_bytes())

    def test_alignment_requires_confirmation_fresh_frame_matching_revision_and_static_region(self):
        session, config = self.session()
        payload = {"confirmed": True, "revision": 0, "anchor_box": [100, 40, 150, 50]}
        with self.assertRaises(ValueError):
            session.alignment_reference(payload)
        image = self.alignment_image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        for bad in ({**payload, "confirmed": False}, {**payload, "revision": 9},
                    {**payload, "anchor_box": [125, 115, 70, 120]},
                    {**payload, "anchor_box": [True, 40, 150, 50]},
                    {**payload, "private": "not accepted"}):
            with self.assertRaises(ValueError):
                session.alignment_reference(bad)
        with patch('appliance_display_sensor.calibration.time.monotonic',
                   return_value=session._last_frame_at + 6):
            with self.assertRaises(ValueError):
                session.alignment_reference(payload)
        session.preview({"display": {"threshold_value": 95}})
        with self.assertRaises(ValueError):
            session.alignment_reference({**payload, "revision": 1})
        self.assertFalse(session._alignment.path.exists())

    def test_http_alignment_store_and_forget_and_config_invalidation(self):
        session, config = self.session()
        image = self.alignment_image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        server = CalibrationServer("127.0.0.1", 0, session)
        server.start()
        self.addCleanup(server.close)
        base = f"http://127.0.0.1:{server._server.server_address[1]}"
        def post(path, payload):
            request = Request(base + path, data=json.dumps(payload).encode(), method="POST",
                              headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=3) as response:
                return json.load(response)
        result = post('/api/alignment/reference', {
            "confirmed": True, "revision": 0, "anchor_box": [100, 40, 150, 50],
        })
        self.assertTrue(result["health"]["alignment"]["configured"])
        request = Request(base + '/api/alignment/forget', data=b'{"confirmed":true}',
                          method="POST", headers={"Content-Type": "text/plain"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=3)
        self.assertEqual(error.exception.code, 400)
        self.assertTrue(session._alignment.path.exists())
        session.save({"display": {"threshold_value": 95}})
        session.take_pending_config()
        self.assertEqual(session.state()["health"]["alignment"]["status"], "needs_reference")
        result = post('/api/alignment/forget', {"confirmed": True})
        self.assertFalse(result["health"]["alignment"]["configured"])

    def test_pixel_advice_is_crop_only_read_only_and_private(self):
        session, config = self.session()
        image = self.image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        before = session.config_path.read_bytes()
        with patch('appliance_display_sensor.calibration.suggest_pixels', return_value={
            "reason": "current_settings_fit", "recommendation": None,
        }) as helper:
            advice = session.pixel_suggestions()
        self.assertEqual(helper.call_args.args[0].shape, (150, 420, 3))
        self.assertEqual(advice["revision"], 0)
        self.assertEqual(before, session.config_path.read_bytes())
        self.assertFalse(session.active)
        self.assertIsNone(session.take_pending_config())
        self.assertNotIn("do-not-expose", json.dumps(advice))
        np.testing.assert_array_equal(image, session._frame)

    def test_pixel_advice_rejects_unhealthy_test_pending_and_oversized_states(self):
        session, config = self.session()
        with self.assertRaises(ValueError):
            session.pixel_suggestions()
        image = self.image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        with patch('appliance_display_sensor.calibration.time.monotonic',
                   return_value=session._last_frame_at + 6):
            with self.assertRaises(ValueError):
                session.pixel_suggestions()
        with patch('appliance_display_sensor.calibration.MAX_DIAGNOSTIC_PIXELS', 1):
            with self.assertRaises(ValueError):
                session.pixel_suggestions()
        session.preview({"display": {"threshold_value": 95}})
        with self.assertRaises(ValueError):
            session.pixel_suggestions()
        session.cancel()
        with self.assertRaises(ValueError):
            session.pixel_suggestions()
        session.take_pending_config()
        session.update_frame(image, FrameProcessor(config).process(image), error="private error")
        with self.assertRaises(ValueError):
            session.pixel_suggestions()
        session.update_frame(image, FrameProcessor(config).process(image))
        self.assertIn("reason", session.pixel_suggestions())

    def test_pixel_advice_single_flight_and_revision_change_are_rejected(self):
        session, config = self.session()
        image = self.image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        session._suggestion_lock.acquire()
        try:
            with self.assertRaises(RuntimeError):
                session.pixel_suggestions()
        finally:
            session._suggestion_lock.release()
        with patch('appliance_display_sensor.calibration.suggest_pixels',
                   side_effect=lambda *_: (session.cancel() and {})):
            with self.assertRaises(ValueError):
                session.pixel_suggestions()
        session.take_pending_config()
        self.assertIn("reason", session.pixel_suggestions())

    def test_http_pixel_advice_failure_and_success_do_not_apply_settings(self):
        session, config = self.session()
        server = CalibrationServer("127.0.0.1", 0, session)
        server.start()
        self.addCleanup(server.close)
        url = f"http://127.0.0.1:{server._server.server_address[1]}/api/suggestions"
        with self.assertRaises(HTTPError) as error:
            urlopen(url, timeout=3)
        self.assertEqual(error.exception.code, 503)
        image = self.image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        with urlopen(url, timeout=3) as response:
            advice = json.load(response)
        self.assertEqual(advice["reason"], "current_settings_fit")
        self.assertFalse(session.active)
        self.assertIsNone(session.take_pending_config())

    def test_setup_page_includes_manual_browser_local_checklist(self):
        session, _ = self.session()
        server = CalibrationServer("127.0.0.1", 0, session)
        server.start()
        self.addCleanup(server.close)
        url = f"http://127.0.0.1:{server._server.server_address[1]}/"
        with urlopen(url, timeout=3) as response:
            page = response.read().decode("utf-8")
        self.assertIn('id="setupChecklist"', page)
        self.assertEqual(page.count('data-check="'), 7)
        self.assertIn("not automatic certification", page)
        self.assertIn("Camera movement cannot be detected here", page)
        self.assertFalse(session.state()["active"])

    def test_http_diagnostics_zip_and_no_frame_failure(self):
        session, config = self.session()
        server = CalibrationServer("127.0.0.1", 0, session)
        server.start()
        self.addCleanup(server.close)
        url = f"http://127.0.0.1:{server._server.server_address[1]}/api/diagnostics.zip"
        with self.assertRaises(HTTPError) as error:
            urlopen(url, timeout=3)
        self.assertEqual(error.exception.code, 503)
        image = self.image(config)
        session.update_frame(image, FrameProcessor(config).process(image))
        with urlopen(url, timeout=3) as response:
            self.assertEqual(response.headers["Content-Type"], "application/zip")
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertIn("display.png", zipfile.ZipFile(BytesIO(response.read())).namelist())

    def test_http_profile_download_and_import_preview_round_trip(self):
        session, _ = self.session()
        server = CalibrationServer("127.0.0.1", 0, session)
        server.start()
        self.addCleanup(server.close)
        base = f"http://127.0.0.1:{server._server.server_address[1]}"
        with urlopen(base + "/api/profile", timeout=3) as response:
            self.assertIn("attachment", response.headers["Content-Disposition"])
            profile = json.load(response)
        self.assertNotIn("do-not-expose", json.dumps(profile))
        profile["calibration"]["display"]["threshold_value"] = 95
        request = Request(
            base + "/api/profile/preview", data=json.dumps(profile).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(request, timeout=3) as response:
            self.assertTrue(json.load(response)["active"])
        bad = Request(
            base + "/api/profile/preview", data=b'{"version":999}',
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(bad, timeout=3)
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(session.state()["config"]["display"]["threshold_value"], 95)

    def test_public_session_state_does_not_contain_mqtt_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.yaml"
            path.write_text(CONFIG, encoding="utf-8")
            session = CalibrationSession(path, load_config(path))

            state_text = str(session.state())

        self.assertNotIn("do-not-expose", state_text)
        self.assertNotIn("setup-user", state_text)

    def test_save_is_atomic_and_keeps_a_rollback_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.yaml"
            path.write_text(CONFIG, encoding="utf-8")
            _, raw = build_candidate_config(
                path,
                {"display": {"channel": "red", "threshold_value": 90}},
            )
            backup = save_candidate_config(path, raw)
            saved = yaml.safe_load(path.read_text(encoding="utf-8"))

            self.assertTrue(backup.exists())
            self.assertEqual(saved["display"]["channel"], "red")
            self.assertEqual(saved["mqtt"]["password"], "do-not-expose")
            backup_text = backup.read_text(encoding="utf-8")
            self.assertIn("password: do-not-expose", backup_text)
            self.assertNotIn("channel: red", backup_text)


if __name__ == "__main__":
    unittest.main()
