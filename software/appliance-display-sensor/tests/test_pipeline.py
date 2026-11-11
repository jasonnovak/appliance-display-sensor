from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr
from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import cv2

from appliance_display_sensor.config import load_config
from appliance_display_sensor.cli import _write_transition_diagnostic
from appliance_display_sensor.diagnostics import render_diagnostic
from appliance_display_sensor.inputs import list_replay_images
from appliance_display_sensor.pipeline import FrameProcessor
from appliance_display_sensor.synthetic import render_display


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "example-seven-segment.yaml"


class FramePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(CONFIG_PATH)
        self.observed_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

    def image(self, glyphs: tuple[str | int | None, ...], *, colon: bool = False):
        return render_display(
            size=(self.config.display.roi.width, self.config.display.roi.height),
            digit_boxes=self.config.display.digit_boxes,
            digits=glyphs,
            colon_box=self.config.display.colon_box,
            colon_on=colon,
            thickness_ratio=self.config.display.segment_thickness_ratio,
        )

    def test_stabilizes_changes_and_latches_completion_across_blank(self) -> None:
        processor = FrameProcessor(self.config)
        forty_one = self.image((None, 4, 1))
        forty = self.image((None, 4, 0))
        end = self.image(("E", "n", "d"))
        blank = self.image((None, None, None))

        self.assertIsNone(processor.process(forty_one, now=self.observed_at).stable_state)
        result = processor.process(forty_one, now=self.observed_at)
        self.assertTrue(result.stable_changed)
        self.assertEqual(result.stable_state.remaining_minutes, 41)

        result = processor.process(forty, now=self.observed_at)
        self.assertFalse(result.stable_changed)
        self.assertEqual(result.stable_state.remaining_minutes, 41)
        result = processor.process(forty, now=self.observed_at)
        self.assertTrue(result.stable_changed)
        self.assertEqual(result.stable_state.remaining_minutes, 40)

        processor.process(end, now=self.observed_at)
        result = processor.process(end, now=self.observed_at)
        self.assertTrue(result.stable_changed)
        self.assertEqual(result.stable_state.status, "complete")

        for _ in range(30):
            result = processor.process(blank, now=self.observed_at)
            self.assertFalse(result.stable_changed)
            self.assertEqual(result.stable_state.status, "complete")

    def test_hmm_pipeline_accepts_missing_or_phantom_colon_and_latches_end(self):
        config = replace(self.config, semantics=replace(self.config.semantics,
                                                       countdown_format="H:MM"))
        processor = FrameProcessor(config)
        for glyphs, colon, text, minutes, status in (
            ((1, 1, 2), False, "1:12", 72, "running"),
            ((None, 2, 1), True, "21", 21, "running"),
            ((None, 4, 0), True, "40", 40, "running"),  # Adaptive increase is valid.
            (("E", "n", "d"), True, "End", 0, "complete"),
        ):
            image = self.image(glyphs, colon=colon)
            processor.process(image, now=self.observed_at)
            result = processor.process(image, now=self.observed_at)
            self.assertEqual(result.display.colon_on, colon)
            self.assertEqual(result.stable_state.display_text, text)
            self.assertEqual(result.stable_state.remaining_minutes, minutes)
            self.assertEqual(result.stable_state.status, status)
        blank = processor.process(self.image((None, None, None)), now=self.observed_at)
        self.assertEqual(blank.candidate_state.status, "unknown")
        self.assertEqual(blank.stable_state.status, "complete")

    def test_diagnostic_is_cropped_to_display_roi(self) -> None:
        processor = FrameProcessor(self.config)
        image = self.image((1, 1, 0), colon=True)
        result = processor.process(image, now=self.observed_at)

        diagnostic = render_diagnostic(
            image,
            self.config.display,
            result.display,
            candidate_state=result.candidate_state,
            stable_state=result.stable_state,
        )

        self.assertEqual(
            diagnostic.shape[:2],
            (self.config.display.roi.height, self.config.display.roi.width),
        )

    def test_replay_images_are_sorted_and_filtered(self) -> None:
        image = self.image((None, 4, 1))
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            self.assertTrue(cv2.imwrite(str(directory / "02-second.png"), image))
            self.assertTrue(cv2.imwrite(str(directory / "01-first.jpg"), image))
            (directory / "notes.txt").write_text("not an image", encoding="utf-8")

            paths = list_replay_images(directory)

        self.assertEqual([path.name for path in paths], ["01-first.jpg", "02-second.png"])

    def test_transition_diagnostics_are_bounded_by_semantic_state(self) -> None:
        processor = FrameProcessor(self.config)
        running = self.image((None, 4, 1))

        with tempfile.TemporaryDirectory() as temporary_directory:
            diagnostics_directory = Path(temporary_directory) / "transitions"
            configured = replace(
                self.config,
                diagnostics=replace(
                    self.config.diagnostics,
                    transition_directory=diagnostics_directory,
                ),
            )
            first = processor.process(running, now=self.observed_at)
            _write_transition_diagnostic(first, running, configured)
            self.assertFalse(diagnostics_directory.exists())

            accepted = processor.process(running, now=self.observed_at)
            _write_transition_diagnostic(accepted, running, configured)

            self.assertEqual(
                sorted(path.name for path in diagnostics_directory.iterdir()),
                ["latest-running.diagnostic.png", "latest.diagnostic.png"],
            )

    def test_transition_diagnostic_failure_does_not_stop_processing(self) -> None:
        processor = FrameProcessor(self.config)
        running = self.image((None, 4, 1))
        configured = replace(
            self.config,
            diagnostics=replace(
                self.config.diagnostics,
                transition_directory=Path("unwritable"),
            ),
        )
        processor.process(running, now=self.observed_at)
        accepted = processor.process(running, now=self.observed_at)

        stderr = StringIO()
        with (
            patch(
                "appliance_display_sensor.cli.save_diagnostic",
                side_effect=OSError("read-only file system"),
            ),
            redirect_stderr(stderr),
        ):
            _write_transition_diagnostic(accepted, running, configured)

        self.assertIn("could not write transition diagnostic", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
