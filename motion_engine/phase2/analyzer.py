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
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


def is_qwen3_model(model: str) -> bool:
    return model.lower().startswith("qwen/qwen3")


def _region_mask(region_box: list, W: int, H: int) -> "np.ndarray":
    """Convert a fractional [x0,y0,x1,y1] region box into a boolean numpy mask."""
    import numpy as np
    x0, y0, x1, y1 = region_box
    m = np.zeros((H, W), dtype=bool)
    m[int(H * y0):int(H * y1), int(W * x0):int(W * x1)] = True
    return m


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
    "leaves": [x0, y0, x1, y1] or null,
    "grass": [x0, y0, x1, y1] or null,
    "water": [x0, y0, x1, y1] or null,
    "waterfall": [x0, y0, x1, y1] or null,
    "lamp": [x0, y0, x1, y1] or null,
    "candle": [x0, y0, x1, y1] or null,
    "torch": [x0, y0, x1, y1] or null
  },
  "effects": [
    {
      "name": "<effect_name>",
      "reason": "<why this effect fits>",
      "params": {}
    }
  ]
}

FIGURE DETECTION — CRITICAL:
  Scan the entire image for ANY human presence: people, faces, bodies, silhouettes,
  partial figures (just a hand, a shoulder, a seated person). Include every human
  bounding box in figure_boxes with 3–5% padding. An empty figure_boxes list means
  the scene has ZERO human presence — if in doubt, add the box.

REGION DETECTION — precision is critical for every region.
Mark only the EXACT pixels of each element — tight fit, no padding into surrounding context.
Only mark non-null when the element is unambiguously visible and covers >5% of the frame.

  leaves:    Tight box around visible LEAF CLUSTERS only — the outer foliage at branch
             tips where wind would move them. EXCLUDE trunk, branches, bark, walls,
             ground, and all animals. Canopy is typically in the top 0–35% of the image.
             Set null if no clearly visible leaf clusters exist.

  grass:     Tight box covering ONLY grass blades or reeds. EXCLUDE dirt, rocks, paths,
             and any objects sitting on the grass (feet, wheels, pots).
             Set null if no clearly visible grass exists.

  water:     Tight box around the visible WATER SURFACE only — still pond, lake, or
             river. EXCLUDE reflections that extend above the waterline, banks, rocks,
             and any figures. Set null if water is absent or less than 8% of frame.

  waterfall: Tight box around the falling WATER COLUMN only. EXCLUDE the pool below,
             surrounding rocks, mist, and vegetation.
             Set null if no clearly visible waterfall exists.

  lamp:      Tight box around the lamp body and its visible flame/glow. Even a very
             small lamp (1–2% of frame) should be marked — flame size does not matter.
             EXCLUDE the wall behind it, the table beneath.
             Set null ONLY if there is definitely no kerosene, oil lamp, or diya.

  candle:    Tight box around the candle body and flame only. Mark even small candles.
             EXCLUDE wax drips, holder, and surrounding glow on walls.
             Set null ONLY if there is definitely no candle flame visible.

  torch:     Tight box around the torch head and active flame only. Includes diyas,
             oil lamps with open flames, bonfires, and any open-flame light source.
             Mark even if very small (1–2% of frame). EXCLUDE handle, smoke, surrounding light.
             Set null ONLY if there is definitely no open flame visible.

AVAILABLE EFFECTS (use only names from this list):

  OBJECT_EFFECTS  — only if that object is clearly visible AND its region is non-null.
  The engine enforces this strictly: if you add an effect but its region is null,
  the engine drops the effect entirely. There is no fallback.

    lamp_flicker   → ONLY if lamp region non-null. If you choose this effect, you MUST
                     annotate regions.lamp with the lamp body + flame bounding box. Even
                     a lamp partially behind a figure should be annotated — the engine
                     applies the flicker to the lamp region without figure exclusion.
    candle_flicker → ONLY if candle region non-null. If you choose this effect, you MUST
                     annotate regions.candle. Do not choose candle_flicker and leave
                     regions.candle null — the effect will be dropped.
    torch_flicker  → ONLY if torch region non-null. If you choose this effect, you MUST
                     annotate regions.torch. Includes diyas, oil lamps, bonfires.
    water_ripple   → ONLY if water region non-null (still water surface)
    waterfall_flow → ONLY if waterfall region non-null (flowing water or waterfall)
    tree_sway      → ONLY if leaves region non-null (leaf clusters clearly visible)
    grass_sway     → ONLY if grass region non-null (grass clearly present)

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
  - Never add tree_sway or grass_sway if figures dominate the frame — use dust_particles instead

