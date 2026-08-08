import os
from motion_engine import build_compositor, EFFECT_REGISTRY
from motion_engine.scene import SceneConfig
from motion_engine.renderer import Renderer


def main():
    os.makedirs("output", exist_ok=True)

    scene = SceneConfig(
        image_path="assets/test_scene.png",
        output_path="output/test_output.mp4",
        duration_seconds=14.0,
        fps=30,
        resolution=(1920, 1080),
        effects=["lamp_flicker", "water_ripple", "dust_particles", "slow_push_in"],
        effect_params={
            "water_ripple": {"intensity": 3.0, "speed": 0.8},
            "dust_particles": {"count": 70, "alpha": 0.3},
            "slow_push_in": {"zoom_end": 1.08, "duration": 14.0},
        },
    )

    print(f"Building compositor with effects: {scene.effects}")
    compositor = build_compositor(scene)

    print(f"Rendering {scene.duration_seconds}s clip at {scene.fps}fps...")
    renderer = Renderer()
    output = renderer.render(scene, compositor)

    print(f"Done. Output: {output}")


if __name__ == "__main__":
    main()
