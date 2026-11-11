from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Sequence

import numpy as np

from appliance_display_sensor.config import AppConfig, load_config
from appliance_display_sensor.calibration import (
    CalibrationServer,
    CalibrationSession,
)
from appliance_display_sensor.diagnostics import render_diagnostic, save_diagnostic
from appliance_display_sensor.inputs import Picamera2Input, iter_replay, read_image
from appliance_display_sensor.models import ApplianceState
from appliance_display_sensor.pipeline import FrameProcessor, FrameResult
from appliance_display_sensor.publishers import MqttPublisher
from appliance_display_sensor.runtime_health import HealthReporter, RuntimeHealth


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="appliance-display-sensor",
        description="Decode a calibrated appliance display image.",
    )
    parser.add_argument("--config", required=True, help="Path to the YAML configuration")
    parser.add_argument("--image", help="Override the configured image-file path")
    parser.add_argument(
        "--replay-directory",
        help="Process a directory of images in filename order",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Repeat the replay directory until interrupted",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.0,
        help="Seconds to wait between replay frames (default: 0)",
    )
    parser.add_argument(
        "--diagnostics-dir",
        help="Write display-only diagnostic overlays to this directory",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        help="Stop live camera input after this many frames (useful for validation)",
    )
    parser.add_argument(
        "--no-mqtt",
        action="store_true",
        help="Decode and print the state without publishing MQTT messages",
    )
    parser.add_argument("--compact", action="store_true", help="Print compact JSON")
    return parser


def _state_payload(state: ApplianceState, config: AppConfig) -> dict[str, object]:
    payload = state.to_dict(appliance_type=config.device.appliance_type)
    payload["device_name"] = config.device.name
    payload["device_identifier"] = config.device.identifier
    return payload


def _print_json(payload: object, *, compact: bool) -> None:
    print(
        json.dumps(payload, indent=None if compact else 2, sort_keys=True),
        flush=True,
    )


def _write_diagnostic(
    result: FrameResult,
    image: np.ndarray,
    source_path: Path,
    diagnostics_dir: Path | None,
    config: AppConfig,
) -> None:
    if diagnostics_dir is None:
        return
    suffix_name = source_path.suffix.lower().lstrip(".") or "image"
    output_path = diagnostics_dir / f"{source_path.stem}-{suffix_name}.diagnostic.png"
    overlay = render_diagnostic(
        image,
        config.display,
        result.display,
        candidate_state=result.candidate_state,
        stable_state=result.stable_state,
    )
    save_diagnostic(output_path, overlay)


def _write_transition_diagnostic(
    result: FrameResult,
    image: np.ndarray,
    config: AppConfig,
) -> None:
    """Keep bounded, display-only evidence for accepted state transitions."""

    output_directory = config.diagnostics.transition_directory
    if (
        output_directory is None
        or not result.stable_changed
        or result.stable_state is None
    ):
        return

    overlay = render_diagnostic(
        image,
        config.display,
        result.display,
        candidate_state=result.candidate_state,
        stable_state=result.stable_state,
    )
    status = result.stable_state.status
    if status not in {"running", "complete", "unknown"}:
        status = "other"

    # Fixed names intentionally form a small ring: one overall snapshot and at
    # most one snapshot for each semantic state. In particular, an unrecognized
    # terminal message remains in latest-unknown after the panel goes blank,
    # because blank does not produce another accepted state transition.
    try:
        save_diagnostic(output_directory / "latest.diagnostic.png", overlay)
        save_diagnostic(
            output_directory / f"latest-{status}.diagnostic.png",
            overlay,
        )
    except (OSError, RuntimeError) as exc:
        # Diagnostics are optional evidence. A permissions or storage problem
        # must never take the primary sensor or MQTT state offline.
        print(f"warning: could not write transition diagnostic: {exc}", file=sys.stderr, flush=True)