SCENE RECIPES:
  Interior night / lamp scene  → lamp_flicker + warm_bloom + slow_push_in
  Interior day / temple        → sun_rays + light_haze + slow_push_in
  Exterior golden hour         → sun_rays + warm_bloom + dust_particles + slow_push_in
  Exterior forest / nature     → tree_sway + mist_drift + slow_push_in  (only if leaves region non-null)
  Exterior rainy / stormy      → fog_drift + slow_push_in (no dust in rain)
  Lake / river scene           → water_ripple + mist_drift + slow_push_in
  Ending / closing shot        → warm_bloom + slow_pull_out
  Scene with human figure(s)   → warm_bloom + dust_particles + slow_push_in (no displacement on figures)

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

        W, H = resolution
        effect_names = [e.name for e in self.effects]
        effect_params: dict = {}
        for e in self.effects:
            if not e.params:
                continue
            p = dict(e.params)
            region_box = p.pop("_region_box", None)
            if region_box is not None:
                p["mask"] = _region_mask(region_box, W, H)
            if p:
                effect_params[e.name] = p

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

    def __init__(self, llm_provider=None, model: str = "openai/gpt-5.6-luna-pro"):
        self._llm = llm_provider
        self._model = model

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        try:
            return OpenAI(
                base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://openrouter.ai/api/v1"),
                api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            )
        except Exception as e:
            logger.warning(f"Could not init LLM client: {e}")
            return None

    # Analysis only needs enough resolution to identify regions — not full HD.
    ANALYZE_MAX_WIDTH = 640
    ANALYZE_MAX_HEIGHT = 360

    def _encode_image(self, image_path: str) -> str:
        import cv2
        img = cv2.imread(image_path)
        if img is not None:
            h, w = img.shape[:2]
            if w > self.ANALYZE_MAX_WIDTH or h > self.ANALYZE_MAX_HEIGHT:
                scale = min(self.ANALYZE_MAX_WIDTH / w, self.ANALYZE_MAX_HEIGHT / h)
                img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                return base64.standard_b64encode(buf.tobytes()).decode("utf-8")
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

            if is_qwen3_model(self._model):
                provider = {
                    "order": ["alibaba"],
                    "allow_fallbacks": False,
                }
            else:
                provider = {
                    "order": ["OpenAI"],
                    "allow_fallbacks": False,
                }

            response = client.chat.completions.create(
                model=self._model,
                max_tokens=1024,
                extra_body={"provider": provider},
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                            },
                        },
                        {"type": "text", "text": ANALYSIS_PROMPT},
                    ],
                }],
            )
            raw = response.choices[0].message.content.strip()
            return self._parse(raw, image_path)

        except Exception as e:
            logger.warning(f"LLM analysis failed for {image_path}: {e}. Using fallback.")
            return self._fallback_plan(image_path)

    # Effects where the region MUST be detected — no region means the effect
    # would apply to the wrong area (e.g. water ripple on a figure).
    _HARD_REGION_GUARDS: dict = {
        "tree_sway":      "leaves",
        "grass_sway":     "grass",
        "grass_movement": "grass",
        "water_ripple":   "water",
        "waterfall_flow": "waterfall",
    }

    # Effects that work with their built-in default mask when the region is null.
    # The LLM selecting the effect means it saw the light source — let it through.
    _SOFT_REGION_GUARDS: dict = {
        "lamp_flicker":   "lamp",
        "candle_flicker": "candle",
        "torch_flicker":  "torch",
    }

    def _parse(self, raw: str, image_path: str) -> EffectPlan:
        data = json.loads(raw)

        raw_figure_boxes = data.get("figure_boxes", []) or []
        figure_boxes = []
        for b in raw_figure_boxes:
            # Unwrap extra nesting: [[x0,y0,x1,y1]] → [x0,y0,x1,y1]
            while isinstance(b, (list, tuple)) and len(b) == 1 and isinstance(b[0], (list, tuple)):
                b = b[0]
            if isinstance(b, (list, tuple)) and len(b) == 4:
                figure_boxes.append(tuple(float(v) for v in b))
            else:
                logger.debug("Skipping malformed figure_box: %s", b)
        regions: dict = data.get("regions", {}) or {}
        for key, region_box in list(regions.items()):
            if not isinstance(region_box, (list, tuple)):
                continue
            b = region_box
            while isinstance(b, (list, tuple)) and len(b) == 1 and isinstance(b[0], (list, tuple)):
                b = b[0]
            if isinstance(b, (list, tuple)) and len(b) == 4:
                regions[key] = list(b)
            else:
                logger.debug("Dropping malformed region '%s': %s", key, region_box)
                regions[key] = None

        raw_effects = [
            EffectSpec(
                name=e["name"],
                reason=e.get("reason", ""),
                params={},
            )
            for e in data.get("effects", [])
            if e["name"] in AVAILABLE_EFFECTS
        ]

        effects: list[EffectSpec] = []
        added_dust = False
        for spec in raw_effects:
            hard_region_key = self._HARD_REGION_GUARDS.get(spec.name)
            soft_region_key = self._SOFT_REGION_GUARDS.get(spec.name)

            if hard_region_key is not None:
                region_box = regions.get(hard_region_key)
                if not region_box:
                    # Hard guard: region absent → drop effect, substitute dust_particles
                    logger.debug(
                        "%s dropped: region '%s' not detected in scene",
                        spec.name, hard_region_key,
                    )
                    if not added_dust:
                        effects.append(EffectSpec("dust_particles", "substituted for missing region effect"))
                        added_dust = True
                    continue
                spec.params["_region_box"] = list(region_box)
                if spec.name == "tree_sway":
                    spec.params["intensity"] = 5.0
                    spec.params["speed"] = 0.35
                    spec.params["wavelength"] = 160.0

            elif soft_region_key is not None:
                region_box = regions.get(soft_region_key)
                if not region_box:
                    # Strict: LLM chose this effect but didn't annotate the region.
                    # The prompt requires a non-null region when choosing flame effects.
                    # Drop rather than falling back to a default mask that will likely
                    # be wrong (lamps are rarely at center-frame).
                    logger.debug(
                        "%s dropped: region '%s' not annotated — "
                        "LLM must provide region coordinates when choosing this effect",
                        spec.name, soft_region_key,
                    )
                    if not added_dust:
                        effects.append(EffectSpec("dust_particles", "substituted for missing region effect"))
                        added_dust = True
                    continue
                # Region detected — use the precise box
                spec.params["_region_box"] = list(region_box)

            effects.append(spec)

        # Ensure at least a camera effect exists
        effect_names = [e.name for e in effects]
        if not any(n in effect_names for n in ("slow_push_in", "slow_pull_out")):
            effects.append(EffectSpec("slow_push_in", "default camera motion"))

        # Ensure at least one non-camera content effect
        if not effects or all(e.name in ("slow_push_in", "slow_pull_out") for e in effects):
            effects.insert(0, EffectSpec("dust_particles", "fallback atmospheric"))

        return EffectPlan(
            scene_type=data.get("scene_type", "exterior"),
            time_of_day=data.get("time_of_day", "day"),
            mood=data.get("mood", ""),
            figure_boxes=figure_boxes,
            regions=regions,
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
                EffectSpec("dust_particles", "fallback — always works"),
                EffectSpec("mist_drift", "subtle atmospheric depth"),
                EffectSpec("slow_push_in", "cinematic camera"),
            ],
            image_path=image_path,
        )
