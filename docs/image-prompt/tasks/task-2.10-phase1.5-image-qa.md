# Task 2.10 — Phase 1.5: Image QA Gate
**New CLI command:** `yt verify-images --project <id>`
**Runs:** after images are manually placed, before Phase 2
**Purpose:** Verify every placed image against its visual_prompt before Phase 2 renders
**Files:** `src/ytfactory/images/verify.py` (new) + `src/ytfactory/cli/main.py`

---

## Token Efficiency

- Vision model call per scene: max_tokens=200 (KEEP/REGENERATE + 1-3 reasons)
- Use existing `FAITHFULNESS_VALIDATOR_MODEL` (google/gemini-2.5-flash-lite) — already configured
- Only call vision model on scenes where image file exists — skip missing images
- Batch-friendly: run all scenes, collect results, print summary at end
- No new LLM calls beyond vision model — decision is vision-only

---

## CLI Interface

```bash
# Verify all placed images
yt verify-images --project a-word-for-those-who-say-i-can-not-do-anything

# Verify specific scenes only
yt verify-images --project <id> --scenes 1,5,12

# Auto-mode: print report only, no interactive prompts
yt verify-images --project <id> --auto
```

---

## Workflow

```
For each scene in image_prompts_manifest.json:
  1. Check image file exists at images/scene-NNN.png
     → if missing: report MISSING, skip
  2. Load image + visual_prompt + shot_type
  3. Call vision model with verification prompt
  4. Parse response: KEEP or REGENERATE
  5. If REGENERATE: store reasons
  6. Print per-scene result inline as it completes
  7. After all scenes: print summary report
  8. Write results to images/image_qa_report.json
  9. Exit code 0 if all KEEP, exit code 1 if any REGENERATE or MISSING
```

---

## Vision Verification Prompt

```python
IMAGE_QA_PROMPT = """\
You are a strict image QA reviewer for a cinematic documentary storyboard.

VISUAL PROMPT (authoritative source):
{visual_prompt}

SHOT TYPE: {shot_type}

Review the image against the visual prompt. Check in order:
1. PRIMARY SUBJECT: Is the exact primary subject present? No substitution, no missing subject.
2. NO INVENTED ELEMENTS: Are there people, animals, objects, buildings, or props NOT in the prompt?
3. SHOT TYPE: Does the camera angle/framing match exactly? ({shot_type})
4. ENVIRONMENT: Does the setting match the prompt?
5. LIGHTING: Does direction, time of day, and color temperature match?
6. COMPOSITION: Does framing, scale, negative space, and perspective match?
7. QUALITY: Photorealistic, no text, no watermark, no artifacts?

Return ONLY one of these two formats — nothing else:

KEEP

or

REGENERATE
Reasons:
- <reason 1>
- <reason 2>
- <reason 3 (optional)>

Be strict. Minor artistic variation is acceptable. Any wrong subject,
invented element, wrong shot type, or wrong environment = REGENERATE."""
```

---

## Implementation

### `src/ytfactory/images/verify.py`

