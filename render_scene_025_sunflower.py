import os
import numpy as np
from motion_engine import build_compositor, SceneConfig
from motion_engine.renderer import Renderer

IMAGE_PATH = "workspace/jobs/Already_Done/a-word-for-those-who-say-i-can-not-do-anything/images/scene-025.png"
OUTPUT_PATH = "output/scene-025-sunflower-animated.mp4"
DURATION = 14.0
H, W = 940, 1672   # 941 → 940 (H.264 even height)

os.makedirs("output", exist_ok=True)

# ---------------------------------------------------------------------------
# Scene: hero sunflower in heavy rain, overcast/stormy, field of drooping
# sunflowers in background. Rain already visible in image — animate it.
# No human figures.
#
# Hero sunflower: x:50-88%, y:10-90% (stem + head, right-center)
# Rain angle: ~3° (nearly vertical, matches existing streaks)
# No sun rays — fully overcast. No dust — it's raining.
# ---------------------------------------------------------------------------

# Sunflower sway mask — the hero plant stem + head
sunflower_mask = np.zeros((H, W), dtype=bool)
sunflower_mask[int(H*0.08):int(H*0.92), int(W*0.48):int(W*0.90)] = True

scene = SceneConfig(
    image_path=IMAGE_PATH,
    output_path=OUTPUT_PATH,
    duration_seconds=DURATION,
    fps=30,
    resolution=(W, H),
    figure_boxes=[],   # no human figures
    effects=[
        "rain",           # continue the existing rain — heavy, near-vertical
        "tree_sway",      # hero sunflower bending in the wind
        "fog",            # deepen the stormy background atmosphere
        "slow_push_in",   # cinematic push into the sunflower face
    ],
    effect_params={
        "rain": {
            "count": 280,
            "angle": 3.0,           # nearly vertical — matches existing streaks
            "speed": 580.0,
            "length": 22,
            "color": (205, 210, 212),  # cool grey-white raindrops (BGR)
            "alpha": 0.42,
        },
        "tree_sway": {
            "mask": sunflower_mask,
            "intensity": 4.0,       # visible sway — heavy rain = strong wind
            "speed": 0.7,
            "wavelength": 250.0,    # very long wave = single slow full-body sway
        },
        "fog": {
            "region_bottom": 0.72,  # background mist in lower 72% — stormy depth
            "opacity": 0.14,
            "drift_speed": 0.04,
            "color": (175, 180, 178),  # cool grey storm mist (BGR)
            "layers": 3,
        },
        "slow_push_in": {
            "zoom_start": 1.0,
            "zoom_end": 1.07,
            "duration": DURATION,
            "center_x": 0.66,       # push toward sunflower face (right-center)
            "center_y": 0.38,       # flower head is upper portion
        },
    },
)

print(f"Scene: {IMAGE_PATH} ({W}x{H})")
print(f"Effects: {scene.effects}")
compositor = build_compositor(scene)
renderer = Renderer()
output = renderer.render(scene, compositor)
print(f"Done. {output} ({os.path.getsize(output)/1e6:.1f} MB)")
