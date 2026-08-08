import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pytest
from motion_engine.effects.flicker import LampFlicker
from motion_engine.effects.water import WaterRipple
from motion_engine.compositor import Compositor


FRAME = np.ones((1080, 1920, 3), dtype=np.uint8) * 128


def test_compositor_applies_all():
    effects = [LampFlicker(), WaterRipple()]
    compositor = Compositor(effects)
    result = compositor.render_frame(FRAME.copy(), t=1.0)
    assert result.shape == FRAME.shape
    assert not np.array_equal(result, FRAME), "Compositor made no changes"
    print("✅ Compositor applied effects correctly")


def test_compositor_empty():
    compositor = Compositor([])
    result = compositor.render_frame(FRAME.copy(), t=0.0)
    assert np.array_equal(result, FRAME), "Empty compositor should return unchanged frame"
    print("✅ Empty compositor returns unchanged frame")


def test_compositor_order():
    """Camera effects must be applied after content effects in build_compositor."""
    from motion_engine import build_compositor, SceneConfig
    scene = SceneConfig(
        image_path="assets/test_scene.png",
        output_path="output/order_test.mp4",
        duration_seconds=1.0,
        effects=["slow_push_in", "lamp_flicker"],
    )
    compositor = build_compositor(scene)
    # slow_push_in should be last
    assert compositor.effects[-1].__class__.__name__ == "SlowPushIn"
    print("✅ Camera effect is last in compositor chain")
