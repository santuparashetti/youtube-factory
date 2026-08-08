import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
from motion_engine import build_compositor, SceneConfig
from motion_engine.renderer import Renderer


@pytest.fixture(autouse=True)
def ensure_output_dir():
    os.makedirs("output", exist_ok=True)


def test_renderer_produces_mp4():
    scene = SceneConfig(
        image_path="assets/test_scene.png",
        output_path="output/test_render.mp4",
        duration_seconds=3.0,
        fps=30,
        resolution=(1280, 720),
        effects=["dust_particles", "slow_push_in"],
    )
    compositor = build_compositor(scene)
    renderer = Renderer()
    output = renderer.render(scene, compositor)

    assert os.path.exists(output)
    assert os.path.getsize(output) > 50_000
    print(f"✅ Renderer produced valid MP4: {output} ({os.path.getsize(output):,} bytes)")


def test_full_pipeline_visual():
    scene = SceneConfig(
        image_path="assets/test_scene.png",
        output_path="output/visual_review.mp4",
        duration_seconds=5.0,
        fps=30,
        resolution=(1280, 720),
        effects=["lamp_flicker", "water_ripple", "dust_particles", "mist_drift", "slow_push_in"],
    )
    compositor = build_compositor(scene)
    renderer = Renderer()
    output = renderer.render(scene, compositor)
    assert os.path.exists(output)
    print(f"✅ Visual review clip ready: {output}")
    print("   → Open this file and review quality before proceeding")
