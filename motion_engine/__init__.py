import warnings
import numpy as np

from .effects.flicker import LampFlicker, CandleFlicker, TorchFlicker
from .effects.water import WaterRipple
from .effects.particles import DustParticles, MistDrift
from .effects.camera import SlowPushIn, SlowPullOut
from .effects.light import SunRays
from .effects.nature import (
    TreeSway, GrassMovement, CloudMovement,
    WaterfallFlow, FallingLeaves, Birds, Butterflies,
)
from .effects.weather import Rain, Snow, Fog, Smoke
from .compositor import Compositor
from .scene import SceneConfig

EFFECT_REGISTRY = {
    # Lighting / fire — all require a spatial mask
    "lamp_flicker":   LampFlicker,
    "candle_flicker": CandleFlicker,
    "torch_flicker":  TorchFlicker,
    "sun_rays":       SunRays,
    # Atmospheric — full-frame, no mask needed
    "mist_drift":     MistDrift,
    "fog":            Fog,
    "fog_drift":      Fog,       # canonical LLM name → same class
    # Water / displacement
    "water_ripple":   WaterRipple,
    "waterfall_flow": WaterfallFlow,
    # Nature / displacement
    "tree_sway":      TreeSway,
    "grass_movement": GrassMovement,
    "grass_sway":     GrassMovement,  # canonical LLM name → same class
    "cloud_movement": CloudMovement,
    # Particles
    "dust_particles": DustParticles,
    "falling_leaves": FallingLeaves,
    "birds":          Birds,
    "butterflies":    Butterflies,
    # Weather particles
    "rain":           Rain,
    "snow":           Snow,
    "smoke":          Smoke,
    # Camera (always applied last)
    "slow_push_in":   SlowPushIn,
    "slow_pull_out":  SlowPullOut,
}

CAMERA_EFFECTS = {"slow_push_in", "slow_pull_out"}

# Effects with a spatial mask — figures are auto-subtracted from the mask.
# Flame/lamp effects are intentionally excluded: a lamp or candle behind a
# figure should still flicker. Figure exclusion would zero out the lamp region
# in interior scenes and kill the effect entirely.
_MASK_EFFECTS = {
    "water_ripple", "waterfall_flow",
    "tree_sway", "grass_movement", "grass_sway", "cloud_movement",
}

# Effects that accept an exclude_mask kwarg — figures are auto-excluded.
_EXCLUDE_MASK_EFFECTS = {
    "dust_particles", "falling_leaves", "birds",
    "butterflies", "smoke", "rain", "snow",
}

# Minimum unblocked area fraction for displacement effects.
# Flame/lamp effects are explicitly set to 0.0 — they apply to the exact lamp
# region regardless of how small it is, and figure exclusion does not apply.
_MIN_AREA_THRESHOLDS = {
    "water_ripple":   0.08,
    "waterfall_flow": 0.05,
    "tree_sway":      0.05,
    "grass_movement": 0.05,
    "grass_sway":     0.05,
    "cloud_movement": 0.05,
    "lamp_flicker":   0.0,
    "candle_flicker": 0.0,
    "torch_flicker":  0.0,
}

# ---------------------------------------------------------------------------
# GLOBAL RULES — cinematic restraint
# ---------------------------------------------------------------------------

# Effect → category mapping (used for per-category caps).
_EFFECT_CATEGORY = {
    # object
    "lamp_flicker": "object", "candle_flicker": "object", "torch_flicker": "object",
    "water_ripple": "object", "waterfall_flow": "object",
    "tree_sway": "object", "grass_movement": "object", "grass_sway": "object",
    "cloud_movement": "object",
    # lighting / atmospheric — grouped together as "lighting"
    "sun_rays": "lighting",
    # atmospheric
    "mist_drift": "atmospheric", "fog": "atmospheric", "fog_drift": "atmospheric",
    # particle
    "dust_particles": "particle", "falling_leaves": "particle",
    "birds": "particle", "butterflies": "particle",
    "smoke": "particle", "rain": "particle", "snow": "particle",
    # camera
    "slow_push_in": "camera", "slow_pull_out": "camera",
}

