import os
from motion_engine import build_compositor, SceneConfig
from motion_engine.renderer import Renderer

IMAGE_PATH = "workspace/jobs/when-everything-feels-wrong/images/scene-012.png"
OUTPUT_PATH = "output/scene-012-animated.mp4"
DURATION = 14.0
H, W = 940, 1672

os.makedirs("output", exist_ok=True)

# Scene: coastal beach, golden hour, three figures, ocean upper-left.
# Ocean mostly blocked by back-view figure → WaterRipple skipped by engine
# (rule: <8% unblocked water). Using sun_rays instead.

scene = SceneConfig(
    image_path=IMAGE_PATH,
    output_path=OUTPUT_PATH,
    duration_seconds=DURATION,
    fps=30,
    resolution=(W, H),
    figure_boxes=[
        (0.00, 0.05, 0.32, 1.00),   # back-view figure (far left, close camera)
        (0.34, 0.12, 0.58, 0.94),   # middle standing figure
        (0.57, 0.12, 0.82, 0.94),   # elder figure (right)
    ],
    effects=[
        "sun_rays",
        "dust_particles",
        "mist_drift",
        "slow_push_in",
    ],
    effect_params={
        "sun_rays": {
            "source_x": 0.08,
            "source_y": 0.10,
            "num_rays": 10,
            "ray_spread": 0.5,
            "color": (70, 150, 225),
            "base_alpha": 0.20,
            "pulse_speed": 0.25,
            "ray_length_scale": 2.0,
            "blur_radius": 71,
        },
        "dust_particles": {
            "count": 160,
            "region_top": 0.08,
            "region_bottom": 0.75,
            "color": (155, 190, 218),
            "max_size": 3,
            "alpha": 0.45,
            "drift_speed": 0.28,
            # exclude_mask auto-injected from figure_boxes by engine
        },
        "mist_drift": {
            "region_bottom": 0.50,
            "opacity": 0.07,
            "drift_speed": 0.03,
            "color": (220, 215, 200),
        },
        "slow_push_in": {
            "zoom_start": 1.0,
            "zoom_end": 1.06,
            "duration": DURATION,
            "center_x": 0.50,
            "center_y": 0.50,
        },
    },
)

print(f"Scene: {IMAGE_PATH} ({W}x{H})")
print(f"Effects: {scene.effects}")
compositor = build_compositor(scene)
renderer = Renderer()
output = renderer.render(scene, compositor)
print(f"Done. {output} ({os.path.getsize(output)/1e6:.1f} MB)")
