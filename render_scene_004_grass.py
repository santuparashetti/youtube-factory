import os
import numpy as np
from motion_engine import build_compositor, SceneConfig
from motion_engine.renderer import Renderer

IMAGE_PATH = "workspace/jobs/Already_Done/grass-that-refused-to-die-1203/images/scene-004.png"
OUTPUT_PATH = "output/scene-004-grass-animated.mp4"
DURATION = 14.0
H, W = 720, 1280

os.makedirs("output", exist_ok=True)

# ---------------------------------------------------------------------------
# Scene: macro close-up of single grass blade with water droplet.
# Golden hour sun bokeh upper-left (~x:8%, y:10%).
# No human figures. Hero subject = the grass blade (x:40-60%, y:5-90%).
#
# Effects:
#   tree_sway   — narrow mask on blade only, very gentle (macro = tiny movements)
#   sun_rays    — soft golden god rays from the sun bokeh
#   dust_particles — warm golden pollen/dust floating in air
#   slow_push_in   — push toward water droplet (center, slightly upper)
# ---------------------------------------------------------------------------

# Grass blade mask — narrow vertical strip covering the blade
blade_mask = np.zeros((H, W), dtype=bool)
blade_mask[int(H*0.05):int(H*0.88), int(W*0.38):int(W*0.62)] = True

scene = SceneConfig(
    image_path=IMAGE_PATH,
    output_path=OUTPUT_PATH,
    duration_seconds=DURATION,
    fps=30,
    resolution=(W, H),
    figure_boxes=[],          # no human figures in this scene
    effects=[
        "tree_sway",
        "sun_rays",
        "dust_particles",
        "slow_push_in",
    ],
    effect_params={
        "tree_sway": {
            "mask": blade_mask,
            "intensity": 9.0,       # clearly visible — sway must read on screen
            "speed": 0.5,
            "wavelength": 150.0,    # long wave = single smooth body sway
        },
        "sun_rays": {
            "source_x": 0.08,       # golden bokeh sun is upper-left
            "source_y": 0.10,
            "num_rays": 8,
            "ray_spread": 0.45,
            "color": (60, 140, 220),  # warm golden (BGR)
            "base_alpha": 0.16,       # subtle — scene already has beautiful light
            "pulse_speed": 0.20,      # very slow breath
            "ray_length_scale": 2.5,
            "blur_radius": 81,        # very soft — bokeh scene needs feathered rays
        },
        "dust_particles": {
            "count": 70,
            "region_top": 0.05,
            "region_bottom": 0.70,   # floating in the air above ground
            "color": (100, 170, 220),  # warm golden pollen (BGR)
            "max_size": 2,
            "alpha": 0.30,
            "drift_speed": 0.18,     # slow drift — still air, macro world
        },
        "slow_push_in": {
            "zoom_start": 1.0,
            "zoom_end": 1.08,        # slightly more zoom — pulls into the droplet
            "duration": DURATION,
            "center_x": 0.50,        # blade is centered
            "center_y": 0.42,        # droplet is around y:42%
        },
    },
)

print(f"Scene: {IMAGE_PATH} ({W}x{H})")
print(f"Effects: {scene.effects}")
compositor = build_compositor(scene)
renderer = Renderer()
output = renderer.render(scene, compositor)
print(f"Done. {output} ({os.path.getsize(output)/1e6:.1f} MB)")
