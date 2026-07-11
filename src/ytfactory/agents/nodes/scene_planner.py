"""Scene planner node — Python splits narrations, LLM adds visual prompts only."""

from __future__ import annotations

import json
import re
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ytfactory.agents.prompts.branding import CLOSING_VARIATIONS, SOFT_CTA
from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt
from ytfactory.agents.state import VideoState
from ytfactory.branding.config import get_brand_config
from ytfactory.config.settings import Settings
from ytfactory.images.prompt_engine import ImagePromptEngineV4
from video_core.providers.llm.factory import get_llm_provider
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.storage.artifact_repository import ArtifactRepository
from ytfactory.storage.project_repository import ProjectRepository

# Closing phrases that should trigger an asset scene instead of AI image generation.
# Derived from branding module so detection tracks new variants from brand config.
_CLOSING_TRIGGERS: frozenset[str] = frozenset(
    phrase.lower().strip().rstrip(".") for phrase in CLOSING_VARIATIONS + [SOFT_CTA]
)

console = Console()

_TARGET_WORDS_PER_SCENE = 28  # ~14s at 120 wpm spiritual pace


def _split_script_to_scenes(
    script: str, target_words: int = _TARGET_WORDS_PER_SCENE
) -> list[dict]:
    """
    Split a script into scenes using Python only — no LLM, no truncation risk.

    Strategy:
    1. Clean markdown from the text
    2. Split each paragraph into individual sentences
    3. Group consecutive sentences until the bucket reaches ~target_words
    4. Prefer splitting AT paragraph breaks when the bucket is half-full

    Produces ~25-35 scenes from a 700-word script (12-20s each at -20% TTS rate).
    Every word from the script is preserved verbatim.
    """
    # ── 1. Clean residual markdown ─────────────────────────────────────────
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", script, flags=re.DOTALL)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"`(.+?)`", r"\1", text)

    # ── 2. Break into sentences across all paragraphs ─────────────────────
    # Split by paragraph first to respect major section breaks
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    # Regex that splits AFTER sentence-ending punctuation followed by a capital
    _SENT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-Z\"‘’])")

    all_sentences: list[tuple[str, bool]] = []  # (sentence, is_paragraph_end)
    for para in paragraphs:
        # Also split on single newlines within the paragraph
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        para_text = " ".join(lines)
        sents = _SENT_RE.split(para_text)
        for i, s in enumerate(sents):
            is_last = i == len(sents) - 1
            all_sentences.append((s.strip(), is_last))

    # ── 3. Group sentences into scenes ────────────────────────────────────
    scenes: list[dict] = []
    bucket: list[str] = []
    bucket_words = 0

    def _flush() -> None:
        if not bucket:
            return
        narration = " ".join(bucket)
        narration = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", narration).strip()
        wc = len(narration.split())
        title = " ".join(narration.split()[:4]).rstrip(".,!?...")
        scenes.append(
            {
                "index": len(scenes) + 1,
                "title": title,
                "narration": narration,
                "duration_seconds": max(8, int(wc * 0.5)),
                "visual_prompt": "",
            }
        )
        bucket.clear()

    for sentence, is_para_end in all_sentences:
        wc = len(sentence.split())
        would_overflow = bucket_words + wc > target_words * 1.6

        if would_overflow and bucket:
            _flush()
            bucket_words = 0

        bucket.append(sentence)
        bucket_words += wc

        # Flush at paragraph boundaries when bucket is reasonably full
        if is_para_end and bucket_words >= target_words * 0.6:
            _flush()
            bucket_words = 0

    _flush()
    return scenes


def _normalise_closing(text: str) -> str:
    """Lowercase, collapse repeated dots, strip trailing punctuation."""
    import re as _re
    return _re.sub(r"\.{2,}", ".", text.lower().strip()).rstrip(".")


def _is_closing_scene(narration: str) -> bool:
    """
    Return True if this narration belongs to the channel's closing section.

    Matches any scene whose text is a substring of (or contains) a known
    closing phrase.  Checks both:
      - _CLOSING_TRIGGERS — built at module load from the default brand config
      - The current brand config — catches runtime config reloads and
        multi-channel scenarios where config/brand_config.yaml was swapped

    Text is normalised (lowercase, collapsed repeated dots) before comparison
    so a config typo like "Clear mind.." still matches "Clear mind.".
    """
    low = _normalise_closing(narration)

    for trigger in _CLOSING_TRIGGERS:
        t = _normalise_closing(trigger)
        if t in low or low in t:
            return True

    cfg = get_brand_config()
    for text in (cfg.closing.text(), cfg.signature.text(), cfg.cta.text()):
        if text:
            trigger = _normalise_closing(text)
            if trigger and (trigger in low or low in trigger):
                return True

    return False


