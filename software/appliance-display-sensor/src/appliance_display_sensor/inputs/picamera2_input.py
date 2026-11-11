from __future__ import annotations

import time
from collections.abc import Iterator

import numpy as np

from appliance_display_sensor.config import CameraConfig


class Picamera2Input:
    """Yield OpenCV-compatible frames from a locally attached libcamera device."""

    def __init__(self, config: CameraConfig):
        self.config = config
        self._camera = None
        self._controls_module = None

    def __enter__(self) -> "Picamera2Input":
        try:
            from libcamera import Transform, controls
            from picamera2 import Picamera2
        except ImportError as exc:  # pragma: no cover - Raspberry Pi dependency path
            raise RuntimeError(
                "Picamera2 input requires the Raspberry Pi picamera2 and libcamera packages"
            ) from exc

        transform = Transform(
            hflip=self.config.rotation == 180,
            vflip=self.config.rotation == 180,
        )
        camera = Picamera2(self.config.index)
        camera.configure(
            camera.create_still_configuration(
                main={
                    # Picamera2/libcamera format names describe component packing,
                    # not NumPy/OpenCV channel order. RGB888 produces the BGR
                    # triples expected by OpenCV and by our channel selector.
                    "format": "RGB888",
                    "size": (self.config.width, self.config.height),
                },
                transform=transform,
                buffer_count=2,
            )
        )

        self._controls_module = controls
        camera.set_controls(self._camera_controls(self.config))
        camera.start()
        if self.config.warmup_seconds:
            time.sleep(self.config.warmup_seconds)
        self._camera = camera
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._camera is not None:
            self._camera.stop()
            self._camera.close()
            self._camera = None
            self._controls_module = None

    def apply_config(self, config: CameraConfig) -> None:
        """Apply live-safe optical controls without restarting the camera pipeline."""

        if self._camera is None or self._controls_module is None:
            raise RuntimeError("Picamera2Input must be used as a context manager")
        fixed_fields = ("index", "width", "height", "rotation")
        changed = [
            field
            for field in fixed_fields
            if getattr(self.config, field) != getattr(config, field)
        ]
        if changed:
            raise ValueError(
                "live calibration cannot change " + ", ".join(changed) + "; restart the service"
            )
        self._camera.set_controls(self._camera_controls(config))
        self.config = config

    def _camera_controls(self, config: CameraConfig) -> dict[str, object]:
        controls = self._controls_module
        if controls is None:
            raise RuntimeError("camera controls are not available")

        camera_controls: dict[str, object] = {}
        if config.exposure_time_us is None:
            camera_controls["AeEnable"] = True
        else:
            camera_controls["AeEnable"] = False
            camera_controls["ExposureTime"] = config.exposure_time_us
            assert config.analogue_gain is not None
            camera_controls["AnalogueGain"] = config.analogue_gain

        autofocus_modes = {
            "auto": controls.AfModeEnum.Auto,
            "continuous": controls.AfModeEnum.Continuous,
            "manual": controls.AfModeEnum.Manual,
        }
        if config.autofocus_mode != "default":
            camera_controls["AfMode"] = autofocus_modes[config.autofocus_mode]
        if config.autofocus_mode == "auto":
            camera_controls["AfTrigger"] = controls.AfTriggerEnum.Start
        if config.lens_position is not None:
            camera_controls["LensPosition"] = config.lens_position
        return camera_controls

    def frames(self, *, interval_seconds: float | None = None) -> Iterator[np.ndarray]:
        if self._camera is None:
            raise RuntimeError("Picamera2Input must be used as a context manager")

        interval = (
            self.config.frame_interval_seconds
            if interval_seconds is None
            else interval_seconds
        )
        next_capture = time.monotonic()
        while True:
            # Many appliance displays multiplex their digit positions. A
            # per-pixel maximum across consecutive sensor frames reconstructs
            # the complete illuminated display without retaining the burst.
            composite = self._camera.capture_array("main").copy()
            for _ in range(1, self.config.capture_burst_count):
                np.maximum(
                    composite,
                    self._camera.capture_array("main"),
                    out=composite,
                )
            yield composite
            next_capture += interval
            delay = next_capture - time.monotonic()
            if delay > 0:
                time.sleep(delay)
