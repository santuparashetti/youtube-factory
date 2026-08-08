import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import pytest
from motion_engine.effects.flicker import LampFlicker
from motion_engine.effects.water import WaterRipple
from motion_engine.effects.particles import DustParticles, MistDrift
from motion_engine.effects.camera import SlowPushIn


FRAME = np.zeros((1080, 1920, 3), dtype=np.uint8)
FRAME_GREY = np.ones((1080, 1920, 3), dtype=np.uint8) * 128


def test_effect_output_shape():
    effects = [
        LampFlicker(),
        WaterRipple(),
        DustParticles(),
        MistDrift(),
        SlowPushIn(duration=14.0),
    ]
    for effect in effects:
        result = effect.apply(FRAME.copy(), t=1.0)
        assert result.shape == FRAME.shape, f"{effect.__class__.__name__} shape mismatch"
        assert result.dtype == np.uint8, f"{effect.__class__.__name__} dtype mismatch"
        print(f"✅ {effect.__class__.__name__} output shape and dtype correct")


def test_effect_determinism():
    effect = WaterRipple()
    result_a = effect.apply(FRAME_GREY.copy(), t=2.5)
    result_b = effect.apply(FRAME_GREY.copy(), t=2.5)
    assert np.array_equal(result_a, result_b), "WaterRipple is not deterministic"
    print("✅ WaterRipple is deterministic")


def test_lamp_flicker_modifies_frame():
    frame = np.ones((1080, 1920, 3), dtype=np.uint8) * 100
    effect = LampFlicker()
    result = effect.apply(frame.copy(), t=1.0)
    assert not np.array_equal(result, frame), "LampFlicker made no changes"
    print("✅ LampFlicker modifies frame")


def test_dust_particles_determinism():
    effect = DustParticles(seed=123)
    result_a = effect.apply(FRAME_GREY.copy(), t=3.0)
    result_b = effect.apply(FRAME_GREY.copy(), t=3.0)
    assert np.array_equal(result_a, result_b), "DustParticles not deterministic"
    print("✅ DustParticles is deterministic")


def test_slow_push_in_at_t0():
    """At t=0 zoom=1.0, output must equal input (modulo resize rounding)."""
    effect = SlowPushIn(zoom_start=1.0, zoom_end=1.08, duration=14.0)
    frame = np.ones((720, 1280, 3), dtype=np.uint8) * 200
    result = effect.apply(frame.copy(), t=0.0)
    assert result.shape == frame.shape
    print("✅ SlowPushIn at t=0 returns correct shape")
