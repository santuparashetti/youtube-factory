"""Export scene image prompts as human-readable markdown for manual image generation."""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

from ytfactory.shared.constants import WORKSPACE_DIR


_CHATGPT_SETUP = dedent("""\
    I am generating a multi-scene philosophical documentary storyboard in a MANDATORY hybrid
    visual style. You MUST follow this style for every single image without exception.

    ⚠️ CRITICAL RULE — TWO-LAYER STYLE (never ignore this):
    LAYER 1 — ENVIRONMENT: 100% photorealistic. Architecture, nature, interiors, soil,
    trees, props, lighting, and shadows must look like real cinema photography.
    LAYER 2 — CHARACTERS: 100% illustrated cartoon. Every human, eagle, bird, or animal
    MUST be rendered as a hand-painted storybook illustration — visible ink outlines, flat
    cel shading, painterly texture, graphic novel quality. Characters must NEVER look like
    real photos. They should look like 2D cartoon characters placed inside a real photograph.

    DO NOT make characters photorealistic. DO NOT make the environment cartoon.
    Think of it as: real-world photo background + animated cartoon characters composited on top.

    CHARACTER PRESENCE RULE — SCENE-DRIVEN ONLY:
    There is NO global anchor character. Never automatically insert a viewer-proxy
    or any other character into a scene because of the scene number, scene type, or a
    previous scene.

    Only characters explicitly named in that scene's CHARACTER PRESENCE may appear.
    Character continuity means preserving the appearance of a character when that character
    is present — it does NOT mean adding the character to scenes where they are absent.
    Characters from a previous scene must never leak into the next scene.

    For environment-only scenes (CHARACTER PRESENCE: NONE), generate NO human figures,
    silhouettes, body parts, or implied human presence.\
""")

_GLOBAL_INSTRUCTIONS = dedent("""\
    Append these to every prompt when pasting into a generator:
    - **Aspect ratio:** 16:9
    - **Character style:** All characters (humans, animals, birds) MUST be illustrated cartoon style with ink outlines and cel shading — NOT photorealistic
    - **Environment style:** Background and environment only are 100% photorealistic cinema photography
    - **Negative:** No text, no watermark, no subtitle, no logo, no photorealistic characters, no realistic humans, no realistic animals, no real-photo people

    These lines are stripped from individual prompts below to reduce repetition.\
""")

_TOOLS_TABLE = dedent("""\
    | Tool | Best for | Link |
    |------|----------|------|
    | **Leonardo AI** | Photorealistic, free daily credits | https://leonardo.ai |
    | **Adobe Firefly** | Safe, commercial-use images | https://firefly.adobe.com |
    | **Ideogram** | Text-accurate, stylized | https://ideogram.ai |
    | **Midjourney** | Highest quality (paid) | https://midjourney.com |
    | **DALL-E 3** | Via ChatGPT, great quality | https://chatgpt.com |\
""")


def _character_presence_label(scene: dict) -> str:
    """Return the CHARACTER PRESENCE string for a scene.

    Priority:
    1. character_presence field (list[str]) — authoritative, set by new pipeline
    2. scene_analysis.characters — fallback for old scene plans (when non-empty)
    3. NONE — do NOT fall back to anchor_role; that was auto-injected Kai logic
    """
    presence = scene.get("character_presence") or []
    if presence:
        return ", ".join(str(c).upper() for c in presence)

    analysis = scene.get("scene_analysis") or {}
    characters = analysis.get("characters") or []
    if characters:
        return ", ".join(str(c).upper().replace(" ", "_") for c in characters)

    return "NONE"


def _visual_metadata_line(scene: dict) -> str:
    """Format visual_metadata as a compact key=value line."""
    vm = scene.get("visual_metadata") or {}
    if not vm:
        return ""
    parts = []
    if vm.get("era"):
        parts.append(f"era={vm['era']}")
    if vm.get("narrative_role"):
        parts.append(f"role={vm['narrative_role']}")
    if vm.get("environment"):
        parts.append(f"env={vm['environment']}")
    if vm.get("mood"):
        parts.append(f"mood={vm['mood']}")
    if vm.get("visual_style"):
        parts.append(f"style={vm['visual_style']}")
    if "allow_modern_objects" in vm:
        parts.append(f"modern={vm['allow_modern_objects']}")
    return " ".join(parts)


