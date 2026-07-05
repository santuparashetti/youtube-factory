"""Image Prompt Engine V4 — cinematic, story-driven prompt generation.

Orchestrates:
  1. Shot planning  — balanced shot type assignment, no consecutive repeats
  2. Scene enrichment — injects shot_type into each scene dict
  3. Diagnostics     — shot distribution, uniqueness, repeated objects, diversity
  4. Validation      — pre-completion quality checks
  5. Debug output    — per-scene text files + image_prompt_debug.json
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.images.diagnostics import DiagnosticsReport, build_report
from ytfactory.images.shot_planner import plan_shots, validate_shot_diversity
from ytfactory.shared.constants import WORKSPACE_DIR


class ImagePromptEngineV4:
    """
    V4 image prompt engine.

    Usage inside scene_planner_node:
        engine = ImagePromptEngineV4()
        scenes = engine.enrich_scenes_with_shots(scenes)
        # ... LLM generates visual_prompt for each scene ...
        report = engine.build_diagnostics(scenes)
        issues = engine.validate(scenes, report)
        if settings.image_prompt_debug:
            engine.write_debug_output(project_id, scenes, report)
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    def enrich_scenes_with_shots(self, scenes: list[dict]) -> list[dict]:
        """
        Return a new list of scene dicts with ``shot_type`` added to each
        generated_image scene.  Asset scenes are left unchanged.

        The shot plan is deterministic: same scene count → same shot sequence.
        """
        generated_indices = [
            i
            for i, s in enumerate(scenes)
            if s.get("scene_type", "generated_image") == "generated_image"
        ]
        shot_plan = plan_shots(len(generated_indices))

        enriched: list[dict] = []
        plan_cursor = 0
        for scene in scenes:
            s = dict(scene)  # shallow copy — don't mutate caller's list
            if s.get("scene_type", "generated_image") == "generated_image":
                s["shot_type"] = shot_plan[plan_cursor]
                plan_cursor += 1
            enriched.append(s)
        return enriched

    def get_shot_plan(self, scenes: list[dict]) -> list[str]:
        """Extract the shot_type values from enriched scenes (generated only)."""
        return [
            s["shot_type"]
            for s in scenes
            if s.get("scene_type", "generated_image") == "generated_image"
            and "shot_type" in s
        ]

    def build_diagnostics(self, scenes: list[dict]) -> DiagnosticsReport:
        """Compute quality diagnostics after visual prompts have been generated."""
        shot_plan = self.get_shot_plan(scenes)
        return build_report(scenes, shot_plan)

    def validate(self, scenes: list[dict], report: DiagnosticsReport) -> list[str]:
        """
        Run pre-completion validation checks.

        Returns a list of validation failure messages (empty = all passed).
        Checks:
        - Shot diversity (via shot_planner.validate_shot_diversity)
        - No consecutive shot repeats
        - No repetitive symbolic objects
        - Adequate prompt coverage (all generated scenes have a non-empty prompt)
        - Style markers present
        - Acceptable visual diversity score
        """
        failures: list[str] = []

        shot_plan = self.get_shot_plan(scenes)
        for issue in validate_shot_diversity(shot_plan):
            failures.append(f"[shot diversity] {issue}")

        if report.consecutive_shot_repeats:
            failures.append(
                f"[shot continuity] Consecutive repeats at scenes: "
                f"{report.consecutive_shot_repeats}"
            )

        if report.repeated_objects:
            for obj, scene_list in report.repeated_objects.items():
                failures.append(
                    f"[repetition] '{obj}' appears in {len(scene_list)} scenes: "
                    f"{scene_list}"
                )

        missing_prompts = [
            s["index"]
            for s in scenes
            if s.get("scene_type", "generated_image") == "generated_image"
            and not s.get("visual_prompt", "").strip()
        ]
        if missing_prompts:
            failures.append(
                f"[coverage] Missing visual prompts for scenes: {missing_prompts}"
            )

        if not report.style_consistent:
            failures.append(
                f"[style] Scenes missing style markers "
                f"(photorealistic/documentary/cinematic): "
                f"{report.scenes_missing_style_markers}"
            )

        if report.diversity_score < 0.5:
            failures.append(
                f"[diversity] Visual diversity score too low: "
                f"{report.diversity_score:.2f} (minimum 0.50)"
            )

        return failures

    def write_debug_output(
        self,
        project_id: str,
        scenes: list[dict],
        report: DiagnosticsReport,
    ) -> Path:
        """
        Write V4 debug artifacts to workspace/jobs/{project_id}/images/debug/:
          - scene-001-original.txt  — narration (the prompt input)
          - scene-001-optimized.txt — final visual_prompt (the LLM output)
          - image_prompt_debug.json — full diagnostics report

        Returns the debug directory path.
        """
        debug_dir = Path(WORKSPACE_DIR) / project_id / "images" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)

        for scene in scenes:
            if scene.get("scene_type", "generated_image") != "generated_image":
                continue
            idx: int = scene["index"]
            narration: str = scene.get("narration", "")
            visual_prompt: str = scene.get("visual_prompt", "")
            shot_type: str = scene.get("shot_type", "")

            # original = input material (narration + assigned shot type)
            original_content = (
                f"Scene {idx}\nShot type: {shot_type}\nNarration:\n{narration}\n"
            )
            (debug_dir / f"scene-{idx:03d}-original.txt").write_text(
                original_content, encoding="utf-8"
            )

            # optimized = final visual prompt produced by LLM
            optimized_content = (
                f"Scene {idx}\n"
                f"Shot type: {shot_type}\n"
                f"Visual prompt:\n{visual_prompt}\n"
            )
            (debug_dir / f"scene-{idx:03d}-optimized.txt").write_text(
                optimized_content, encoding="utf-8"
            )

        # Full diagnostics JSON
        debug_json = {
            "version": "v4",
            "project_id": project_id,
            "total_scenes": len(scenes),
            "generated_scenes": sum(
                1
                for s in scenes
                if s.get("scene_type", "generated_image") == "generated_image"
            ),
            "diagnostics": report.to_dict(),
        }
        debug_json_path = debug_dir / "image_prompt_debug.json"
        debug_json_path.write_text(
            json.dumps(debug_json, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return debug_dir
