"""
Phase 2 Scene Analyzer.

Uses LLM vision to analyze each scene image and return a structured
EffectPlan that build_compositor can execute directly.

Usage:
    analyzer = SceneAnalyzer()
    plan = analyzer.analyze("images/scene-012.png")
    scene = plan.to_scene_config("output/scene-012.mp4", duration=14.0)
    compositor = build_compositor(scene)
"""

import json
import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

# Flat set used for validation (every name the LLM may return)
AVAILABLE_EFFECTS = [
    # OBJECT_EFFECTS — require a spatial mask; figures auto-excluded
    "lamp_flicker", "candle_flicker", "torch_flicker",
    "water_ripple", "waterfall_flow",
    "tree_sway", "grass_sway",
    # LIGHTING_EFFECTS
    "sun_rays",
    # ATMOSPHERIC_EFFECTS — full-frame, no mask
    "fog_drift", "mist_drift", "light_haze", "warm_bloom",
    # PARTICLE_EFFECTS — figures auto-excluded
    "dust_particles", "smoke",
    # CAMERA_EFFECTS — always last
    "slow_push_in", "slow_pull_out",
]

ANALYSIS_PROMPT = """Analyze this scene image for cinematic motion effects.

Return a JSON object with exactly this structure:

{
  "scene_type": "interior|exterior",
  "time_of_day": "day|golden_hour|dusk|night",
  "mood": "one sentence",
  "figure_boxes": [
    [x0, y0, x1, y1]
  ],
  "regions": {
    "sky": [x0, y0, x1, y1] or null,
    "water": [x0, y0, x1, y1] or null,
    "vegetation": [x0, y0, x1, y1] or null,
    "fire_or_lamp": [x0, y0, x1, y1] or null,
    "waterfall": [x0, y0, x1, y1] or null,
    "grass": [x0, y0, x1, y1] or null
  },
  "effects": [
    {
      "name": "<effect_name>",
      "reason": "<why this effect fits>",
      "params": {}
    }
  ]
}

AVAILABLE EFFECTS (use only names from this list):

  OBJECT_EFFECTS  — only if that object is clearly visible in the scene:
    lamp_flicker   → kerosene or oil lamp
    candle_flicker → candle flame
    torch_flicker  → open flame: torch, diya, bonfire
    water_ripple   → still water surface (pond, lake, river)
    waterfall_flow → flowing water or waterfall
    tree_sway      → trees or large plants
    grass_sway     → grass, reeds, low ground cover

  LIGHTING_EFFECTS — one maximum:
    sun_rays       → visible light shafts, golden hour, temple interior light

  ATMOSPHERIC_EFFECTS — one maximum, choose the best fit:
    fog_drift      → heavy mist, forest ground fog, stormy atmosphere
    mist_drift     → light atmospheric haze, cool morning
    light_haze     → warm sunny haze, temple interior glow
    warm_bloom     → golden hour warmth, candlelit room subtle glow

  PARTICLE_EFFECTS — one maximum, only if it fits naturally:
    dust_particles → floating dust in light beams (AVOID in rain/snow scenes)
    smoke          → only if fireplace / incense / chimney / torch is present

  CAMERA_EFFECTS — always exactly one, always last:
    slow_push_in   → storytelling, emotional moments, teachings, introductions
    slow_pull_out  → endings, moments of realization, closing shots

GLOBAL RULES (the engine enforces these, but respect them in your selection):
  - Max 2 OBJECT_EFFECTS, max 1 LIGHTING, max 1 ATMOSPHERIC, max 1 PARTICLE, max 1 CAMERA
  - Total effects: 2 to 4 (camera counts as 1)
  - Prefer subtle motion — real cinematography is restrained, not everything moves at once
  - Never add an effect unless the trigger object is clearly visible
  - Never force water_ripple if water is mostly blocked by figures (< 8% of frame)

SCENE RECIPES:
  Interior night / lamp scene  → lamp_flicker + warm_bloom + slow_push_in
  Interior day / temple        → sun_rays + light_haze + slow_push_in
  Exterior golden hour         → sun_rays + warm_bloom + dust_particles + slow_push_in
  Exterior forest / nature     → tree_sway + mist_drift + slow_push_in
  Exterior rainy / stormy      → fog_drift + slow_push_in (no dust in rain)
  Lake / river scene           → water_ripple + mist_drift + slow_push_in
  Ending / closing shot        → warm_bloom + slow_pull_out

figure_boxes: ALL human figures as [x0,y0,x1,y1] fractions (0.0–1.0). Add 3–5% padding.
regions: same fractional format. null if not present.

Return ONLY the JSON object, no markdown fences, no explanation."""