GLOBAL_RULES = {
    "max_object":      2,   # e.g. lamp_flicker + water_ripple, not three displacement effects
    "max_lighting":    1,   # one light source effect (sun_rays)
    "max_atmospheric": 1,   # one haze/mist layer
    "max_particle":    1,   # one particle type (no dust + leaves + birds simultaneously)
    "max_camera":      1,   # always exactly one camera move
}

# Priority within each category — higher wins when the cap forces a trim.
# Scene-specific triggers (lamp, fire, water) score high; generic fallbacks score low.
_EFFECT_PRIORITY = {
    # object — scene-specific triggers
    "lamp_flicker":   95, "candle_flicker": 95, "torch_flicker": 95,
    "water_ripple":   85, "waterfall_flow": 85,
    "tree_sway":      70, "grass_movement": 65, "grass_sway":    65,
    "cloud_movement": 55,
    # lighting
    "sun_rays":       90,
    # atmospheric — scene-specific first, generic fallbacks last
    "mist_drift":     65, "fog":            60, "fog_drift":     60,
    # particle — specific context beats generic dust
    "smoke":          80, "rain":           80, "snow":          80,
    "falling_leaves": 60, "birds":          55, "butterflies":   55,
    "dust_particles": 40,
    # camera — always keep
    "slow_push_in":  100, "slow_pull_out": 100,
}


def _enforce_global_rules(effect_names: list) -> list:
    """
    Cap each effect category per GLOBAL_RULES, keeping the highest-priority
    effects when the limit forces a trim.

    Example: [lamp_flicker, water_ripple, tree_sway, dust_particles, fog_drift]
    with max_object=2 → tree_sway (p=70) dropped, lamp_flicker (p=95) and
    water_ripple (p=85) kept. Output order matches the original input.
    """
    from collections import defaultdict

    # Tag each effect with its index, category, and priority
    indexed = [
        (i, name,
         _EFFECT_CATEGORY.get(name, "unknown"),
         _EFFECT_PRIORITY.get(name, 50))
        for i, name in enumerate(effect_names)
    ]

    # Per-category: sort by priority desc, keep top N, record drops
    by_cat: dict = defaultdict(list)
    for tup in indexed:
        by_cat[tup[2]].append(tup)

    kept_indices: set = set()
    dropped: list = []

    for cat, items in by_cat.items():
        limit = GLOBAL_RULES.get(f"max_{cat}", 999)
        items_by_priority = sorted(items, key=lambda x: x[3], reverse=True)
        for rank, (idx, name, _, priority) in enumerate(items_by_priority):
            if rank < limit:
                kept_indices.add(idx)
            else:
                kept_in_cat = [n for i2, n, _, _ in items_by_priority if i2 in kept_indices]
                dropped.append((name, cat, limit, priority, kept_in_cat))

    for name, cat, limit, priority, kept_in_cat in dropped:
        warnings.warn(
            f"'{name}' dropped by GLOBAL_RULES — '{cat}' at limit ({limit}), "
            f"priority {priority} < kept {kept_in_cat}.",
            stacklevel=3,
        )

    # Return in original input order
    return [name for i, name in enumerate(effect_names) if i in kept_indices]


def _build_figures_mask(figure_boxes, W: int, H: int) -> np.ndarray:
    """Build a boolean exclusion mask from fractional bounding boxes."""
    mask = np.zeros((H, W), dtype=bool)
    for box in figure_boxes:
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        x0, y0, x1, y1 = box
        mask[int(H * y0):int(H * y1), int(W * x0):int(W * x1)] = True
    return mask