def _mark_asset_scenes(scenes: list[dict]) -> list[dict]:
    """
    Post-process the scene list to detect channel closing scenes and mark them
    as asset scenes so the brand card is used instead of AI image generation.

    Asset path and animation are read from config/brand_config.yaml so no code
    change is needed when switching channels.

    Scans backwards from the end (up to 3 scenes) so that the brand card
    appears for the CTA and closing phrase without touching main content.
    Returns the same list, mutated in-place.
    """
    brand_cfg = get_brand_config()
    asset_path = brand_cfg.branding.asset_path
    animation = brand_cfg.branding.asset_animation

    tail = min(3, len(scenes))
    for scene in scenes[-tail:]:
        if _is_closing_scene(scene.get("narration", "")):
            scene["scene_type"] = "asset"
            scene["asset_path"] = asset_path
            scene["animation"] = animation
            scene["visual_prompt"] = ""
    return scenes


def _write_prompts_file(
    project_id: str,
    scenes: list[dict],
    style: str | None,
    settings: Settings,
) -> Path:
    """
    Write IMAGE_PROMPTS.md to the images/ directory.
    The user can take these prompts to any image generator, download the images,
    and place them with the exact filename shown — the pipeline will use them
    automatically (skipping its own image generation for those scenes).
    """
    images_dir = Path(WORKSPACE_DIR) / project_id / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    abs_images_dir = images_dir.resolve()

    w = settings.image_width
    h = settings.image_height
    total_scenes = len(scenes)
    style_label = style or "documentary"

    lines: list[str] = [
        f"# Image Prompts — {project_id}",
        f"**Style:** {style_label} | **Scenes:** {total_scenes} | **Size:** {w}×{h} px (16:9)",
        "",
        "---",
        "",
        "## How to Use",
        "",
        "1. Copy each prompt below into your preferred image generator.",
        f"2. Generate at **{w}×{h}** resolution (16:9). Any 16:9 size works — it gets resized.",
        "3. Download and **rename** each image to the exact filename shown (e.g. `scene-001.png`).",
        f"4. Place all images in this folder:  \n   `{abs_images_dir}`",
        "5. Re-run the pipeline — placed images are detected automatically and image generation is skipped.",
        "",
        "## Recommended Free Tools",
        "",
        "| Tool | Best for | Link |",
        "|------|----------|------|",
        "| **Leonardo AI** | Photorealistic, free daily credits | https://leonardo.ai |",
        "| **Adobe Firefly** | Safe, commercial-use images | https://firefly.adobe.com |",
        "| **Ideogram** | Text-accurate, stylized | https://ideogram.ai |",
        "| **Midjourney** | Highest quality (paid) | https://midjourney.com |",
        "| **DALL-E 3** | Via ChatGPT, great quality | https://chatgpt.com |",
        "",
        "**Tip:** For spiritual documentary style, try Leonardo with the *Cinematic Kino* or",
        "*Photorealism* model. Set negative prompt: `text, watermark, logo, blurry, cartoon`",
        "",
        "---",
        "",
        "## Re-run Command (after placing images)",
        "",
        "```bash",
        "# Delete old auto-generated scene videos so they re-render with your new images",
        f"rm workspace/jobs/{project_id}/video/scene-*.mp4",
        "",
        "# Re-run — existing images and audio are skipped, only video is rebuilt",
        f'ytfactory run "[your topic]" --project {project_id} --script [your_script.md] --style {style_label} --auto',
        "```",
        "",
        "---",
        "",
    ]

    for scene in scenes:
        idx: int = scene["index"]
        filename = f"scene-{idx:03d}.png"
        save_path = abs_images_dir / filename

        lines += [
            f"## Scene {idx} — `{filename}`",
            "",
            f"**Save to:** `{save_path}`",
            "",
            f"**Narration:** _{scene.get('narration', '')}_",
            "",
            "**Image Prompt:**",
            "",
            f"> {scene.get('visual_prompt', '')}",
            "",
            "---",
            "",
        ]

    content = "\n".join(lines)
    out_path = images_dir / "IMAGE_PROMPTS.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM JSON responses."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end])
    return text.strip()


