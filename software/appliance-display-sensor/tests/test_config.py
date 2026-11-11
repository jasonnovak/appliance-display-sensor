from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from appliance_display_sensor.config import load_config


CAMERA_CONFIG = """
version: 1
device:
  identifier: test-display
  name: Test Display
input:
  type: picamera2
  camera_index: 1
  resolution: [2304, 1296]
  rotation: 180
  exposure_time_us: 8333
  analogue_gain: 1.0
  autofocus_mode: manual
  lens_position: 6.75
  warmup_seconds: 0.5
  frame_interval_seconds: 1.0
  capture_burst_count: 4
display:
  decoder: seven_segment
  roi: [0, 0, 420, 150]
  digit_boxes: [[25, 15, 70, 120], [175, 15, 70, 120], [285, 15, 70, 120]]
  colon_box: [120, 38, 24, 74]
  colon_after: 1
semantics:
  no_colon_unit: minutes
  terminal_texts: [End]
stability:
  confirmations: 2
  latch_completion_until_next_cycle: true
  unknown_grace_seconds: 12.5
diagnostics:
  transition_directory: debug/transitions
calibration:
  enabled: true
  host: 0.0.0.0
  port: 8090
mqtt:
  enabled: false
"""


class CameraConfigurationTests(unittest.TestCase):
    def test_countdown_format_default_and_validation(self):
        cases = [("", "auto"), ("  countdown_format: H:MM\n", "H:MM"),
                 ("  countdown_format: guess\n", None)]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "config.yaml"
            for setting, expected in cases:
                path.write_text(CAMERA_CONFIG.replace("semantics:\n", "semantics:\n" + setting))
                if expected is None:
                    with self.assertRaisesRegex(ValueError, "countdown_format"):
                        load_config(path)
                else:
                    self.assertEqual(load_config(path).semantics.countdown_format, expected)
            configured = CAMERA_CONFIG.replace(
                "semantics:\n", "semantics:\n  countdown_format: H:MM\n",
            )
            configured = configured.replace(", [285, 15, 70, 120]", "")
            path.write_text(configured)
            with self.assertRaisesRegex(ValueError, "exactly three"):
                load_config(path)

    def test_loads_picamera2_capture_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "camera.yaml"
            path.write_text(CAMERA_CONFIG, encoding="utf-8")

            config = load_config(path)

        self.assertEqual(config.input.kind, "picamera2")
        self.assertIsNotNone(config.input.camera)
        camera = config.input.camera
        assert camera is not None
        self.assertEqual((camera.width, camera.height), (2304, 1296))
        self.assertEqual(camera.rotation, 180)
        self.assertEqual(camera.exposure_time_us, 8333)
        self.assertEqual(camera.lens_position, 6.75)
        self.assertEqual(camera.capture_burst_count, 4)
        self.assertEqual(config.display.segment_slant_ratio, 0.0)
        self.assertEqual(config.stability.unknown_grace_seconds, 12.5)
        self.assertTrue(config.calibration.enabled)
        self.assertEqual(config.calibration.port, 8090)
        self.assertEqual(
            config.diagnostics.transition_directory,
            path.parent / "debug" / "transitions",
        )

    def test_loads_mqtt_password_from_a_separate_file(self) -> None:
        configured = CAMERA_CONFIG.replace(
            "  enabled: false\n",
            "  enabled: true\n"
            "  host: homeassistant.local\n"
            "  username: display-reader\n"
            "  password_file: mqtt-password.txt\n",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "mqtt-password.txt").write_text("secret-value\n", encoding="utf-8")
            path = directory / "camera.yaml"
            path.write_text(configured, encoding="utf-8")

            config = load_config(path)

        self.assertTrue(config.mqtt.enabled)
        self.assertEqual(config.mqtt.username, "display-reader")
        self.assertEqual(config.mqtt.password, "secret-value")


if __name__ == "__main__":
    unittest.main()
