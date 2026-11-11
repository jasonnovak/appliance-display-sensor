from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from appliance_display_sensor.config import load_config  # noqa: E402
from appliance_display_sensor.synthetic import parse_synthetic_text, render_display  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic seven-segment fixture")
    parser.add_argument("--config", default="configs/example-seven-segment.yaml")
    parser.add_argument("--text", default="1:23")
    parser.add_argument("--output", default="sample-display.png")
    args = parser.parse_args()

    config = load_config(args.config)
    digits, colon_on = parse_synthetic_text(args.text, len(config.display.digit_boxes))
    image = render_display(
        size=(config.display.roi.width, config.display.roi.height),
        digit_boxes=config.display.digit_boxes,
        digits=digits,
        colon_box=config.display.colon_box,
        colon_on=colon_on,
        thickness_ratio=config.display.segment_thickness_ratio,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), image):
        raise RuntimeError(f"could not write {output_path}")
    print(output_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