def _default_mask(effect_name: str, W: int, H: int) -> np.ndarray:
    """Return the heuristic default mask each effect would use internally."""
    m = np.zeros((H, W), dtype=bool)
    if effect_name == "water_ripple":
        m[int(H * 0.65):, :] = True
    elif effect_name in ("lamp_flicker", "candle_flicker", "torch_flicker"):
        # Lamps appear anywhere in the frame — cover the right-side lower area
        # as a wider fallback. Strict mode (strict_region_effects) means this
        # is only reached for manually-constructed SceneConfigs, not the analyzer.
        m[int(H * 0.25):int(H * 0.80), int(W * 0.40):int(W * 1.0)] = True
    return m




def build_compositor(scene: SceneConfig) -> Compositor:
    """
    Build compositor from scene config applying all engine-level rules:

    Rule 1 — Figure exclusion: figure_boxes are subtracted from every
              mask-based effect. Figures are never displaced or brightened.
    Rule 2 — WaterRipple skip: if <8% of frame remains after exclusion,
              WaterRipple is dropped with a warning (too little visible water).
    Rule 3 — Particle exclusion: DustParticles gets exclude_mask from
              figure_boxes so particles never render on figures.
    Rule 4 — Camera effects always applied last, after all content effects.
    """
    W, H = scene.resolution

    # Global rules first — cap per-category counts before any mask work
    allowed_effects = _enforce_global_rules(scene.effects)

    # dust_particles is a universal atmospheric base layer — always present.
    # Inserted before camera effects so ordering stays correct.
    if "dust_particles" not in allowed_effects:
        cam_idx = next(
            (i for i, e in enumerate(allowed_effects) if e in CAMERA_EFFECTS),
            len(allowed_effects),
        )
        allowed_effects.insert(cam_idx, "dust_particles")

    # Build figures exclusion mask once (None if no boxes defined)
    figures_mask = _build_figures_mask(scene.figure_boxes, W, H) if scene.figure_boxes else None

    content_effects = []
    camera_effects = []

    for effect_name in allowed_effects:
        cls = EFFECT_REGISTRY[effect_name]
        params = dict(scene.effect_params.get(effect_name, {}))  # shallow copy

        # --- Rule 1 & 2: mask-based effect figure exclusion ---
        if figures_mask is not None and effect_name in _MASK_EFFECTS:
            raw_mask = params.get("mask")
            if raw_mask is None:
                raw_mask = _default_mask(effect_name, W, H)
            else:
                raw_mask = raw_mask.copy()

            raw_mask[figures_mask] = False
            params["mask"] = raw_mask

            # Rule 2: skip if too little area remains (not worth applying)
            min_area = _MIN_AREA_THRESHOLDS.get(effect_name, 0.05)
            coverage = raw_mask.sum() / (W * H)
            if coverage < min_area:
                warnings.warn(
                    f"{effect_name} skipped — only {coverage:.1%} of frame is "
                    f"unblocked after figure exclusion (threshold {min_area:.0%}). "
                    f"Consider sun_rays, mist_drift, or dust_particles instead.",
                    stacklevel=2,
                )
                continue

        # --- Rule 3: particle/weather effect figure exclusion ---
        if figures_mask is not None and effect_name in _EXCLUDE_MASK_EFFECTS:
            if params.get("exclude_mask") is None:
                params["exclude_mask"] = figures_mask

        effect = cls(**params)

        if effect_name in CAMERA_EFFECTS:
            camera_effects.append(effect)
        else:
            content_effects.append(effect)

    return Compositor(content_effects + camera_effects)


__all__ = [
    "EFFECT_REGISTRY",
    "CAMERA_EFFECTS",
    "GLOBAL_RULES",
    "build_compositor",
    "Compositor",
    "SceneConfig",
    "LampFlicker",
    "CandleFlicker",
    "TorchFlicker",
    "WaterRipple",
    "DustParticles",
    "MistDrift",
    "SunRays",
    "SlowPushIn",
    "SlowPullOut",
]