@dataclass
class EffectSpec:
    name: str
    reason: str
    params: dict = field(default_factory=dict)


@dataclass
class EffectPlan:
    scene_type: str
    time_of_day: str
    mood: str
    figure_boxes: List[Tuple[float, float, float, float]]
    regions: dict
    effects: List[EffectSpec]
    image_path: str

    def to_scene_config(self, output_path: str, duration: float = 14.0,
                        fps: int = 30, resolution: tuple = None):
        """Convert plan to SceneConfig ready for build_compositor."""
        from motion_engine.scene import SceneConfig

        if resolution is None:
            import cv2
            img = cv2.imread(self.image_path)
            h, w = img.shape[:2]
            # H.264 needs even dimensions
            resolution = (w if w % 2 == 0 else w - 1, h if h % 2 == 0 else h - 1)

        effect_names = [e.name for e in self.effects]
        effect_params = {e.name: e.params for e in self.effects if e.params}

        return SceneConfig(
            image_path=self.image_path,
            output_path=output_path,
            duration_seconds=duration,
            fps=fps,
            resolution=resolution,
            effects=effect_names,
            effect_params=effect_params,
            figure_boxes=self.figure_boxes,
        )


class SceneAnalyzer:
    """
    Analyzes a scene image with LLM vision and returns an EffectPlan.
    Falls back gracefully to dust_particles + slow_push_in if LLM is unavailable.
    """

    def __init__(self, llm_provider=None):
        self._llm = llm_provider  # injected; loaded lazily if None

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        try:
            import anthropic
            return anthropic.Anthropic()
        except Exception as e:
            logger.warning(f"Could not init LLM client: {e}")
            return None

    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    def analyze(self, image_path: str) -> EffectPlan:
        """Analyze image and return EffectPlan. Falls back to safe defaults."""
        logger.info(f"Analyzing scene: {image_path}")

        client = self._get_llm()
        if client is None:
            return self._fallback_plan(image_path)

        try:
            b64 = self._encode_image(image_path)
            response = client.messages.create(
                model="claude-opus-5",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": ANALYSIS_PROMPT},
                    ],
                }],
            )
            raw = response.content[0].text.strip()
            return self._parse(raw, image_path)

        except Exception as e:
            logger.warning(f"LLM analysis failed for {image_path}: {e}. Using fallback.")
            return self._fallback_plan(image_path)

    def _parse(self, raw: str, image_path: str) -> EffectPlan:
        data = json.loads(raw)

        figure_boxes = [tuple(b) for b in data.get("figure_boxes", [])]
        effects = [
            EffectSpec(
                name=e["name"],
                reason=e.get("reason", ""),
                params=e.get("params", {}),
            )
            for e in data.get("effects", [])
            if e["name"] in AVAILABLE_EFFECTS
        ]

        # Ensure at least dust_particles and a camera effect exist
        effect_names = [e.name for e in effects]
        if not any(n in effect_names for n in ("slow_push_in", "slow_pull_out")):
            effects.append(EffectSpec("slow_push_in", "default camera motion"))
        if not effects or all(e.name in ("slow_push_in", "slow_pull_out") for e in effects):
            effects.insert(0, EffectSpec("dust_particles", "fallback atmospheric"))

        return EffectPlan(
            scene_type=data.get("scene_type", "exterior"),
            time_of_day=data.get("time_of_day", "day"),
            mood=data.get("mood", ""),
            figure_boxes=figure_boxes,
            regions=data.get("regions", {}),
            effects=effects,
            image_path=image_path,
        )

    def _fallback_plan(self, image_path: str) -> EffectPlan:
        """Safe default when LLM is unavailable."""
        return EffectPlan(
            scene_type="exterior",
            time_of_day="day",
            mood="cinematic",
            figure_boxes=[],
            regions={},
            effects=[
                EffectSpec("dust_particles", "fallback — always works",
                           {"count": 80, "alpha": 0.30}),
                EffectSpec("mist_drift", "subtle atmospheric depth"),
                EffectSpec("slow_push_in", "cinematic camera"),
            ],
            image_path=image_path,
        )
