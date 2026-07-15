import unittest

import numpy as np
import pytest

pytest.importorskip("moviepy")
from worker.services.media_service import MediaService


class FakeClip:
    def __init__(self):
        self.transformed = None

    def transform(self, callback):
        self.transformed = callback
        return self


class CompositionFrameEffectTests(unittest.TestCase):
    def test_soft_glow_and_temporal_blur_install_a_real_frame_transform(self):
        service = MediaService.__new__(MediaService)
        clip = FakeClip()

        result = service._apply_composition_frame_effects(clip, ["soft_glow", "motion_blur"])

        self.assertIs(result, clip)
        self.assertIsNotNone(clip.transformed)
        current = np.full((8, 8, 3), 120, dtype=np.uint8)
        previous = np.full((8, 8, 3), 20, dtype=np.uint8)
        rendered = clip.transformed(lambda timestamp: current if timestamp >= 1 else previous, 1.0)
        self.assertEqual(current.shape, rendered.shape)
        self.assertFalse(np.array_equal(current, rendered))

    def test_unknown_effect_does_not_install_a_transform(self):
        service = MediaService.__new__(MediaService)
        clip = FakeClip()

        self.assertIs(clip, service._apply_composition_frame_effects(clip, ["not-supported"]))
        self.assertIsNone(clip.transformed)
