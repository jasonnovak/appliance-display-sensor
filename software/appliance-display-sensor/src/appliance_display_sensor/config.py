from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from appliance_display_sensor.models import Rect
from appliance_display_sensor.seven_segment_glyphs import (
    DEFAULT_ALLOWED_GLYPHS,
    normalize_glyph,
)


def _mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return value


@dataclass(frozen=True)
class DeviceConfig:
    identifier: str
    name: str
    appliance_type: str | None = None


@dataclass(frozen=True)
class CameraConfig:
    index: int
    width: int
    height: int
    rotation: int
    exposure_time_us: int | None
    analogue_gain: float | None
    autofocus_mode: str
    lens_position: float | None
    warmup_seconds: float
    frame_interval_seconds: float
    capture_burst_count: int = 1


@dataclass(frozen=True)
class InputConfig:
    kind: str
    path: Path | None
    camera: CameraConfig | None


@dataclass(frozen=True)
class DisplayConfig:
    decoder: str
    roi: Rect
    digit_boxes: tuple[Rect, ...]
    colon_box: Rect | None
    colon_after: int | None
    channel: str
    threshold_method: str
    threshold_value: int
    min_segment_fill: float
    colon_min_fill: float
    min_digit_confidence: float
    segment_thickness_ratio: float
    segment_slant_ratio: float
    allowed_glyphs: tuple[str | None, ...]
    segment_sample_boxes: tuple[tuple[float, float, float, float], ...] | None = None