def _scene_block(scene: dict, project_id: str, images_dir: Path) -> str:
    """Render a single scene as a markdown section."""
    idx = scene.get("index", 0)
    filename = f"scene-{idx:03d}.png"
    save_path = images_dir / filename
    narration = scene.get("narration", "").strip()

    # Use compiled_prompt when available (structured prompt), else visual_prompt
    structured = scene.get("structured_prompt") or {}
    prompt = structured.get("compiled_prompt") or scene.get("visual_prompt", "")

    presence = _character_presence_label(scene)
    meta_line = _visual_metadata_line(scene)

    lines: list[str] = [
        f"## Scene {idx} — `{filename}`",
        "",
        f"**Save to:** `{save_path}`",
        "",
        f"**Narration:** _{narration}_",
        "",
        "**Image Prompt:**",
        "",
        f"**CHARACTER PRESENCE:** {presence}",
        "",
        prompt.strip(),
        "",
    ]
    if meta_line:
        lines += [f"**Visual Metadata:** {meta_line}", ""]
    lines += ["---", ""]
    return "\n".join(lines)


def export_image_prompts(
    project_id: str,
    output_dir: Path | None = None,
    chunk_size: int = 9,
) -> list[Path]:
    """Export image prompts as chunked markdown files.

    Args:
        project_id: Project slug.
        output_dir: Where to write files. Defaults to workspace images dir.
        chunk_size: Scenes per file. Default 9.

    Returns:
        List of paths written.
    """
    project_dir = Path(WORKSPACE_DIR) / project_id
    scene_plan_path = project_dir / "scenes" / "scene-plan.json"
    if not scene_plan_path.exists():
        raise FileNotFoundError(f"No scene plan found: {scene_plan_path}")

    scene_plan = json.loads(scene_plan_path.read_text(encoding="utf-8"))
    scenes = scene_plan.get("scenes", [])
    # Exclude non-image scenes like brand_card
    scenes = [s for s in scenes if s.get("scene_type", "generated_image") != "brand_card"]

    total = len(scenes)
    title = scene_plan.get("title", project_id)
    images_dir = project_dir / "images"

    dest = output_dir or (project_dir / "publish")
    dest.mkdir(parents=True, exist_ok=True)

    # Build ChatGPT preamble block (shown in Step 0 for generators)
    preamble_block = _CHATGPT_SETUP

    written: list[Path] = []
    chunks = [scenes[i : i + chunk_size] for i in range(0, total, chunk_size)]

    for chunk_idx, chunk in enumerate(chunks):
        first = chunk[0].get("index", chunk_idx * chunk_size + 1)
        last = chunk[-1].get("index", first + len(chunk) - 1)
        out_name = f"{project_id}_prompts_{first:02d}-{last:02d}.md"
        out_path = dest / out_name

        header = f"# Image Prompts — {project_id}\n**Style:** documentary | **Scenes:** {first}–{last} of {total} | **Size:** 1280×720 px (16:9)\n"

        step0 = (
            "## Step 0 — Before You Start (Image Generator Setup)\n\n"
            "**ChatGPT / DALL-E 3:** Paste this message ONCE at the start of a new conversation,\n"
            "before pasting any scene prompt:\n\n"
            f"```\n{preamble_block}\n```\n\n"
            f"Keep all {total} generations in ONE conversation window. If style drifts, paste\n"
            "scene 1 back and say \"same hybrid style — continue with scene [X]\".\n\n"
            "**Midjourney / Leonardo:** Generate scene 1 first. Use that as your style\n"
            "reference (--sref) for all subsequent scenes. For character-primary scenes, "
            "use the same character reference when your generator supports it."
        )

        global_instr = f"## Global Instructions (apply to ALL prompts below)\n\n{_GLOBAL_INSTRUCTIONS}"

        how_to_use = (
            "## How to Use\n\n"
            "1. Copy each prompt below into your preferred image generator.\n"
            "2. Generate at **1280×720** resolution (16:9). Any 16:9 size works — it gets resized.\n"
            "3. Download and **rename** each image to the exact filename shown (e.g. `scene-001.png`).\n"
            f"4. Place all images in this folder:  \n"
            f"   `{images_dir}`\n"
            "5. Re-run the pipeline — placed images are detected automatically and image generation is skipped."
        )

        tools = f"## Recommended Free Tools\n\n{_TOOLS_TABLE}"

        rerun = (
            "## Re-run Command (after placing images)\n\n"
            "```bash\n"
            f"# Delete old auto-generated scene videos so they re-render with your new images\n"
            f"rm {project_dir}/video/scene-*.mp4\n\n"
            f"# Re-run — existing images and audio are skipped, only video is rebuilt\n"
            f"ytfactory render {project_id}\n"
            "```"
        )

        scene_sections = "\n".join(_scene_block(s, project_id, images_dir) for s in chunk)

        content = "\n\n".join([header, step0, global_instr, how_to_use, tools, rerun, scene_sections])
        out_path.write_text(content + "\n", encoding="utf-8")
        written.append(out_path)

    return written
