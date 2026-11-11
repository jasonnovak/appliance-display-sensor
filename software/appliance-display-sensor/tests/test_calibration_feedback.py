from dataclasses import replace
from pathlib import Path
import unittest

import numpy as np

from appliance_display_sensor.calibration_feedback import inspect_readability
from appliance_display_sensor.config import load_config
from appliance_display_sensor.synthetic import render_display


class ReadabilityFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(Path(__file__).resolve().parents[1] /
                                  'configs/example-seven-segment.yaml')
        self.config = replace(self.config, semantics=replace(self.config.semantics,
                                                            countdown_format='H:MM'))

    def image(self, digits=(1, 1, 2), *, colon=False):
        display = self.config.display
        return render_display(size=(display.roi.width, display.roi.height),
                              digit_boxes=display.digit_boxes, digits=digits,
                              colon_box=display.colon_box, colon_on=colon)

    def codes(self, image, config=None):
        return {item['code'] for item in inspect_readability(
            image, config or self.config)['issues']}

    def test_clean_hmm_does_not_need_colon_or_mutate_pixels(self):
        image = self.image()
        original = image.copy()
        report = inspect_readability(image, self.config)
        self.assertEqual(report['text'], '1:12')
        self.assertEqual(report['colon_role'], 'diagnostic_only')
        self.assertEqual(report['issues'], [])
        np.testing.assert_array_equal(image, original)

    def test_blank_is_not_diagnosed_as_a_camera_fault(self):
        report = inspect_readability(self.image((None, None, None)), self.config)
        self.assertEqual([i['code'] for i in report['issues']], ['blank'])
        self.assertIn('leave the settings alone', report['issues'][0]['message'])

    def test_crop_edge_and_crossed_digit_edge_are_distinct(self):
        image = self.image()
        image[0, 20:70] = 255
        self.assertIn('crop_edge', self.codes(image))
        image = self.image()
        b = self.config.display.digit_boxes[1]
        image[b.y+30:b.y+55, b.x-2:b.x+3] = 255
        report = inspect_readability(image, self.config)
        crossed = [i for i in report['issues'] if i['code'] == 'digit_edge']
        self.assertEqual(crossed[0]['target'], 'digit-2')
        self.assertIn('left', crossed[0]['message'])

    def test_uniform_bright_box_warns_but_bright_led_strokes_do_not(self):
        self.assertNotIn('filled_box', self.codes(self.image()))
        image = self.image()
        b = self.config.display.digit_boxes[1]
        image[b.y:b.y2, b.x:b.x2] = 255
        self.assertIn('filled_box', self.codes(image))

    def test_blue_halo_crossing_box_is_not_called_a_clipped_segment(self):
        image = self.image()
        b = self.config.display.digit_boxes[1]
        image[b.y+30:b.y+55, b.x-2:b.x+3] = (255, 0, 0)
        image[-1, :, :] = (255, 0, 0)
        codes = self.codes(image)
        self.assertNotIn('digit_edge', codes)
        self.assertNotIn('crop_edge', codes)

    def test_small_colon_like_spots_at_digit_boundary_do_not_count_as_segments(self):
        image = self.image()
        b = self.config.display.digit_boxes[1]
        for dy in (30, 80):
            image[b.y+dy:b.y+dy+8, b.x-2:b.x+3] = 255
        self.assertNotIn('digit_edge', self.codes(image))

    def test_low_contrast_below_fixed_cutoff_gives_conditional_advice(self):
        image = self.image()
        image = (image.astype(np.float32) * 0.45).astype(np.uint8)
        codes = self.codes(image)
        self.assertIn('cutoff_high', codes)
        self.assertIn('blank', codes)

    def test_lit_pixels_outside_sampling_regions_are_explained(self):
        image = self.image((None, None, None))
        b = self.config.display.digit_boxes[1]
        image[b.y+25:b.y+45, b.x+25:b.x+45] = 255
        self.assertIn('missed_light', self.codes(image))

    def test_valid_patterns_with_invalid_minutes_report_format(self):
        self.assertIn('format', self.codes(self.image((1, 9, 9))))
        self.assertNotIn('format', self.codes(self.image(('E', 'n', 'd'), colon=True)))

    def test_unbounded_input_is_rejected_before_processing(self):
        with self.assertRaises(ValueError):
            inspect_readability(np.zeros((1001, 1000, 3), np.uint8), self.config)
