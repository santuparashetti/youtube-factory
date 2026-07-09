"""Image Prompt Engine V5 — documentary-quality, anatomy-safe prompt generation.

Orchestrates:
  1. Shot planning      — balanced shot type assignment, no consecutive repeats
  2. Scene enrichment   — injects shot_type into each scene dict
  3. Provider enrichment — adds anatomy reinforcement or negative prompts per provider
  4. Diagnostics        — shot distribution, uniqueness, repeated objects, AI clichés
  5. Prompt review      — per-prompt quality check before submission
  6. Validation         — pre-completion quality checks including cliché detection
  7. Debug output       — per-scene text files + image_prompt_debug.json (version v5)

V5 architecture:
  • Subject-first prompts (human storytelling over abstract symbolism)
  • Documentary-style realism (Netflix/BBC/NatGeo aesthetic)
  • Character continuity across scenes
  • Scene diversity (locations, lighting, emotional tone)
  • Natural human anatomy (no isolated hands, correct proportions)
  • Model-aware prompting (negative prompts for providers that support them;
    anatomy reinforcement appended to positive prompts for others)
  • Built-in prompt quality review before returning
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.images.clothing_policy import (
    apply_clothing_policy,
    detect_violation,
    get_negative_clothing_terms,
    is_authentic_exception,
)
from ytfactory.images.diagnostics import (
    _AI_CLICHES,
    _UNSAFE_COMPOSITIONS,
    DiagnosticsReport,
    build_report,
)
from ytfactory.images.human_detector import (
    add_human_quality_reinforcement,
    apply_subject_dominance_rule,
    detect_human_presence,
    has_human_quality_reinforcement,
)
from ytfactory.images.shot_planner import plan_shots, validate_shot_diversity
from ytfactory.shared.constants import WORKSPACE_DIR

# ---------------------------------------------------------------------------
# Provider capability constants
# ---------------------------------------------------------------------------

# These providers support native negative_prompt API parameters.
_PROVIDERS_WITH_NEGATIVE_PROMPTS: frozenset[str] = frozenset(
    {
        "huggingface",
        "a1111",
        "automatic1111",
        "sd-webui",
    }
)

# Anatomy reinforcement appended to positive prompts for providers that do NOT
# support negative prompts (e.g. Pollinations, Gemini).
_ANATOMY_REINFORCEMENT = (
    ", natural human anatomy, five fingers, correct proportions, realistic body posture"
)

# Default negative prompt for providers that support it.
# Clothing terms appended from clothing_policy at runtime to keep them in sync.
_DEFAULT_NEGATIVE_PROMPT = (
    "deformed hands, extra fingers, distorted anatomy, floating hands, giant hands, "
    "isolated hands, disembodied hands, AI artifacts, surreal distortions, "
    "multiple heads, merged limbs, text, watermark, logo, extreme close-up of body parts, "
    + get_negative_clothing_terms()
)


class ImagePromptEngineV4:
    """
    V5 image prompt engine (class name kept for backward compatibility).

    Usage inside scene_planner_node:
        engine = ImagePromptEngineV4()
        scenes = engine.enrich_scenes_with_shots(scenes)
        # ... LLM generates visual_prompt for each scene ...
        review_issues = engine.review_all_prompts(scenes)
        report = engine.build_diagnostics(scenes)
        issues = engine.validate(scenes, report)
        if settings.image_prompt_debug:
            engine.write_debug_output(project_id, scenes, report)

    For provider-aware anatomy reinforcement (call after LLM generates prompts):
        scenes = engine.enrich_for_provider(scenes, provider_name)
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

    def enrich_for_provider(
        self,
        scenes: list[dict],
        provider_name: str,
    ) -> list[dict]:
        """
        Return scenes with anatomy reinforcement appropriate for *provider_name*.

        - Providers with native negative prompt support → set ``negative_prompt``
          on each scene (used by ImagePipeline when building the ImageRequest).
        - Other providers (Pollinations, Gemini) → append ``_ANATOMY_REINFORCEMENT``
          to the ``visual_prompt`` positive text.

        Only generated_image scenes are touched; asset scenes pass through.
        """
        key = provider_name.lower().strip()
        uses_negative = key in _PROVIDERS_WITH_NEGATIVE_PROMPTS

        enriched: list[dict] = []
        for scene in scenes:
            s = dict(scene)
            if s.get("scene_type", "generated_image") == "generated_image":
                prompt = s.get("visual_prompt", "")
                shot_type = s.get("shot_type", "")

                # Human quality reinforcement (positive prompt, all providers)
                if prompt and detect_human_presence(prompt):
                    prompt = add_human_quality_reinforcement(prompt)
                    prompt = apply_subject_dominance_rule(prompt, shot_type)
                    s["visual_prompt"] = prompt

                # Clothing & cultural authenticity policy
                if prompt:
                    clothing_result = apply_clothing_policy(prompt, s)
                    s["visual_prompt"] = clothing_result.final_prompt
                    prompt = clothing_result.final_prompt
                    if clothing_result.action != "none":
                        s["clothing_policy_action"] = clothing_result.action
                        s["clothing_policy_terms"] = clothing_result.violation_terms

                # Provider-specific anatomy reinforcement or negative prompt
                if uses_negative:
                    s["negative_prompt"] = _DEFAULT_NEGATIVE_PROMPT
                else:
                    if prompt and not prompt.endswith(_ANATOMY_REINFORCEMENT):
                        s["visual_prompt"] = prompt + _ANATOMY_REINFORCEMENT
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

    def review_prompt(self, prompt: str, scene_index: int) -> list[str]:
        """
        Review a single visual prompt for V5 quality issues.

        Returns a list of human-readable issue strings (empty = prompt is clean).
        Checks:
          - Opening with a banned phrase ("A figure", "A person", etc.)
          - Narration-copy patterns ("a man who X" where X is abstract narration)
          - AI visual clichés present in the prompt
          - Unsafe composition keywords present
          - Missing style markers (no text, no watermark, photorealistic)
          - Prompt word count (too short or too long)
        """
        issues: list[str] = []
        p_lower = prompt.lower().strip()

        # Banned opening phrases
        _BANNED_OPENERS = (
            "a figure ",
            "a person ",
            "a silhouette ",
            "a traveler ",
            "a man ",
            "a woman ",
            "a bird ",
            "the camera ",
            "we see ",
            "there is a ",
        )
        for opener in _BANNED_OPENERS:
            if p_lower.startswith(opener):
                issues.append(
                    f"Scene {scene_index}: banned opener '{opener.strip()}' — "
                    "lead with the strongest visual element instead"
                )
                break

        # AI clichés
        for cliche in _AI_CLICHES:
            if cliche.lower() in p_lower:
                issues.append(
                    f"Scene {scene_index}: AI visual cliché '{cliche}' — "
                    "use a real documentary visual instead"
                )

        # Unsafe compositions
        for comp in _UNSAFE_COMPOSITIONS:
            if comp.lower() in p_lower:
                issues.append(
                    f"Scene {scene_index}: unsafe composition '{comp}' — "
                    "use environmental portrait, profile shot, or wide cinematic"
                )

        # Style markers
        _STYLE_MARKERS = (
            "photorealistic",
            "documentary",
            "cinematic",
            "no text",
            "no watermark",
        )
        if not any(m in p_lower for m in _STYLE_MARKERS):
            issues.append(
                f"Scene {scene_index}: missing style marker — "
                "add 'photorealistic' and 'no text, no watermark'"
            )

        # Human quality markers
        if detect_human_presence(prompt) and not has_human_quality_reinforcement(
            prompt
        ):
            issues.append(
                f"Scene {scene_index}: human detected but missing quality markers — "
                "add: highly detailed face, natural facial expression, realistic eyes, "
                "authentic skin texture, natural posture, documentary-quality realism"
            )

        # Clothing & cultural authenticity policy
        violations = detect_violation(prompt)
        if violations and not is_authentic_exception(prompt):
            issues.append(
                f"Scene {scene_index}: clothing policy violation — "
                f"terms detected: {violations}. "
                "Ensure subjects wear contextually appropriate clothing. "
                "Authentic cultural exceptions (sadhu, jain monk, ancient ascetic) are allowed."
            )

        # Word count
        word_count = len(prompt.split())
        if word_count < 30:
            issues.append(
                f"Scene {scene_index}: prompt too short ({word_count} words) — "
                "aim for 60–90 words of specific visual detail"
            )
        elif word_count > 150:
            issues.append(
                f"Scene {scene_index}: prompt too long ({word_count} words) — "
                "simplify to 60–90 words, 2–3 environmental details max"
            )

        return issues

    def review_all_prompts(self, scenes: list[dict]) -> dict[int, list[str]]:
        """
        Review all generated_image scenes.

        Returns a mapping of scene_index → list[issue_strings].
        Scenes with no issues have an empty list.
        """
        results: dict[int, list[str]] = {}
        for scene in scenes:
            if scene.get("scene_type", "generated_image") != "generated_image":
                continue
            idx: int = scene["index"]
            prompt: str = scene.get("visual_prompt", "")
            results[idx] = self.review_prompt(prompt, idx)
        return results

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
        - V5: No AI visual clichés
        - V5: No unsafe compositions
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

        # V5 checks
        if report.ai_cliches_detected:
            for cliche, scene_list in report.ai_cliches_detected.items():
                failures.append(f"[ai_cliche] '{cliche}' found in scenes: {scene_list}")

        if report.unsafe_compositions_detected:
            for comp, scene_list in report.unsafe_compositions_detected.items():
                failures.append(
                    f"[unsafe_composition] '{comp}' found in scenes: {scene_list}"
                )

        # Clothing policy violations remaining after enforcement pass
        if report.clothing_violations:
            failures.append(
                f"[clothing_policy] Violation terms corrected in scenes: "
                f"{report.clothing_violations} — "
                "review prompts to ensure the LLM no longer generates these"
            )

        return failures

    def write_debug_output(
        self,
        project_id: str,
        scenes: list[dict],
        report: DiagnosticsReport,
    ) -> Path:
        """
        Write V5 debug artifacts to workspace/jobs/{project_id}/images/debug/:
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
            "version": "v5",
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