```python
from dataclasses import dataclass
from pathlib import Path
from enum import Enum
import json
import base64
import logging

logger = logging.getLogger(__name__)

class QADecision(str, Enum):
    KEEP = "keep"
    REGENERATE = "regenerate"
    MISSING = "missing"
    ERROR = "error"

@dataclass
class SceneQAResult:
    scene_id: int
    filename: str
    decision: QADecision
    reasons: list[str]  # empty if KEEP
    visual_prompt: str
    shot_type: str

def _encode_image(path: Path) -> str:
    """Base64-encode image for vision model."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def _parse_qa_response(response: str) -> tuple[QADecision, list[str]]:
    """
    Parse vision model response.
    Returns (decision, reasons).
    On parse failure: returns (KEEP, []) — non-blocking.
    """
    text = response.strip()
    if text.upper().startswith("KEEP"):
        return QADecision.KEEP, []

    if text.upper().startswith("REGENERATE"):
        reasons = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                reasons.append(line[2:].strip())
        return QADecision.REGENERATE, reasons[:3]  # max 3 reasons

    # Ambiguous — log and pass
    logger.warning(f"QA response parse ambiguous: {text[:100]} — defaulting to KEEP")
    return QADecision.KEEP, []

def verify_scene(
    scene: dict,
    images_dir: Path,
    vision_client,
) -> SceneQAResult:
    """Verify one scene image against its visual_prompt."""
    scene_id = scene["scene_id"]
    filename = scene["expected_filename"]
    visual_prompt = scene["visual_prompt"]
    shot_type = scene.get("shot_type", "unspecified")
    scene_type = scene.get("scene_type", "")
    image_path = images_dir / filename

    # Brand card — skip QA
    if scene_type == "brand_card":
        return SceneQAResult(
            scene_id=scene_id, filename=filename,
            decision=QADecision.KEEP, reasons=[],
            visual_prompt=visual_prompt, shot_type=shot_type,
        )

    # Missing image
    if not image_path.exists() or image_path.stat().st_size < 1000:
        return SceneQAResult(
            scene_id=scene_id, filename=filename,
            decision=QADecision.MISSING, reasons=["Image file not found or too small"],
            visual_prompt=visual_prompt, shot_type=shot_type,
        )

    try:
        image_b64 = _encode_image(image_path)
        prompt = IMAGE_QA_PROMPT.format(
            visual_prompt=visual_prompt,
            shot_type=shot_type,
        )
        response = vision_client.verify(
            image_b64=image_b64,
            prompt=prompt,
            max_tokens=200,
        )
        decision, reasons = _parse_qa_response(response)
    except Exception as e:
        logger.warning(f"Scene {scene_id:03d} QA error: {e} — defaulting to KEEP")
        return SceneQAResult(
            scene_id=scene_id, filename=filename,
            decision=QADecision.KEEP, reasons=[],
            visual_prompt=visual_prompt, shot_type=shot_type,
        )

    return SceneQAResult(
        scene_id=scene_id, filename=filename,
        decision=decision, reasons=reasons,
        visual_prompt=visual_prompt, shot_type=shot_type,
    )

def verify_all_scenes(
    manifest_path: Path,
    images_dir: Path,
    vision_client,
    scene_filter: list[int] | None = None,
) -> list[SceneQAResult]:
    """
    Verify all scenes in manifest.
    scene_filter: if set, only verify these scene_ids.
    """
    with open(manifest_path) as f:
        manifest = json.load(f)

    scenes = manifest["scenes"]
    if scene_filter:
        scenes = [s for s in scenes if s["scene_id"] in scene_filter]

    results = []
    for scene in scenes:
        result = verify_scene(scene, images_dir, vision_client)
        _log_result(result)
        results.append(result)

    return results

def _log_result(result: SceneQAResult):
    icons = {
        QADecision.KEEP: "✓",
        QADecision.REGENERATE: "✗",
        QADecision.MISSING: "?",
        QADecision.ERROR: "!",
    }
    icon = icons[result.decision]
    msg = f"  Scene {result.scene_id:03d} | {icon} {result.decision.upper():12s} | {result.filename}"
    if result.reasons:
        for r in result.reasons:
            msg += f"\n              → {r}"
    print(msg)

def write_qa_report(results: list[SceneQAResult], output_path: Path):
    keep = [r for r in results if r.decision == QADecision.KEEP]
    regen = [r for r in results if r.decision == QADecision.REGENERATE]
    missing = [r for r in results if r.decision == QADecision.MISSING]

    report = {
        "summary": {
            "total": len(results),
            "keep": len(keep),
            "regenerate": len(regen),
            "missing": len(missing),
        },
        "scenes": [
            {
                "scene_id": r.scene_id,
                "filename": r.filename,
                "decision": r.decision.value,
                "reasons": r.reasons,
            }
            for r in results
        ],
    }
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    return report
```

### CLI wiring in `src/ytfactory/cli/main.py`