def parse_segment_sample_boxes(value, digit_boxes):
    """Seven normalized sampling rectangles, shared by all physical digit positions."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != set("abcdefg"):
        raise ValueError("display.segment_sample_boxes must contain exactly segments a–g")
    result = []
    for name in "abcdefg":
        rectangle = value[name]
        if (not isinstance(rectangle, (list, tuple)) or len(rectangle) != 4
                or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in rectangle)):
            raise ValueError(f"Segment {name} requires four finite numbers: x, y, width, height")
        x, y, w, h = map(float, rectangle)
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
            raise ValueError(f"Segment {name} must fit inside the digit (normalized 0–1)")
        for box in digit_boxes:
            if round((x + w) * box.width) <= round(x * box.width) or (
                round((y + h) * box.height) <= round(y * box.height)
            ):
                raise ValueError(f"Segment {name} is smaller than one pixel in a digit box")
        result.append((x, y, w, h))
    return tuple(result)


@dataclass(frozen=True)
class SemanticsConfig:
    no_colon_unit: str
    terminal_texts: tuple[str, ...]
    countdown_format: str = "auto"


@dataclass(frozen=True)
class StabilityConfig:
    confirmations: int
    latch_completion_until_next_cycle: bool
    unknown_grace_seconds: float


@dataclass(frozen=True)
class DiagnosticsConfig:
    transition_directory: Path | None


@dataclass(frozen=True)
class CalibrationConfig:
    enabled: bool
    host: str
    port: int


@dataclass(frozen=True)
class MqttConfig:
    enabled: bool
    host: str
    port: int
    username: str | None
    password: str | None
    base_topic: str
    discovery_prefix: str


@dataclass(frozen=True)
class AppConfig:
    device: DeviceConfig
    input: InputConfig
    display: DisplayConfig
    semantics: SemanticsConfig
    stability: StabilityConfig
    diagnostics: DiagnosticsConfig
    calibration: CalibrationConfig
    mqtt: MqttConfig


def load_config(path: str | Path) -> AppConfig:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - dependency error path
        raise RuntimeError("PyYAML is required to load configuration files") from exc

    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = _mapping(raw, field_name="configuration")

    device_raw = _mapping(root.get("device", {}), field_name="device")
    identifier = str(device_raw.get("identifier", "")).strip()
    name = str(device_raw.get("name", "")).strip()
    if not identifier or not name:
        raise ValueError("device.identifier and device.name are required")
    appliance_type_raw = device_raw.get("appliance_type")
    appliance_type = str(appliance_type_raw).strip() if appliance_type_raw else None

    input_raw = _mapping(root.get("input", {}), field_name="input")
    input_kind = str(input_raw.get("type", "image_file")).strip()
    input_path_raw = input_raw.get("path")
    input_path = None
    if input_path_raw:
        input_path = Path(str(input_path_raw))
        if not input_path.is_absolute():
            input_path = (config_path.parent / input_path).resolve()

    camera_config: CameraConfig | None = None
    if input_kind == "picamera2":
        resolution_raw = input_raw.get("resolution", [2304, 1296])
        if not isinstance(resolution_raw, (list, tuple)) or len(resolution_raw) != 2:
            raise ValueError("input.resolution must contain [width, height]")
        width, height = (int(component) for component in resolution_raw)
        if width <= 0 or height <= 0:
            raise ValueError("input.resolution width and height must be positive")

        camera_index = int(input_raw.get("camera_index", 0))
        if camera_index < 0:
            raise ValueError("input.camera_index must not be negative")

        rotation = int(input_raw.get("rotation", 0))
        if rotation not in {0, 180}:
            raise ValueError("input.rotation currently supports only 0 or 180")

        exposure_raw = input_raw.get("exposure_time_us")
        exposure_time_us = int(exposure_raw) if exposure_raw is not None else None
        if exposure_time_us is not None and exposure_time_us <= 0:
            raise ValueError("input.exposure_time_us must be positive")

        gain_raw = input_raw.get("analogue_gain")
        analogue_gain = float(gain_raw) if gain_raw is not None else None
        if analogue_gain is not None and analogue_gain <= 0:
            raise ValueError("input.analogue_gain must be positive")

        if (exposure_time_us is None) != (analogue_gain is None):
            raise ValueError(
                "input.exposure_time_us and input.analogue_gain must be set together"
            )

        autofocus_mode = str(input_raw.get("autofocus_mode", "default")).lower()
        if autofocus_mode not in {"default", "auto", "continuous", "manual"}:
            raise ValueError(
                "input.autofocus_mode must be default, auto, continuous, or manual"
            )

        lens_raw = input_raw.get("lens_position")
        lens_position = float(lens_raw) if lens_raw is not None else None
        if lens_position is not None and lens_position < 0:
            raise ValueError("input.lens_position must not be negative")
        if autofocus_mode == "manual" and lens_position is None:
            raise ValueError("input.lens_position is required for manual autofocus")

        warmup_seconds = float(input_raw.get("warmup_seconds", 2.0))
        if warmup_seconds < 0:
            raise ValueError("input.warmup_seconds must not be negative")
        frame_interval_seconds = float(input_raw.get("frame_interval_seconds", 1.0))
        if frame_interval_seconds <= 0:
            raise ValueError("input.frame_interval_seconds must be positive")
        capture_burst_count = int(input_raw.get("capture_burst_count", 1))
        if not 1 <= capture_burst_count <= 10:
            raise ValueError("input.capture_burst_count must be between 1 and 10")

        camera_config = CameraConfig(
            index=camera_index,
            width=width,
            height=height,
            rotation=rotation,
            exposure_time_us=exposure_time_us,
            analogue_gain=analogue_gain,
            autofocus_mode=autofocus_mode,
            lens_position=lens_position,
            warmup_seconds=warmup_seconds,
            frame_interval_seconds=frame_interval_seconds,
            capture_burst_count=capture_burst_count,
        )

    display_raw = _mapping(root.get("display", {}), field_name="display")
    decoder = str(display_raw.get("decoder", "seven_segment")).strip()
    if decoder != "seven_segment":
        raise ValueError(f"unsupported display.decoder: {decoder}")
    roi = Rect.from_value(display_raw.get("roi"), field_name="display.roi")

    boxes_raw = display_raw.get("digit_boxes")
    if not isinstance(boxes_raw, list) or not boxes_raw:
        raise ValueError("display.digit_boxes must be a non-empty list")
    digit_boxes = tuple(
        Rect.from_value(value, field_name=f"display.digit_boxes[{index}]")
        for index, value in enumerate(boxes_raw)
    )

    colon_box_raw = display_raw.get("colon_box")
    colon_box = (
        Rect.from_value(colon_box_raw, field_name="display.colon_box")
        if colon_box_raw is not None
        else None
    )
    colon_after_raw = display_raw.get("colon_after")
    colon_after = int(colon_after_raw) if colon_after_raw is not None else None
    if colon_after is not None and not 0 < colon_after < len(digit_boxes):
        raise ValueError("display.colon_after must fall between configured digit positions")

    threshold_raw = _mapping(display_raw.get("threshold", {}), field_name="display.threshold")
    threshold_method = str(threshold_raw.get("method", "fixed")).strip().lower()
    if threshold_method not in {"fixed", "otsu"}:
        raise ValueError("display.threshold.method must be 'fixed' or 'otsu'")
    threshold_value = int(threshold_raw.get("value", 160))
    if not 0 <= threshold_value <= 255:
        raise ValueError("display.threshold.value must be between 0 and 255")

    channel = str(display_raw.get("channel", "blue")).strip().lower()
    if channel not in {"blue", "green", "red", "gray", "max"}:
        raise ValueError("display.channel must be blue, green, red, gray, or max")

    min_segment_fill = float(display_raw.get("min_segment_fill", 0.5))
    colon_min_fill = float(display_raw.get("colon_min_fill", 0.02))
    min_digit_confidence = float(display_raw.get("min_digit_confidence", 0.72))
    segment_thickness_ratio = float(display_raw.get("segment_thickness_ratio", 0.12))
    for field_name, value in {
        "display.min_segment_fill": min_segment_fill,
        "display.colon_min_fill": colon_min_fill,
        "display.min_digit_confidence": min_digit_confidence,
        "display.segment_thickness_ratio": segment_thickness_ratio,
    }.items():
        if not 0 < value < 1:
            raise ValueError(f"{field_name} must be between 0 and 1")

    segment_slant_ratio = float(display_raw.get("segment_slant_ratio", 0.0))
    if not -0.45 < segment_slant_ratio < 0.45:
        raise ValueError("display.segment_slant_ratio must be between -0.45 and 0.45")

    allowed_glyphs_raw = display_raw.get("allowed_glyphs", DEFAULT_ALLOWED_GLYPHS)
    if not isinstance(allowed_glyphs_raw, (list, tuple)) or not allowed_glyphs_raw:
        raise ValueError("display.allowed_glyphs must be a non-empty list")
    allowed_glyphs = tuple(
        dict.fromkeys(normalize_glyph(value) for value in allowed_glyphs_raw)
    )

    semantics_raw = _mapping(root.get("semantics", {}), field_name="semantics")
    countdown_format = str(semantics_raw.get("countdown_format", "auto")).strip()
    if countdown_format not in {"auto", "H:MM"}:
        raise ValueError("semantics.countdown_format must be auto or H:MM")
    if countdown_format == "H:MM" and len(digit_boxes) != 3:
        raise ValueError("H:MM requires exactly three digit boxes: hours, tens, units")
    no_colon_unit = str(semantics_raw.get("no_colon_unit", "minutes")).strip().lower()
    if no_colon_unit not in {"minutes", "seconds"}:
        raise ValueError("semantics.no_colon_unit must be minutes or seconds")
    terminal_texts_raw = semantics_raw.get("terminal_texts", ["End"])
    if not isinstance(terminal_texts_raw, list):
        raise ValueError("semantics.terminal_texts must be a list")
    terminal_texts = tuple(
        text
        for value in terminal_texts_raw
        if (text := str(value).strip())
    )

    stability_raw = _mapping(root.get("stability", {}), field_name="stability")
    confirmations = int(stability_raw.get("confirmations", 2))
    if confirmations < 1:
        raise ValueError("stability.confirmations must be at least 1")
    latch_completion = stability_raw.get("latch_completion_until_next_cycle", True)
    if not isinstance(latch_completion, bool):
        raise ValueError("stability.latch_completion_until_next_cycle must be true or false")
    unknown_grace_seconds = float(stability_raw.get("unknown_grace_seconds", 15.0))
    if unknown_grace_seconds < 0:
        raise ValueError("stability.unknown_grace_seconds must not be negative")

    diagnostics_raw = _mapping(root.get("diagnostics", {}), field_name="diagnostics")
    transition_directory_raw = diagnostics_raw.get("transition_directory")
    transition_directory: Path | None = None
    if transition_directory_raw:
        transition_directory = Path(str(transition_directory_raw))
        if not transition_directory.is_absolute():
            transition_directory = (
                config_path.parent / transition_directory
            ).resolve()

    calibration_raw = _mapping(root.get("calibration", {}), field_name="calibration")
    calibration_enabled = calibration_raw.get("enabled", False)
    if not isinstance(calibration_enabled, bool):
        raise ValueError("calibration.enabled must be true or false")
    calibration_host = str(calibration_raw.get("host", "127.0.0.1")).strip()
    if not calibration_host:
        raise ValueError("calibration.host must not be empty")
    calibration_port = int(calibration_raw.get("port", 8090))
    if not 1 <= calibration_port <= 65535:
        raise ValueError("calibration.port must be between 1 and 65535")

    mqtt_raw = _mapping(root.get("mqtt", {}), field_name="mqtt")
    mqtt_enabled = bool(mqtt_raw.get("enabled", False))
    mqtt_host = str(mqtt_raw.get("host", "localhost")).strip()
    mqtt_port = int(mqtt_raw.get("port", 1883))
    mqtt_username_raw = mqtt_raw.get("username")
    mqtt_password_raw = mqtt_raw.get("password")
    mqtt_password_file_raw = mqtt_raw.get("password_file")
    if mqtt_password_raw is not None and mqtt_password_file_raw is not None:
        raise ValueError("mqtt.password and mqtt.password_file cannot both be set")
    if mqtt_password_file_raw is not None:
        password_path = Path(str(mqtt_password_file_raw))
        if not password_path.is_absolute():
            password_path = (config_path.parent / password_path).resolve()
        try:
            mqtt_password_raw = password_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"could not read mqtt.password_file: {password_path}") from exc
        if not mqtt_password_raw:
            raise ValueError("mqtt.password_file must not be empty")
    base_topic = str(
        mqtt_raw.get("base_topic", f"appliance_display_sensor/{identifier}")
    ).strip("/")
    discovery_prefix = str(mqtt_raw.get("discovery_prefix", "homeassistant")).strip("/")

    return AppConfig(
        device=DeviceConfig(identifier, name, appliance_type),
        input=InputConfig(input_kind, input_path, camera_config),
        display=DisplayConfig(
            decoder=decoder,
            roi=roi,
            digit_boxes=digit_boxes,
            colon_box=colon_box,
            colon_after=colon_after,
            channel=channel,
            threshold_method=threshold_method,
            threshold_value=threshold_value,
            min_segment_fill=min_segment_fill,
            colon_min_fill=colon_min_fill,
            min_digit_confidence=min_digit_confidence,
            segment_thickness_ratio=segment_thickness_ratio,
            segment_slant_ratio=segment_slant_ratio,
            allowed_glyphs=allowed_glyphs,
            segment_sample_boxes=parse_segment_sample_boxes(
                display_raw.get("segment_sample_boxes"), digit_boxes,
            ),
        ),
        semantics=SemanticsConfig(no_colon_unit, terminal_texts, countdown_format),
        stability=StabilityConfig(
            confirmations,
            latch_completion,
            unknown_grace_seconds,
        ),
        diagnostics=DiagnosticsConfig(transition_directory),
        calibration=CalibrationConfig(
            calibration_enabled,
            calibration_host,
            calibration_port,
        ),
        mqtt=MqttConfig(
            enabled=mqtt_enabled,
            host=mqtt_host,
            port=mqtt_port,
            username=str(mqtt_username_raw) if mqtt_username_raw else None,
            password=str(mqtt_password_raw) if mqtt_password_raw else None,
            base_topic=base_topic,
            discovery_prefix=discovery_prefix,
        ),
    )
