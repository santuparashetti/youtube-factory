# Spec: Two-Phase Pipeline Split (Manual Image Generation Break)

## Goal
Split the pipeline into two runs with a manual step in between, so images can be generated externally (via a web tool) from the pipeline's own generated prompts, then fed back in.

## New behavior

### Phase 1 command (e.g. `--phase=prep` or new `.env` flag `PIPELINE_MODE=prep_only`)
Run the pipeline through every current stage **except actual image generation/download**:
- research_agent / script_enhancer
- scene_planner
- TTS / audio generation (with spiritual pause timing)
- subtitle generation (WhisperX alignment etc.)
- any other stage that currently runs before/alongside image generation (BGM mixing if it doesn't depend on final render — confirm)

**Image generation stage behavior in this mode:**
- Do NOT call any image provider (skip `HF_IMAGE_MODEL` / tier1-3 calls entirely — no HF/API cost incurred)
- DO still generate and persist the per-scene image prompts (the existing `visual_prompt` / prompt-refinement logic runs as normal, just the generation call itself is skipped)
- Write all scene image prompts to a manifest file in the project directory, e.g. `image_prompts_manifest.json`, with at minimum: `scene_id`, `expected_filename` (see naming convention below), `visual_prompt`, `shot_type`, `motion_type` (if already planned)

**Verification + stop:**
- After all above stages complete, run existing verification/QC checks that don't require images (script QC, audio QC, subtitle QC, scene plan completeness — e.g. shot_type present, motion variety, brand-card scene present)
- Produce a single **stop report** (e.g. `phase1_report.md` or `.json`) summarizing: stages completed, any QC warnings/failures, total scene count, path to `image_prompts_manifest.json`, path to the images folder the user needs to fill
- Pipeline halts here — no video rendering, no image generation, no publish steps run

### Manual step (outside pipeline, not code)
User generates images externally from `image_prompts_manifest.json` and places all resulting image files into the project's images folder (path pipeline already uses for scene assets, or a clearly designated folder like `<project_dir>/images/`), using `expected_filename` from the manifest so the pipeline can match them back to scenes.

### Phase 2 command (e.g. `--phase=resume` or `PIPELINE_MODE=resume`)
Resume the same project:
1. **Validation step first:** check that every `expected_filename` in `image_prompts_manifest.json` exists in the images folder. If any are missing, fail fast with a clear list of missing scene_ids/filenames — do not proceed.
2. Run remaining stages exactly as the pipeline currently does, treating the manually-placed images as if they were pipeline-generated for those scenes:
   - Image QA (if applicable/desired for externally-sourced images — flag this as a decision point, see Open Questions)
   - video_renderer (with motion effects — zoompan/push-in/pull-out as currently implemented)
   - subtitle burn-in
   - video_concatenator
   - cta
   - quality_review / remediation
   - publish (artifact generation) — **excluding thumbnail generation entirely** in this run

## Naming convention
Define `expected_filename` deterministically from `scene_id` (e.g. `scene_{scene_id:03d}.png`) so there's no ambiguity matching manually-generated images back to scenes.

## Decisions (confirmed, no longer open)
1. **Image QA: skip entirely in Phase 2.** Manually-sourced images are reviewed by the user directly — do not run ImageReviewEngine/anatomy-defect checks on them.
2. **BGM mixing: run in Phase 2**, not Phase 1 — placed wherever it fits naturally in the remaining render stages (Kilo to confirm exact ordering against `video_renderer`/`video_concatenator`, but default to Phase 2 unless there's a hard technical reason it must run earlier).
3. Thumbnail generation location: still flag back exactly where it currently sits in the publish stage, so it can be cleanly excluded from the Phase 2 run rather than just skipped-and-logged.

## Interactive CLI change
When running `uv run ytfactory` with no other args (the current interactive entrypoint), present a selection menu instead of jumping straight into the existing flow:

```
1. New   — start a new project (current default behavior, runs Phase 1)
2. Resume — resume an existing project from its saved state (runs Phase 2)
```

- Selecting **New** should behave exactly as the current interactive flow does today, but stop at the Phase 1 boundary (per this spec) instead of running straight through to publish.
- Selecting **Resume** should list existing in-progress projects (project dir / name, and Phase 1 completion timestamp) for the user to pick from, then run Phase 2 validation + remaining stages against the selected project.
- Any existing non-interactive/flag-based invocation (if one exists, e.g. `uv run ytfactory --project X`) should keep working unchanged — this menu only applies to the bare interactive entrypoint.

## Testing
- Add a test project fixture that runs Phase 1, asserts no image-provider calls were made (mock/spy), asserts manifest + report are written, asserts pipeline halts cleanly.
- Add a test that runs Phase 2 against a fixture images folder: one with all files present (should proceed), one with a missing file (should fail fast with clear error).
- Run full existing test suite to confirm no regression to single-phase mode (should probably remain the default when no `PIPELINE_MODE` is set).