def _run_single(
    *,
    config: AppConfig,
    image_path: Path,
    diagnostics_dir: Path | None,
    no_mqtt: bool,
    compact: bool,
) -> int:
    image = read_image(image_path)
    result = FrameProcessor(config).process(image)
    _write_diagnostic(result, image, image_path, diagnostics_dir, config)
    _print_json(_state_payload(result.candidate_state, config), compact=compact)

    if config.mqtt.enabled and not no_mqtt:
        MqttPublisher(config.device, config.mqtt).publish(result.candidate_state)
    return 0


def _run_replay(
    *,
    config: AppConfig,
    replay_directory: Path,
    loop: bool,
    interval: float,
    diagnostics_dir: Path | None,
    no_mqtt: bool,
    compact: bool,
) -> int:
    processor = FrameProcessor(config)
    publisher = (
        MqttPublisher(config.device, config.mqtt)
        if config.mqtt.enabled and not no_mqtt
        else None
    )

    try:
        if publisher is not None:
            publisher.connect()
        for frame in iter_replay(replay_directory, loop=loop):
            result = processor.process(frame.image)
            _write_diagnostic(result, frame.image, frame.path, diagnostics_dir, config)
            _write_transition_diagnostic(result, frame.image, config)
            event = {
                "source": str(frame.path),
                "candidate": _state_payload(result.candidate_state, config),
                "stable": (
                    _state_payload(result.stable_state, config)
                    if result.stable_state is not None
                    else None
                ),
                "stable_changed": result.stable_changed,
            }
            _print_json(event, compact=compact)

            if publisher is not None and result.stable_changed and result.stable_state is not None:
                publisher.publish_state(result.stable_state)
            if interval > 0:
                time.sleep(interval)
    except KeyboardInterrupt:
        return 130
    finally:
        if publisher is not None:
            publisher.close()
    return 0


