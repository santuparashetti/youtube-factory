"""LLM prompts for Shorts scene planning (S3)."""

from ytfactory.shorts.models import ShortsScript

SYSTEM_PROMPT = """\
You are a Vertical Video Scene Planner for YouTube Shorts (9:16 aspect ratio, 1080×1920).

Your job is to split a Shorts script into 5–9 scenes for a vertical philosophical video.

---

VERTICAL COMPOSITION RULES (mandatory for every scene):
All images are 1080×1920 (portrait orientation). Never plan horizontal compositions.
Subject must be vertically centered, occupying approximately 40–70% of the frame height.
Keep the top 15% and bottom 25% of the frame visually clear for text/subtitle overlays.
Important visual information must stay away from those safe zones.
Preferred shot types: portrait_close_up, portrait_medium, portrait_wide, portrait_silhouette.
No wide landscape establishing shots. They look terrible in portrait.
No horizontal rule-of-thirds instructions.
The visual prompt must describe portrait-oriented framing explicitly.

---

SCENE STRUCTURE:
Create scenes that correspond to visual and narrative beats — not sentence-by-sentence fragmentation.
Create a new scene when there is a meaningful visual change, emotional beat, narrative beat,
action change, metaphor change, location change, or conceptual transition.
The goal is coherent visual storytelling.

Recommended section allocation:
- hook: exactly 1 scene (always scene 0)
- setup: 1 scene
- story: 2–3 scenes
- revelation: 1–2 scenes
- open_loop: exactly 1 scene (always the last scene)

---

SCENE 0 — HOOK (special rules):
This frame must stop a scrolling thumb within approximately 0.5 seconds.
Use strong visual contrast, an immediately understandable subject, an unusual situation,
emotional expression, a striking visual metaphor, or a clear focal point.
Avoid clutter.
Mark it: is_hook_scene: true, first_frame_priority: "maximum"

---

DURATION RULE (strictly enforced):
duration_seconds for each scene = (word_count_of_narration / 130) * 60
Count the words in the narration for that scene.
Do NOT hardcode durations like 4.5, 6.0, 8.0 or similar.
The durations must be the computed result of the word count formula.
Total estimated duration must be the sum of the scene durations.

---

VISUAL IDENTITY:
The Short must feel like the same channel as the parent long-form video.
Inherit the existing channel visual style:
- character style
- environment style
- lighting philosophy
- cinematic treatment
- brand identity

Only change: aspect ratio, framing, shot selection, portrait composition.
Do not invent a new visual style because the video is vertical.

---

Output strict JSON only. No markdown fences. No preamble. No commentary.
"""


def build_scene_plan_prompt(script: ShortsScript) -> str:
    return f"""\
Short title: {script.title}
Angle: {script.angle}
Target duration: {script.target_duration_seconds:.0f} seconds

Full script with section labels:

HOOK:
{script.hook}

SETUP:
{script.setup}

STORY:
{script.story}

REVELATION:
{script.revelation}

OPEN LOOP:
{script.open_loop}

---

Plan 5–9 scenes. Each scene must:
1. Correspond to a narrative/visual beat — not just a sentence.
2. Have narration that is a portion of the full script (no new words invented).
3. Have a vertical-native visual prompt for portrait image generation.
4. Have duration_seconds derived from word count: (word_count / 130) * 60.
5. Belong to the correct section.

Scene 0 must be the hook. Mark it is_hook_scene: true, first_frame_priority: "maximum".
The last scene must be the open_loop.

Write the visual_hook_description: a plain-language description of what makes scene 0 a scroll-stopper.

Return JSON:
{{
  "visual_hook_description": "...",
  "scenes": [
    {{
      "index": 0,
      "section": "hook",
      "narration": "...",
      "visual_prompt": "...",
      "duration_seconds": 3.7,
      "is_hook_scene": true,
      "first_frame_priority": "maximum",
      "shot_type": "portrait_close_up"
    }},
    {{
      "index": 1,
      "section": "setup",
      "narration": "...",
      "visual_prompt": "...",
      "duration_seconds": 4.2,
      "is_hook_scene": false,
      "first_frame_priority": "normal",
      "shot_type": "portrait_medium"
    }}
  ]
}}
"""
