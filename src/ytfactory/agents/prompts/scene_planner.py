"""Scene planner agent prompts."""

PLAN_SCENES = """\
You are an expert YouTube documentary editor.

Convert the narration script below into a sequence of cinematic scenes for \
a YouTube video about: {topic}

──────────────────────────────────────────────────────────────
RULES
──────────────────────────────────────────────────────────────
- Each scene covers 1 continuous narration segment (5-12 seconds of speech).
- Split at natural pause points: end of sentences, topic changes.
- Every scene MUST have all 5 fields.
- Narration: copy the exact words from the script for that segment.
- Visual prompt: a detailed, cinematic image generation prompt (no text/words in image).
- Duration: realistic estimate in seconds based on word count (~130 wpm).
- Total scenes: aim for 8-15 scenes for a 3-5 minute video.

──────────────────────────────────────────────────────────────
OUTPUT FORMAT — ONLY valid JSON, no markdown, no code fences
──────────────────────────────────────────────────────────────
{{
  "topic": "{topic}",
  "total_duration_seconds": <sum of all scene durations>,
  "scenes": [
    {{
      "index": 1,
      "title": "Scene title",
      "narration": "Exact words spoken in this scene.",
      "visual_prompt": "Detailed cinematic image generation prompt.",
      "duration_seconds": 8
    }}
  ]
}}

Script:
{script}\
"""

ENHANCE_VISUAL_PROMPTS = """\
You are a cinematography expert and AI image generation specialist working on \
a YouTube documentary about: {topic}

Enhance the visual_prompt for each scene to produce consistent, \
professional-quality cinematic images.

For every scene's visual_prompt, make it:
1. Cinematically specific: describe composition (wide shot, close-up, aerial, etc.)
2. Lighting-aware: specify lighting (golden hour, dramatic chiaroscuro, soft diffuse, etc.)
3. Color-consistent: maintain a cohesive color palette across ALL scenes
4. Style-anchored: all scenes should feel like the same documentary (e.g., "cinematic, \
photorealistic, documentary style, 8K detail")
5. Safe: no people with unnatural features, no text/logos/watermarks, no close-up hands

NEVER add: text overlays, watermarks, logos, letters, numbers visible in the image.

Return ONLY the same JSON structure with visual_prompt fields updated.
Keep all other fields (index, title, narration, duration_seconds) EXACTLY unchanged.

{scene_json}\
"""

FIX_JSON_PROMPT = """\
The JSON below is malformed or incomplete. Fix it so it is valid JSON matching \
this exact schema:
{{
  "topic": string,
  "total_duration_seconds": number,
  "scenes": [
    {{
      "index": integer,
      "title": string,
      "narration": string,
      "visual_prompt": string,
      "duration_seconds": number
    }}
  ]
}}

Malformed JSON:
{broken_json}

Return ONLY the corrected valid JSON. No explanation. No code fences.\
"""
