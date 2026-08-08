import os
import numpy as np
from motion_engine import build_compositor, SceneConfig
from motion_engine.renderer import Renderer

IMAGE_PATH = "workspace/jobs/when-everything-feels-wrong/images/scene-032.png"
OUTPUT_PATH = "output/scene-032-animated.mp4"
DURATION = 14.0
H, W = 940, 1672

os.makedirs("output", exist_ok=True)

# Scene: dark rustic interior, dusk, kerosene lamp on right side.
# Lamp is at x:72-82%, y:40-55% — must pass explicit mask or default hits center.

# Lamp glow region — lamp body + warm wall glow spreading right
lamp_mask = np.zeros((H, W), dtype=bool)
lamp_mask[int(H*0.28):int(H*0.75), int(W*0.60):int(W*0.96)] = True

scene = SceneConfig(
    image_path=IMAGE_PATH,
    output_path=OUTPUT_PATH,
    duration_seconds=DURATION,
    fps=30,
    resolution=(W, H),
    figure_boxes=[
        (0.08, 0.12, 0.30, 1.00),   # standing figure (left)
        (0.58, 0.22, 0.80, 0.90),   # seated figure (right, near lamp)
    ],
    effects=[
        "lamp_flicker",
        "dust_particles",
        "mist_drift",
        "slow_push_in",
    ],
    effect_params={
        "lamp_flicker": {
            "mask": lamp_mask,          # explicit — lamp is right side, not center
            "base_brightness": 1.0,
            "flicker_intensity": 0.22,  # clearly visible warm glow variation
        },
        "dust_particles": {
            "count": 120,
            "region_top": 0.10,
            "region_bottom": 0.80,
            "color": (100, 160, 210),
            "max_size": 2,
            "alpha": 0.40,
            "drift_speed": 0.15,
            # exclude_mask auto-injected from figure_boxes by engine
        },
        "mist_drift": {
            "region_bottom": 0.55,
            "opacity": 0.06,
            "drift_speed": 0.02,
            "color": (180, 170, 160),
        },
        "slow_push_in": {
            "zoom_start": 1.0,
            "zoom_end": 1.07,
            "duration": DURATION,
            "center_x": 0.62,
            "center_y": 0.52,
        },
    },
)

print(f"Scene: {IMAGE_PATH} ({W}x{H})")
print(f"Effects: {scene.effects}")
compositor = build_compositor(scene)
renderer = Renderer()
output = renderer.render(scene, compositor)
print(f"Done. {output} ({os.path.getsize(output)/1e6:.1f} MB)")
