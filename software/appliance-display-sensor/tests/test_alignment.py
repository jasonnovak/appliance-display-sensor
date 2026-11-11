from __future__ import annotations

import tempfile
import unittest
import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from appliance_display_sensor.alignment import AlignmentMonitor
from appliance_display_sensor.models import Rect


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "reference.alignment.npz"
        self.monitor = AlignmentMonitor(self.path)
        self.image = np.full((240, 400, 3), 20, np.uint8)
        cv2.putText(self.image, 'LOCK', (92, 104), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (180, 180, 180), 2, cv2.LINE_AA)
        self.box = Rect(85, 78, 90, 42)
        self.signature = "a" * 64

    def capture(self):
        self.monitor.capture(self.image, self.box, self.signature, [])

    def update(self, image, second, **kwargs):
        with patch('appliance_display_sensor.alignment.time.monotonic', return_value=second):
            self.monitor.update(image, self.signature, **kwargs)

    def test_reference_reload_and_stable_anchor(self):
        self.capture()
        self.assertLess(self.path.stat().st_size, 96 * 1024)
        self.monitor = AlignmentMonitor(self.path)
        self.update(self.image, 0)
        self.update(self.image, 5)
        self.assertEqual(self.monitor.status, "aligned")
        self.assertFalse(self.monitor.latched)

    def test_digit_changes_outside_anchor_do_not_look_like_movement(self):
        self.capture()
        image = self.image.copy()
        cv2.putText(image, '38', (220, 210), cv2.FONT_HERSHEY_SIMPLEX,
                    2, (255, 0, 0), 3)
        self.update(image, 0)
        self.update(image, 5)
        self.assertEqual(self.monitor.status, "aligned")

    def test_translation_needs_three_checks_and_return_needs_two(self):
        self.capture()
        shifted = cv2.warpAffine(self.image, np.float32([[1, 0, 9], [0, 1, 6]]), (400, 240))
        for second in (0, 5):
            self.update(shifted, second)
            self.assertFalse(self.monitor.latched)
        self.update(shifted, 10)
        self.assertEqual(self.monitor.status, "moved")
        self.assertEqual(self.monitor.shift, (9, 6))
        self.update(self.image, 15)
        self.assertTrue(self.monitor.latched)
        self.update(self.image, 20)
        self.assertEqual(self.monitor.status, "aligned")
        self.assertFalse(self.monitor.latched)

    def test_brightness_change_and_small_vibration(self):
        self.capture()
        dimmer = np.clip(self.image.astype(float) * 0.55 + 10, 0, 255).astype(np.uint8)
        dimmer = cv2.warpAffine(dimmer, np.float32([[1, 0, 2], [0, 1, 1]]), (400, 240))
        self.update(dimmer, 0)
        self.update(dimmer, 5)
        self.assertEqual(self.monitor.status, "aligned")

    def test_darkness_does_not_clear_confirmed_movement(self):
        self.capture()
        shifted = cv2.warpAffine(self.image, np.float32([[1, 0, 9], [0, 1, 6]]), (400, 240))
        for second in (0, 5, 10):
            self.update(shifted, second)
        self.update(np.zeros_like(self.image), 15)
        self.assertEqual(self.monitor.status, "uncheckable")
        self.assertTrue(self.monitor.latched)

    def test_flat_overlapping_out_of_bounds_and_oversized_anchors_are_rejected(self):
        for box in (Rect(0, 0, 20, 40), Rect(300, 100, 150, 60), Rect(0, 0, 161, 50)):
            with self.assertRaises(ValueError):
                self.monitor.capture(self.image, box, self.signature, [])
        with self.assertRaises(ValueError):
            self.monitor.capture(self.image, self.box, self.signature, [self.box])
        with self.assertRaises(ValueError):
            self.monitor.capture(np.zeros_like(self.image), self.box, self.signature, [])
        self.assertFalse(self.path.exists())

    def test_bad_replacement_preserves_current_reference(self):
        self.capture()
        saved = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.monitor.capture(np.zeros_like(self.image), self.box, self.signature, [])
        self.assertEqual(self.path.read_bytes(), saved)

    def test_profile_change_test_mode_staleness_and_rate_limit(self):
        self.capture()
        self.update(self.image, 0)
        with patch.object(self.monitor, '_match', side_effect=AssertionError('too soon')):
            self.update(self.image, 1)
        with patch('appliance_display_sensor.alignment.time.monotonic', return_value=20):
            self.assertEqual(self.monitor.snapshot()["status"], "stale")
        self.monitor.update(self.image, "b" * 64)
        self.assertEqual(self.monitor.status, "needs_reference")
        self.update(self.image, 25, testing=True)
        self.assertEqual(self.monitor.status, "needs_reference")

    def test_invalid_persisted_reference_does_not_crash_service(self):
        self.path.write_bytes(b'not an archive')
        self.assertEqual(AlignmentMonitor(self.path).status, "reference_unavailable")
        np.savez_compressed(self.path, metadata='{}', template=np.zeros((200, 200)))
        self.assertEqual(AlignmentMonitor(self.path).status, "reference_unavailable")

    def test_oversized_array_header_is_rejected_before_numpy_load(self):
        header = io.BytesIO()
        np.lib.format.write_array_header_1_0(header, {
            "descr": "|u1", "fortran_order": False, "shape": (10_000_000, 10_000_000),
        })
        metadata = io.BytesIO()
        np.save(metadata, '{}', allow_pickle=False)
        with zipfile.ZipFile(self.path, 'w') as archive:
            archive.writestr('template.npy', header.getvalue())
            archive.writestr('metadata.npy', metadata.getvalue())
        with patch('appliance_display_sensor.alignment.np.load',
                   side_effect=AssertionError('unsafe load')):
            self.assertEqual(AlignmentMonitor(self.path).status, "reference_unavailable")

    def test_repeated_pattern_is_rejected_as_ambiguous(self):
        image = np.full_like(self.image, 20)
        for x in range(70, 220, 12):
            for y in range(55, 145, 12):
                cv2.rectangle(image, (x, y), (x + 5, y + 5), (180, 180, 180), -1)
        with self.assertRaises(ValueError):
            self.monitor.capture(image, self.box, self.signature, [])

    def test_failed_write_preserves_reference_and_leaves_no_temporary_file(self):
        self.capture()
        before = self.path.read_bytes()
        with patch('appliance_display_sensor.alignment.os.replace',
                   side_effect=OSError('no write')):
            with self.assertRaises(OSError):
                self.capture()
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)

    def test_rotation_or_large_move_is_uncheckable_not_falsely_aligned(self):
        self.capture()
        rotated = cv2.warpAffine(self.image, cv2.getRotationMatrix2D((130, 100), 20, 1), (400, 240))
        for second in (0, 5, 10):
            self.update(rotated, second)
        self.assertNotEqual(self.monitor.status, "aligned")
        self.update(np.roll(self.image, 85, axis=1), 15)
        self.assertEqual(self.monitor.status, "uncheckable")

    def test_forget_removes_only_reference(self):
        self.capture()
        other = self.path.parent / 'config.yaml'
        other.write_text('unchanged')
        self.monitor.clear()
        self.assertFalse(self.path.exists())
        self.assertEqual(other.read_text(), 'unchanged')
        self.assertEqual(self.monitor.status, "not_configured")


if __name__ == '__main__':
    unittest.main()