```python
@app.command("verify-images")
def verify_images_cmd(
    project: str = typer.Option(..., help="Project ID"),
    scenes: str = typer.Option(None, help="Comma-separated scene IDs to verify"),
    auto: bool = typer.Option(False, help="Non-interactive mode"),
):
    """Verify placed images against their visual prompts before Phase 2."""
    from ytfactory.images.verify import verify_all_scenes, write_qa_report

    workspace = get_workspace_path(project)
    manifest_path = workspace / "image_prompts_manifest.json"
    images_dir = workspace / "images"
    report_path = images_dir / "image_qa_report.json"

    if not manifest_path.exists():
        typer.echo("No manifest found. Run Phase 1 first.")
        raise typer.Exit(1)

    scene_filter = None
    if scenes:
        scene_filter = [int(s.strip()) for s in scenes.split(",")]

    # Use existing cheap vision client
    vision_client = get_vision_client(settings)

    typer.echo(f"\n🔍 Verifying images for: {project}\n")
    results = verify_all_scenes(manifest_path, images_dir, vision_client, scene_filter)

    report = write_qa_report(results, report_path)
    summary = report["summary"]

    typer.echo(f"\n{'─'*60}")
    typer.echo(f"  KEEP:        {summary['keep']}/{summary['total']}")
    typer.echo(f"  REGENERATE:  {summary['regenerate']}/{summary['total']}")
    typer.echo(f"  MISSING:     {summary['missing']}/{summary['total']}")
    typer.echo(f"  Report:      {report_path}")
    typer.echo(f"{'─'*60}\n")

    if summary["regenerate"] > 0:
        typer.echo("⚠  Some images need regeneration. See report for reasons.")

    if summary["missing"] > 0:
        typer.echo("⚠  Some images are missing. Place them before running Phase 2.")

    # Exit 1 if any failures — allows shell scripting
    if summary["regenerate"] > 0 or summary["missing"] > 0:
        raise typer.Exit(1)
```

---

## Output Example

```
🔍 Verifying images for: a-word-for-those-who-say-i-can-not-do-anything

  Scene 001 | ✓ KEEP         | scene-001.png
  Scene 002 | ✓ KEEP         | scene-002.png
  Scene 003 | ✓ KEEP         | scene-003.png
  Scene 004 | ✗ REGENERATE   | scene-004.png
              → Wrong shot type: expected close-up, got wide shot
              → Chick is not visible in foreground
  Scene 005 | ✓ KEEP         | scene-005.png
  Scene 006 | ? MISSING       | scene-006.png
  ...

────────────────────────────────────────────────────────────
  KEEP:        26/30
  REGENERATE:  2/30
  MISSING:     1/30
  Report:      workspace/jobs/.../images/image_qa_report.json
────────────────────────────────────────────────────────────

⚠  Some images need regeneration. See report for reasons.
⚠  Some images are missing. Place them before running Phase 2.
```

---

## Settings

Add to `SharedSettings`:
```python
image_qa_enabled: bool = Field(default=True, env="IMAGE_QA_ENABLED")
image_qa_max_tokens: int = Field(default=200, env="IMAGE_QA_MAX_TOKENS")
```

Add to `.env.example`:
```bash
IMAGE_QA_ENABLED=true
IMAGE_QA_MAX_TOKENS=200
```

---

## Tests

```python
def test_parse_keep_response():
    decision, reasons = _parse_qa_response("KEEP")
    assert decision == QADecision.KEEP
    assert reasons == []

def test_parse_regenerate_response():
    response = "REGENERATE\nReasons:\n- Wrong shot type\n- Missing subject"
    decision, reasons = _parse_qa_response(response)
    assert decision == QADecision.REGENERATE
    assert len(reasons) == 2
    assert "Wrong shot type" in reasons[0]

def test_parse_ambiguous_defaults_to_keep():
    decision, reasons = _parse_qa_response("I think this looks okay")
    assert decision == QADecision.KEEP

def test_missing_image_returns_missing():
    scene = {"scene_id": 1, "expected_filename": "scene-001.png",
             "visual_prompt": "test", "shot_type": "wide", "scene_type": "generated_image"}
    result = verify_scene(scene, Path("/nonexistent"), mock_client)
    assert result.decision == QADecision.MISSING

def test_brand_card_skipped():
    scene = {"scene_id": 30, "expected_filename": "scene-030.png",
             "visual_prompt": "Brand Card", "shot_type": "wide", "scene_type": "brand_card"}
    result = verify_scene(scene, Path("/any"), mock_client)
    assert result.decision == QADecision.KEEP

def test_qa_error_defaults_to_keep():
    # Vision client throws — should not block pipeline
    result = verify_scene(scene, images_dir, failing_client)
    assert result.decision == QADecision.KEEP

def test_write_qa_report_structure():
    results = [
        SceneQAResult(1, "scene-001.png", QADecision.KEEP, [], "", ""),
        SceneQAResult(2, "scene-002.png", QADecision.REGENERATE, ["wrong subject"], "", ""),
    ]
    report = write_qa_report(results, tmp_path / "report.json")
    assert report["summary"]["keep"] == 1
    assert report["summary"]["regenerate"] == 1

def test_cli_exit_code_1_on_regenerate():
    # CLI must exit with code 1 when any scene needs regeneration
    result = runner.invoke(app, ["verify-images", "--project", "test", "--auto"])
    assert result.exit_code == 1
```