def _run_camera(
    *,
    config: AppConfig,
    config_path: Path,
    interval: float,
    max_frames: int | None,
    diagnostics_dir: Path | None,
    no_mqtt: bool,
    compact: bool,
) -> int:
    if config.input.camera is None:
        raise ValueError("picamera2 input requires camera settings")

    runtime_config = config
    processor = FrameProcessor(runtime_config)
    publisher = (
        MqttPublisher(config.device, config.mqtt, diagnostics=True)
        if config.mqtt.enabled and not no_mqtt
        else None
    )
    camera_interval = interval if interval > 0 else None
    runtime_health = RuntimeHealth(stale_after_seconds=max(
        15, 3 * (camera_interval or config.input.camera.frame_interval_seconds),
    ))
    calibration_session = (
        CalibrationSession(
            config_path, config,
            mqtt_health=publisher.health if publisher else lambda: {
                "enabled": False, "connected": False,
            },
        ) if config.calibration.enabled else None
    )
    calibration_server = (
        CalibrationServer(
            config.calibration.host,
            config.calibration.port,
            calibration_session,
        )
        if calibration_session is not None
        else None
    )

    health_reporter = (
        HealthReporter(
            runtime_health, publisher.publish_health,
            calibrating=lambda: calibration_session is not None and calibration_session.active,
            alignment=calibration_session.alignment_health if calibration_session else None,
        ) if publisher is not None else None
    )

    try:
        if calibration_server is not None:
            calibration_server.start()
            print(
                "calibration page listening on "
                f"http://{config.calibration.host}:{config.calibration.port}/",
                file=sys.stderr,
                flush=True,
            )
        if publisher is not None:
            publisher.connect(background=True)
        if health_reporter is not None:
            health_reporter.start()
        with Picamera2Input(config.input.camera) as camera:
            for index, image in enumerate(
                camera.frames(interval_seconds=camera_interval),
                start=1,
            ):
                if calibration_session is not None:
                    pending, frame_revision = (
                        calibration_session.take_pending_config_with_revision()
                    )
                    if pending is not None:
                        if pending.input.camera is None:
                            raise ValueError("calibration requires picamera2 camera settings")
                        camera.apply_config(pending.input.camera)
                        runtime_config = pending
                        processor = FrameProcessor(runtime_config)
                try:
                    result = processor.process(image)
                except (ValueError, RuntimeError) as exc:
                    if calibration_session is None or not calibration_session.active:
                        raise
                    calibration_session.update_frame(
                        image, None, str(exc), config_revision=frame_revision,
                    )
                    runtime_health.observe(None, calibrating=True)
                    continue
                runtime_health.observe(
                    result,
                    calibrating=calibration_session is not None and calibration_session.active,
                )
                if calibration_session is not None:
                    calibration_session.update_frame(image, result, config_revision=frame_revision)
                _write_diagnostic(
                    result,
                    image,
                    Path("camera-latest.jpg"),
                    diagnostics_dir,
                    runtime_config,
                )
                _write_transition_diagnostic(result, image, runtime_config)
                event = {
                    "source": f"picamera2:{runtime_config.input.camera.index}",
                    "frame": index,
                    "candidate": _state_payload(result.candidate_state, runtime_config),
                    "stable": (
                        _state_payload(result.stable_state, runtime_config)
                        if result.stable_state is not None
                        else None
                    ),
                    "stable_changed": result.stable_changed,
                }
                _print_json(event, compact=compact)

                calibration_active = (
                    calibration_session is not None and calibration_session.active
                )
                if (
                    publisher is not None
                    and not calibration_active
                    and result.stable_changed
                    and result.stable_state
                ):
                    publisher.publish_state(result.stable_state)
                if max_frames is not None and index >= max_frames:
                    break
    except KeyboardInterrupt:
        return 130
    except Exception:
        runtime_health.capture_error()
        if health_reporter is not None:
            try:
                health_reporter.report_once()
            except Exception:
                pass
        raise
    finally:
        if health_reporter is not None:
            health_reporter.close()
        if calibration_server is not None:
            calibration_server.close()
        if publisher is not None:
            publisher.close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    if args.image and args.replay_directory:
        raise ValueError("--image and --replay-directory cannot be used together")
    if args.interval < 0:
        raise ValueError("--interval must not be negative")
    if args.max_frames is not None and args.max_frames < 1:
        raise ValueError("--max-frames must be at least 1")

    diagnostics_dir = Path(args.diagnostics_dir).resolve() if args.diagnostics_dir else None
    replay_directory: Path | None = None
    if args.replay_directory:
        replay_directory = Path(args.replay_directory).resolve()
    elif not args.image and config.input.kind == "image_directory":
        replay_directory = config.input.path

    if replay_directory is not None:
        return _run_replay(
            config=config,
            replay_directory=replay_directory,
            loop=args.loop,
            interval=args.interval,
            diagnostics_dir=diagnostics_dir,
            no_mqtt=args.no_mqtt,
            compact=args.compact,
        )

    if not args.image and config.input.kind == "picamera2":
        if args.loop:
            raise ValueError("picamera2 input is already continuous; do not use --loop")
        return _run_camera(
            config=config,
            config_path=config_path,
            interval=args.interval,
            max_frames=args.max_frames,
            diagnostics_dir=diagnostics_dir,
            no_mqtt=args.no_mqtt,
            compact=args.compact,
        )

    if args.loop:
        raise ValueError("--loop requires a replay directory")
    if config.input.kind not in {"image_file", "image_directory"} and not args.image:
        raise ValueError(
            f"input type {config.input.kind!r} is not available yet; "
            "use image_file or image_directory until camera support lands"
        )

    image_path = Path(args.image).resolve() if args.image else config.input.path
    if image_path is None:
        raise ValueError("an image path is required through input.path or --image")
    return _run_single(
        config=config,
        image_path=image_path,
        diagnostics_dir=diagnostics_dir,
        no_mqtt=args.no_mqtt,
        compact=args.compact,
    )