def _parse_visual_prompts(text: str) -> list[dict] | None:
    """Parse Phase-2 output: [{index, visual_prompt}].

    Handles several LLM output styles:
    - Clean JSON array
    - JSON inside ```json...``` code fences (anywhere in the response)
    - Per-scene separate arrays on separate lines
    - JSON array anywhere in text (regex fallback)
    """

    def _valid(items: list) -> bool:
        return bool(items and all("index" in i and "visual_prompt" in i for i in items))

    raw = _strip_fences(text)

    # ── Try 1: whole stripped text is valid JSON ──────────────────────────
    try:
        data = json.loads(raw)
        items = (
            data.get("scenes", data.get("prompts", []))
            if isinstance(data, dict)
            else data
        )
        if isinstance(items, list) and _valid(items):
            return items
    except json.JSONDecodeError:
        pass

    # ── Try 2: JSON array inside a code fence block (Claude-style output) ─
    import re as _re

    for fence_re in [r"```json\s*(\[.*?\])\s*```", r"```\s*(\[.*?\])\s*```"]:
        m = _re.search(fence_re, text, _re.DOTALL)
        if m:
            try:
                items = json.loads(m.group(1))
                if isinstance(items, list) and _valid(items):
                    return items
            except json.JSONDecodeError:
                pass

    # ── Try 3: multiple separate JSON arrays on separate lines ────────────
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, list):
                items.extend(obj)
        except json.JSONDecodeError:
            pass
    if _valid(items):
        return items

    # ── Try 4: find first [...] JSON array anywhere in text ───────────────
    m = _re.search(r"(\[[\s\S]*?\])\s*(?:```|$|\n\n)", text)
    if m:
        try:
            items = json.loads(m.group(1))
            if isinstance(items, list) and _valid(items):
                return items
        except json.JSONDecodeError:
            pass

    return None