---

---

## Additional Scope — Update `image_generation_rules.md` Generation

Phase 1 generates `image_generation_rules.md` and writes it to the job
folder. Find where this file is generated in the pipeline (likely
`src/ytfactory/agents/nodes/scene_assets.py` or
`src/ytfactory/images/pipeline.py`) and replace the v1 content with
the v2 content below.

This ensures every new Phase 1 run produces the correct rules file
automatically — no manual copying needed.

**Replace the generated content with:**

```markdown
# Image Generation Rules
**Version:** 2.0 — Storyboard Mode

---

## Source of Truth

- The `visual_prompt` is the **single source of truth** for what to generate.
- The narration provides **emotional tone and mood only** — it does not add subjects, actions, or environments.
- Never infer visual elements from the narration that are not in the `visual_prompt`.
- When uncertain whether to include something: **omit rather than invent**.

---

## Storyboard Mode (mandatory)

Every scene is an independent storyboard frame. Treat it as such:

- Generate **only** what is explicitly described in the `visual_prompt`.
- Do **not** continue characters, objects, or environments from previous scenes unless explicitly stated.
- Do **not** invent people, animals, props, furniture, architecture, or landscape elements not described.
- Preserve intentional emptiness and negative space — empty space in the prompt means empty space in the image.
- Match the requested shot type, camera angle, composition, lighting, and environment **exactly**.

---

## Camera & Composition

- Apply the exact shot type specified: establishing, wide, medium, close-up, extreme close-up, drone, low angle, high angle, POV, tracking, over-the-shoulder, profile, environmental portrait.
- Apply cinematic optics: Wide ~24–35mm, Medium ~50–85mm, Close-up ~85–135mm, natural depth of field.
- Respect subject placement, scale, framing, and negative space as described.
- Maintain realistic perspective — object size must change naturally with distance.

---

## Subject & Scale

- Maintain real-world physical scale for all subjects (humans, animals, objects, architecture, vegetation).
- Use realistic proportions — anatomically and structurally accurate humans, animals, and environments.
- Preserve environmental scale cues (terrain, rocks, trees, doors reinforce believable size relationships).

---

## Continuity

When scenes share a character, location, or setting:
- Same character appearance, costume, age, and build across scenes
- Same environment lighting, time of day, and visual style
- Same overall color palette unless the prompt specifies a change

---

## Quality

- Photorealistic cinematic quality
- Natural lighting, realistic materials, physically accurate shadows
- No text, no watermark, no artifacts, no cartoon, no illustration style
- Output: **1280×720 px (16:9)**

---

## Rejection Criteria (regenerate immediately)

Regenerate without hesitation if:
- Wrong or missing primary subject
- Invented subject not in the prompt
- Wrong camera angle or shot type
- Wrong environment or setting
- Text or watermark visible
- Wrong lighting or time of day
- Non-photorealistic or illustrated look
- Incorrect aspect ratio or resolution
```

Add a test confirming the generated file contains "Storyboard Mode":
```python
def test_image_generation_rules_contains_storyboard_mode(tmp_path):
    # Run Phase 1 image rules generation
    # Confirm output file contains v2 content marker
    rules_path = tmp_path / "image_generation_rules.md"
    generate_image_rules(rules_path)
    content = rules_path.read_text()
    assert "Storyboard Mode" in content
    assert "single source of truth" in content
    assert "omit rather than invent" in content
```

---

## Do NOT change

- Phase 1 pipeline logic beyond the rules file content
- Phase 2 pipeline
- Existing `ImageReviewEngine` (runs inside Phase 2 separately)
- Any validator, scene planner, or prompt template
- Test baseline — do not regress
