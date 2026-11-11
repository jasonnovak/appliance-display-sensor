from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import test_calibration as fixtures
from appliance_display_sensor.calibration import (
    CalibrationSession, build_candidate_config, optical_profile,
)
from appliance_display_sensor.config import load_config
from appliance_display_sensor.decoders.seven_segment import segment_rectangles
from appliance_display_sensor.diagnostics import render_diagnostic
from appliance_display_sensor.pipeline import FrameProcessor


class SegmentProfileTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'config.yaml'
        self.path.write_text(fixtures.CONFIG, encoding='utf-8')
        self.config = load_config(self.path)
        d = self.config.display
        box = d.digit_boxes[0]
        self.samples = {
            k: [r.x / box.width, r.y / box.height, r.width / box.width, r.height / box.height]
            for k, r in segment_rectangles(
                box.width, box.height, d.segment_thickness_ratio, d.segment_slant_ratio,
            ).items()
        }

    def candidate(self, samples):
        return build_candidate_config(self.path, {'display': {'segment_sample_boxes': samples}})

    def test_absent_and_null_preserve_automatic_decoder_and_v1_export(self):
        candidate, raw = self.candidate(None)
        self.assertEqual(candidate, self.config)
        self.assertNotIn('segment_sample_boxes', raw['display'])
        profile = optical_profile(candidate)
        self.assertEqual(profile['version'], 1)
        self.assertNotIn('segment_sample_boxes', profile['calibration']['display'])

    def test_custom_samples_round_trip_in_v2_without_credentials(self):
        config, _ = self.candidate(self.samples)
        profile = json.loads(json.dumps(optical_profile(config)))
        self.assertEqual(profile['version'], 2)
        self.assertEqual(profile['calibration']['display']['segment_sample_boxes'], self.samples)
        self.assertNotIn('do-not-expose', json.dumps(profile))
        session = CalibrationSession(self.path, self.config)
        before = self.path.read_bytes()
        session.import_profile(profile)
        self.assertEqual(session.take_pending_config().display.segment_sample_boxes,
                         config.display.segment_sample_boxes)
        self.assertEqual(self.path.read_bytes(), before)
        session.cancel()
        self.assertIsNone(session.take_pending_config().display.segment_sample_boxes)

    def test_old_profile_resets_custom_layout_not_a_hybrid(self):
        import yaml
        custom, raw = self.candidate(self.samples)
        self.path.write_text(yaml.safe_dump(raw), encoding='utf-8')
        session = CalibrationSession(self.path, custom)
        session.import_profile(optical_profile(self.config))
        self.assertIsNone(session.take_pending_config().display.segment_sample_boxes)
        self.assertIsNotNone(load_config(self.path).display.segment_sample_boxes)

    def test_rejects_malformed_outside_nonfinite_and_subpixel_samples(self):
        bad_values = [[], {}, {'a': [0, 0, .1, .1]}]
        for rectangle in ([0, 0, .1], ['0', 0, .1, .1], [True, 0, .1, .1],
                          [0, 0, float('nan'), .1], [0, 0, float('inf'), .1],
                          [-.1, 0, .2, .2], [.9, 0, .2, .2], [0, 0, 0, .1],
                          [0, 0, .00001, .1], [0, .95, .1, .1]):
            samples = copy.deepcopy(self.samples)
            samples['a'] = rectangle
            bad_values.append(samples)
        for value in bad_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.candidate(value)

    def test_samples_must_cover_pixels_in_every_digit_not_just_first(self):
        samples = copy.deepcopy(self.samples)
        samples['a'] = [0, 0, .01, .1]  # one pixel at width 70; zero at width 10
        with self.assertRaisesRegex(ValueError, 'one pixel'):
            build_candidate_config(self.path, {'display': {
                'segment_sample_boxes': samples,
                'digit_boxes': [[0, 0, 70, 120], [80, 0, 10, 120]],
                'colon_box': None, 'colon_after': None,
            }})

    def test_generated_seed_is_pixel_identical_and_custom_ignores_slant_thickness(self):
        custom, _ = self.candidate(self.samples)
        d = custom.display
        auto = segment_rectangles(70, 120, d.segment_thickness_ratio, d.segment_slant_ratio)
        self.assertEqual(auto, segment_rectangles(70, 120, .9, -.4, d.segment_sample_boxes))
        image = fixtures.CalibrationTests.image(self, self.config)
        base = FrameProcessor(self.config).process(image)
        result = FrameProcessor(custom).process(image)
        self.assertEqual(base.display, result.display)
        changed = replace(custom, display=replace(d, segment_thickness_ratio=.8,
                                                  segment_slant_ratio=.4))
        self.assertEqual(result.display, FrameProcessor(changed).process(image).display)

    def test_overlay_uses_same_custom_rectangles_as_decoder(self):
        custom, _ = self.candidate(self.samples)
        image = fixtures.CalibrationTests.image(self, self.config)
        result = FrameProcessor(custom).process(image)
        with patch('appliance_display_sensor.diagnostics.segment_rectangles',
                   wraps=segment_rectangles) as rectangles:
            render_diagnostic(image, custom.display, result.display)
        self.assertEqual(rectangles.call_count, 3)
        for call in rectangles.call_args_list:
            self.assertEqual(call.args[-1], custom.display.segment_sample_boxes)

    def test_version_schema_rejects_silently_ignored_custom_fields(self):
        session = CalibrationSession(self.path, self.config)
        profile = optical_profile(self.config)
        profile['calibration']['display']['segment_sample_boxes'] = self.samples
        with self.assertRaises(ValueError):
            session.import_profile(profile)  # v1 cannot contain a v2 field
        profile['version'] = 2
        del profile['calibration']['display']['segment_sample_boxes']
        with self.assertRaises(ValueError):
            session.import_profile(profile)
        profile['version'] = 3
        with self.assertRaises(ValueError):
            session.import_profile(profile)
