from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

from appliance_display_sensor.config import CameraConfig
from appliance_display_sensor.inputs.picamera2_input import Picamera2Input


class _FakeCamera:
    def __init__(self, index: int):
        self.index = index
        self.configuration = None
        self.controls = []
        self.frame_values = iter((10, 80, 30, 20))

    def create_still_configuration(self, **kwargs):
        return kwargs

    def configure(self, configuration) -> None:
        self.configuration = configuration

    def set_controls(self, controls) -> None:
        self.controls.append(controls)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass

    def capture_array(self, stream: str) -> np.ndarray:
        return np.full((2, 3, 3), next(self.frame_values), dtype=np.uint8)


class Picamera2InputTests(unittest.TestCase):
    def test_requests_opencv_bgr_channel_order(self) -> None:
        instances: list[_FakeCamera] = []

        def fake_picamera(index: int) -> _FakeCamera:
            camera = _FakeCamera(index)
            instances.append(camera)
            return camera

        libcamera = types.ModuleType("libcamera")
        libcamera.Transform = lambda **kwargs: kwargs
        libcamera.controls = types.SimpleNamespace(
            AfModeEnum=types.SimpleNamespace(Auto=1, Continuous=2, Manual=3),
            AfTriggerEnum=types.SimpleNamespace(Start=1),
        )
        picamera2 = types.ModuleType("picamera2")
        picamera2.Picamera2 = fake_picamera

        config = CameraConfig(
            index=0,
            width=2304,
            height=1296,
            rotation=180,
            exposure_time_us=None,
            analogue_gain=None,
            autofocus_mode="default",
            lens_position=None,
            warmup_seconds=0,
            frame_interval_seconds=1,
        )

        with patch.dict(sys.modules, {"libcamera": libcamera, "picamera2": picamera2}):
            with Picamera2Input(config):
                pass

        self.assertEqual(instances[0].configuration["main"]["format"], "RGB888")
        self.assertTrue(instances[0].controls[0]["AeEnable"])

    def test_applies_live_safe_camera_controls(self) -> None:
        instances: list[_FakeCamera] = []

        def fake_picamera(index: int) -> _FakeCamera:
            camera = _FakeCamera(index)
            instances.append(camera)
            return camera

        libcamera = types.ModuleType("libcamera")
        libcamera.Transform = lambda **kwargs: kwargs
        libcamera.controls = types.SimpleNamespace(
            AfModeEnum=types.SimpleNamespace(Auto=1, Continuous=2, Manual=3),
            AfTriggerEnum=types.SimpleNamespace(Start=1),
        )
        picamera2 = types.ModuleType("picamera2")
        picamera2.Picamera2 = fake_picamera
        original = CameraConfig(0, 2304, 1296, 180, None, None, "default", None, 0, 1)
        updated = CameraConfig(0, 2304, 1296, 180, 5000, 1.5, "manual", 8.5, 0, 1)

        with patch.dict(sys.modules, {"libcamera": libcamera, "picamera2": picamera2}):
            with Picamera2Input(original) as camera:
                camera.apply_config(updated)

        applied = instances[0].controls[-1]
        self.assertFalse(applied["AeEnable"])
        self.assertEqual(applied["ExposureTime"], 5000)
        self.assertEqual(applied["AnalogueGain"], 1.5)
        self.assertEqual(applied["LensPosition"], 8.5)

    def test_composites_a_capture_burst_with_per_pixel_maximum(self) -> None:
        instances: list[_FakeCamera] = []

        def fake_picamera(index: int) -> _FakeCamera:
            camera = _FakeCamera(index)
            instances.append(camera)
            return camera

        libcamera = types.ModuleType("libcamera")
        libcamera.Transform = lambda **kwargs: kwargs
        libcamera.controls = types.SimpleNamespace(
            AfModeEnum=types.SimpleNamespace(Auto=1, Continuous=2, Manual=3),
            AfTriggerEnum=types.SimpleNamespace(Start=1),
        )
        picamera2 = types.ModuleType("picamera2")
        picamera2.Picamera2 = fake_picamera
        config = CameraConfig(
            0, 2304, 1296, 180, None, None, "default", None, 0, 1, 3
        )

        with patch.dict(sys.modules, {"libcamera": libcamera, "picamera2": picamera2}):
            with Picamera2Input(config) as camera:
                composite = next(camera.frames(interval_seconds=0.001))

        self.assertTrue(np.all(composite == 80))


if __name__ == "__main__":
    unittest.main()