def _generate_vp_sub_batches(
    llm: "LLMProvider",
    batch: list[dict],
    style: str,
    visual_diary: list[str],
) -> list[dict] | None:
    """Retry a truncated batch by splitting it in half and calling each half separately."""
    half = max(1, len(batch) // 2)
    merged: list[dict] = []
    for sub in [batch[:half], batch[half:]]:
        if not sub:
            continue
        sub_prompt = build_visual_prompts_prompt(sub, style, prev_context=visual_diary or None)
        sub_resp = llm.generate(sub_prompt, temperature=0.35)
        if sub_resp.finish_reason == "length":
            logger.warning(
                "Sub-batch {}-{} still truncated after split — accepting partial results",
                sub[0]["index"],
                sub[-1]["index"],
            )
        sub_list = _parse_visual_prompts(sub_resp.text)
        if sub_list:
            merged.extend(sub_list)
    return merged or None


def scene_planner_node(state: VideoState) -> dict:
    """
    Scene Planner Agent:
    1. Load script from state / disk
    2. Generate scene plan JSON with retry loop on parse failure
    3. Validate and fix duration totals
    4. Second-pass: enhance visual prompts with cinematography guidance
    5. Save scene-plan.json + scene-plan.md
    """
    settings = Settings()
    llm = get_llm_provider(settings)
    artifact_repo = ArtifactRepository()
    project_repo = ProjectRepository()

    topic = state["topic"]
    project_id = state["project_id"]
    style = state.get("style")

    project_repo.update_stage(project_id, "scenes", "running")
    style_label = f" [{style}]" if style else ""
    console.print(
        f"\n[bold cyan]🎬 Scene Planner Agent[/bold cyan]{style_label} — "
        f"planning scenes for: [italic]{topic}[/italic]\n"
    )

    # ── Idempotency: load existing plan from disk if available ────────────
    existing_plan_path = Path(WORKSPACE_DIR) / project_id / "scenes" / "scene-plan.json"
    if existing_plan_path.exists():
        existing = json.loads(existing_plan_path.read_text(encoding="utf-8"))
        scenes = existing.get("scenes", [])
        total = sum(s.get("duration_seconds", 0) for s in scenes)
        console.print(
            f"  [green]✓[/green] Loaded existing scene plan — "
            f"{len(scenes)} scenes, ~{total / 60:.1f} min (skipping LLM calls)"
        )
        prompts_path = _write_prompts_file(project_id, scenes, style, settings)
        console.print(f"  [green]✓[/green] Image prompts: [dim]{prompts_path}[/dim]")
        project_repo.update_stage(project_id, "scenes", "completed")
        return {"scene_plan": scenes}

    # Load script — prefer state, fall back to disk
    script_md = state.get("script_md", "")
    if not script_md:
        script_path = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"
        if not script_path.exists():
            raise FileNotFoundError("Script not found. Run script-writer first.")
        script_md = script_path.read_text(encoding="utf-8")

    # ── Phase 1: Python-based script splitting (no LLM, no truncation risk) ──
    # The LLM was reliably failing to return 25+ scenes in one JSON response —
    # Groq cuts off mid-stream when output tokens get large. Python splitting is
    # deterministic, instant, and preserves every word verbatim.
    console.print("  [cyan]→[/cyan] Phase 1: splitting script into scenes...")
    scenes: list[dict] = _split_script_to_scenes(script_md)

    # Detect channel closing scenes and mark them as asset scenes so that
    # image generation is skipped and the brand card is used instead.
    _mark_asset_scenes(scenes)
    asset_count = sum(1 for s in scenes if s.get("scene_type") == "asset")
    if asset_count:
        brand_asset = get_brand_config().branding.asset_path
        console.print(
            f"  [green]✓[/green] {asset_count} closing scene(s) marked as asset scenes "
            f"[dim]({brand_asset})[/dim]"
        )

    total = sum(s.get("duration_seconds", 0) for s in scenes)
    narration_words = sum(len(s.get("narration", "").split()) for s in scenes)
    console.print(
        f"  [green]✓[/green] {len(scenes)} scenes — "
        f"{narration_words} words — {total:.0f}s (~{total / 60:.1f} min)"
    )

    # ── V4: Enrich scenes with shot types before Phase 2 ─────────────────
    _v4_engine = ImagePromptEngineV4()
    scenes = _v4_engine.enrich_scenes_with_shots(scenes)
    shot_plan = _v4_engine.get_shot_plan(scenes)
    console.print(
        f"  [cyan]→[/cyan] V4 shot plan: "
        f"{len(set(shot_plan))} distinct types across {len(shot_plan)} scenes"
    )

    # ── Phase 2: Visual prompts — use the configured LLM provider ───────────
    # Batch size: 10 scenes keeps each batch well under an 8192-token proxy cap (~500 tok/prompt).
    # Groq uses 7 (tighter output limit). If the proxy returns finish_reason=length the batch
    # is automatically split in half and retried by _generate_vp_sub_batches().
    # Asset scenes are excluded — they have no visual_prompt and skip image generation.
    _VP_BATCH = 7 if settings.llm_provider.lower() == "groq" else 10
    generated_scenes = [
        s for s in scenes if s.get("scene_type", "generated_image") == "generated_image"
    ]
    console.print(
        f"  [cyan]→[/cyan] Phase 2: generating visual prompts "
        f"[dim]({settings.llm_provider}, batches of {_VP_BATCH}, "
        f"{len(generated_scenes)}/{len(scenes)} scenes)[/dim]..."
    )
    vp_map: dict[int, str] = {}
    visual_diary: list[
        str
    ] = []  # cross-batch continuity: short summaries of prompts already written

    for batch_start in range(0, len(generated_scenes), _VP_BATCH):
        batch = generated_scenes[batch_start : batch_start + _VP_BATCH]
        batch_nums = f"{batch[0]['index']}–{batch[-1]['index']}"
        prompt = build_visual_prompts_prompt(
            batch, style, prev_context=visual_diary or None
        )
        vp_response = llm.generate(prompt, temperature=0.35)

        # If the proxy hit its output token cap, split the batch and retry each half.
        # Parsing a truncated response risks silently dropping the last N scenes.
        if vp_response.finish_reason == "length":
            logger.warning(
                "Batch {} hit output token limit ({} tokens) — splitting into sub-batches",
                batch_nums,
                vp_response.completion_tokens,
            )
            vp_list = _generate_vp_sub_batches(llm, batch, style, visual_diary)
        else:
            vp_list = _parse_visual_prompts(vp_response.text)
            # Retry once on parse failure
            if vp_list is None:
                logger.warning("Batch {} parse failed — retrying", batch_nums)
                vp_response = llm.generate(prompt, temperature=0.35)
                vp_list = _parse_visual_prompts(vp_response.text)

        if vp_list:
            expected_indexes = [s["index"] for s in batch]
            returned_indexes = [item["index"] for item in vp_list]

            # Safety net: if LLM reset indexes (e.g. returned 1-7 instead of 15-21),
            # remap by position so the correct scenes get their prompts.
            if returned_indexes != expected_indexes and len(vp_list) == len(batch):
                logger.warning(
                    "Batch {} — LLM returned indexes {} instead of {}; remapping by position",
                    batch_nums,
                    returned_indexes,
                    expected_indexes,
                )
                for item, scene in zip(vp_list, batch):
                    vp_map[scene["index"]] = item["visual_prompt"]
            else:
                for item in vp_list:
                    vp_map[item["index"]] = item["visual_prompt"]

            # Update visual diary for the next batch — first ~72 chars capture subject + environment
            for scene in batch:
                if scene["index"] in vp_map:
                    summary = vp_map[scene["index"]][:72].rstrip(",. ")
                    visual_diary.append(f"Sc.{scene['index']}: {summary}")
            visual_diary = visual_diary[-14:]  # keep the 14 most recent entries

            console.print(
                f"  [green]✓[/green] Scenes {batch_nums} — {len(vp_list)} prompts"
            )
        else:
            logger.warning(
                "Visual prompt batch {} returned malformed JSON after retry; using fallback",
                batch_nums,
            )

    # Apply prompts; fall back to title-based placeholder for any missed scene
    for s in scenes:
        if s["index"] in vp_map:
            s["visual_prompt"] = vp_map[s["index"]]
        elif not s.get("visual_prompt"):
            s["visual_prompt"] = (
                f"Cinematic wide shot, {s.get('title', 'contemplative moment')}, "
                "golden hour lighting, silhouette, spiritual documentary, no text, no watermark, photorealistic"
            )

    # ── V4: Diagnostics, validation, and debug output ─────────────────────
    v4_report = _v4_engine.build_diagnostics(scenes)
    v4_issues = _v4_engine.validate(scenes, v4_report)

    if v4_issues:
        for issue in v4_issues:
            logger.warning("V4 image prompt: {}", issue)
        console.print(
            f"  [yellow]⚠[/yellow] V4 validation: {len(v4_issues)} issue(s) — "
            f"diversity score {v4_report.diversity_score:.2f}"
        )
    else:
        console.print(
            f"  [green]✓[/green] V4 validation passed — "
            f"diversity score {v4_report.diversity_score:.2f}, "
            f"{len(set(shot_plan))} shot types"
        )

    if settings.image_prompt_debug:
        debug_dir = _v4_engine.write_debug_output(project_id, scenes, v4_report)
        console.print(f"  [green]✓[/green] V4 debug output: [dim]{debug_dir}[/dim]")

    # ── Persist artifacts ─────────────────────────────────────────────────
    scene_plan = {"topic": topic, "total_duration_seconds": total, "scenes": scenes}
    artifact_repo.write_json(project_id, "scenes", "scene-plan.json", scene_plan)

    # Human-readable markdown summary
    md_lines = [
        f"# Scene Plan: {topic}\n",
        f"Total: {len(scenes)} scenes, ~{total / 60:.1f} min\n",
    ]
    for s in scenes:
        md_lines.append(
            f"## Scene {s['index']}: {s['title']} ({s['duration_seconds']}s)\n"
            f"**Narration:** {s['narration']}\n\n"
            f"**Visual:** {s['visual_prompt']}\n"
        )
    artifact_repo.write_markdown(
        project_id, "scenes", "scene-plan.md", "\n".join(md_lines)
    )

    project_repo.update_stage(project_id, "scenes", "completed")

    # ── Write prompts file for manual image generation ────────────────────
    prompts_path = _write_prompts_file(project_id, scenes, style, settings)
    console.print(
        f"  [green]✓[/green] Image prompts exported: [dim]{prompts_path}[/dim]"
    )

    # Print summary table
    table = Table(title="Scene Plan", show_lines=True)
    table.add_column("#", style="cyan", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Duration", width=8)
    table.add_column("Narration preview", max_width=50)
    for s in scenes:
        narration_preview = (
            s["narration"][:60] + "…" if len(s["narration"]) > 60 else s["narration"]
        )
        scene_label = s["title"] + (
            " [asset]" if s.get("scene_type") == "asset" else ""
        )
        table.add_row(
            str(s["index"]), scene_label, f"{s['duration_seconds']}s", narration_preview
        )
    console.print(table)
    console.print(
        Panel(
            f"[green]Scene plan complete[/green] — {len(scenes)} scenes, ~{total / 60:.1f} minutes",
            title="Scene Planner Agent",
            border_style="green",
        )
    )

    return {"scene_plan": scenes}
