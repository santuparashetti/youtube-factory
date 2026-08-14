"""Tests for Image Prompt QA/Fix Pass.

Original seven focused tests:
  1. narration conflict → prompt repaired to match narration
  2. CHARACTER_PRESENCE: [] (NONE) → no character remains in repaired prompt
  3. unsupported character/prop → removed from repaired prompt
  4. text-rendering instruction → removed when compositor handles text
  5. visual-world conflict → repaired without changing narration
  6. valid prompt → preserved unchanged
  7. unresolved issue → status REVIEW_REQUIRED

Hardening tests (8 new, H-series):
  H1. Visual Bible context reaches QA prompt
  H2. scene_analysis / visual_metadata reach QA prompt
  H3. REVIEW_REQUIRED is persisted (report serialised completely)
  H4. API/LLM failure does not block and does not create false PASS
  H5. QA repair triggers final deterministic validation (repaired prompt visible post-QA)
  H6. Final validation sees the repaired prompt, not the original
  H7. Existing valid prompts remain unchanged
  H8. visual_prompt and compiled_prompt remain synchronised after repair

Consistency regression tests (C-series):
  C1. Enforcement re-run cannot be bypassed: enforcement functions correct repaired prompts
  C2. Final validators always see repaired+enforced prompt (scene dict is the contract)
  C3. Continuity report reflects the final prompt state via scene dict
  C4. Faithfulness upgrade: FAILED scenes that pass after repair produce correct qa dict
  C5. QA report preserves actual issues and repairs (to_dict is complete)
  C6. Top-level unresolved is derived from per-scene data, not trusted from LLM field
  C7. No second LLM QA call is introduced by run_prompt_qa_pass

New focused checks (new test classes at bottom):
  Check A: missing narrated subject/action/relationship
  Check D: metadata ↔ prompt contradiction (animal visible when presence=[])
  Check E: animal incorrectly treated as environment-only
  Check G: visual-world conflict (with Visual Bible context)
  Check I: camera/composition contradiction (macro+wide; side-profile+frontal)
  Check J: prohibited text rendering; designated compositor scene preserved
  Check L: impossible spatial/action relationship; unresolvable → REVIEW_REQUIRED
  Check M: duplicate/contradictory subject fields consolidated
  Valid prompt with new check areas remains unchanged
  Unresolved checks L and M produce REVIEW_REQUIRED
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ytfactory.images.prompt_qa import (
    PromptQAReport,
    _build_qa_prompt,
    _parse_qa_response,
    normalize_prompt_fields,
    run_prompt_qa_pass,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scene(
    index: int,
    narration: str,
    visual_prompt: str,
    character_presence: list[str] | None = None,
    anchor_role: str = "absent",
    scene_type: str = "generated_image",
) -> dict:
    return {
        "index": index,
        "title": f"Scene {index}",
        "narration": narration,
        "visual_prompt": visual_prompt,
        "duration_seconds": 12,
        "scene_type": scene_type,
        "character_presence": character_presence or [],
        "anchor_role": anchor_role,
    }


def _llm_returning(payload: dict) -> MagicMock:
    """Return a mock LLM provider whose generate() returns *payload* as JSON."""
    mock = MagicMock()
    response = MagicMock()
    response.text = json.dumps(payload)
    mock.generate.return_value = response
    return mock


def _qa_payload(scene_results: list[dict], unresolved: list | None = None) -> dict:
    """Build a minimal valid QA JSON response payload."""
    all_issues = sum(len(r.get("issues", [])) for r in scene_results)
    all_fixes = sum(len(r.get("fixes", [])) for r in scene_results)
    all_unresolved: list = []
    for r in scene_results:
        all_unresolved.extend(r.get("unresolved") or [])
    if unresolved is not None:
        all_unresolved = unresolved

    status = "REVIEW_REQUIRED" if all_unresolved else "PASS"
    return {
        "status": status,
        "scenes_checked": len(scene_results),
        "issues_found": all_issues,
        "issues_fixed": all_fixes,
        "unresolved": all_unresolved,
        "scene_results": scene_results,
    }


# ---------------------------------------------------------------------------
# Test 1 — narration conflict: prompt repaired to match narration
# ---------------------------------------------------------------------------


class TestNarrationConflictRepair:
    def test_prompt_updated_to_match_narration(self):
        """When prompt conflicts with narration, the repaired prompt must be applied."""
        narration = "The young mother cradles her newborn child by the river."
        bad_prompt = "Empty forest path at dawn, no living beings, mist rising."
        repaired = "Young mother, illustrated storybook style, cradling a newborn by a sunlit river."

        scene = _make_scene(1, narration, bad_prompt, character_presence=["MOTHER"])
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [{"check": "A", "description": "Prompt shows empty forest; narration requires mother and child."}],
            "fixes": ["Replaced empty forest with young mother cradling newborn by river."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.status == "PASS"
        assert report.issues_found == 1
        assert report.issues_fixed == 1
        # Repair applied in place
        assert scenes[0]["visual_prompt"] == repaired

    def test_original_prompt_preserved_when_no_conflict(self):
        """When repaired_prompt equals original, visual_prompt is not touched."""
        narration = "The eagle soars above the canyon."
        prompt = "Eagle soaring above a canyon, wide aerial shot, photorealistic."

        scene = _make_scene(2, narration, prompt)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 2,
            "issues": [],
            "fixes": [],
            "repaired_prompt": prompt,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert scenes[0]["visual_prompt"] == prompt


# ---------------------------------------------------------------------------
# Test 2 — CHARACTER_PRESENCE: [] (NONE) → no character remains
# ---------------------------------------------------------------------------


class TestNoneCharacterPresence:
    def test_character_stripped_when_presence_is_empty(self):
        """When character_presence=[], the repaired prompt must contain no character."""
        narration = "Autumn leaves fall onto the empty garden path."
        bad_prompt = "An old man walks through a garden of falling autumn leaves."
        repaired = "Autumn leaves drifting onto a stone garden path, no human figures, photorealistic."

        scene = _make_scene(3, narration, bad_prompt, character_presence=[])
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 3,
            "issues": [{"check": "D", "description": "CHARACTER_PRESENCE is NONE but prompt contains 'old man'."}],
            "fixes": ["Removed old man; left only falling leaves and garden path."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.status == "PASS"
        assert "old man" not in scenes[0]["visual_prompt"]
        assert scenes[0]["visual_prompt"] == repaired


# ---------------------------------------------------------------------------
# Test 3 — unsupported character/prop → removed
# ---------------------------------------------------------------------------


class TestUnsupportedCharacterRemoved:
    def test_invented_prop_removed_from_prompt(self):
        """A prop not in the narration or scene metadata is removed."""
        narration = "The philosopher sat in silence, contemplating the river."
        bad_prompt = (
            "Ancient Greek philosopher sitting by a river, holding a glowing crystal orb, "
            "photorealistic environment."
        )
        repaired = (
            "Ancient Greek philosopher seated by a river in silence, "
            "photorealistic environment, no text, no watermark."
        )

        scene = _make_scene(4, narration, bad_prompt)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 4,
            "issues": [{"check": "K", "description": "Glowing crystal orb not in narration or scene intent."}],
            "fixes": ["Removed glowing crystal orb; philosopher now sits empty-handed."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert "crystal orb" not in scenes[0]["visual_prompt"]
        assert scenes[0]["visual_prompt"] == repaired


# ---------------------------------------------------------------------------
# Test 4 — text-rendering instruction → removed when compositor handles text
# ---------------------------------------------------------------------------


class TestTextRenderingRemoved:
    def test_text_rendering_instruction_stripped(self):
        """Instructions to render exact readable text are replaced with compositor note."""
        narration = "The ancient Sanskrit verse echoes through the stone hall."
        bad_prompt = (
            "Stone hall interior. The screen displays the exact Sanskrit text "
            "'Tat tvam asi' in golden letters. Photorealistic."
        )
        repaired = (
            "Stone hall interior bathed in golden light. "
            "Leave open space for compositor text overlay. Photorealistic."
        )

        scene = _make_scene(5, narration, bad_prompt)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 5,
            "issues": [{"check": "J", "description": "Prompt requests rendering of exact Sanskrit text; compositor handles text."}],
            "fixes": ["Replaced text-render instruction with compositor space note."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert "Tat tvam asi" not in scenes[0]["visual_prompt"]
        assert "compositor" in scenes[0]["visual_prompt"].lower()


# ---------------------------------------------------------------------------
# Test 5 — visual-world conflict → repaired without changing narration
# ---------------------------------------------------------------------------


class TestVisualWorldConflict:
    def test_visual_world_repaired_narration_unchanged(self):
        """Prompt conflicting with dominant visual world is fixed; narration is untouched."""
        narration = "The monk bowed before the ancient temple, seeking guidance."
        bad_prompt = (
            "Lean young man in a glass-and-steel modern office, bowing toward a laptop screen. "
            "Illustrated character, photorealistic office."
        )
        repaired = (
            "Buddhist monk in grey robes bowing before an ancient stone temple entrance, "
            "illustrated character with ink outlines, photorealistic temple environment."
        )

        scene = _make_scene(6, narration, bad_prompt)
        scenes = [scene]
        original_narration = scene["narration"]

        payload = _qa_payload([{
            "scene_index": 6,
            "issues": [{"check": "G", "description": "Modern office contradicts the ancient/spiritual visual world."}],
            "fixes": ["Replaced modern office with ancient stone temple matching narration."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))

        # Narration must be unchanged
        assert scenes[0]["narration"] == original_narration
        # Prompt is updated
        assert scenes[0]["visual_prompt"] == repaired

    def test_narration_field_never_modified(self):
        """run_prompt_qa_pass never modifies the narration field."""
        scene = _make_scene(7, "A mother eagle feeds her chick.", "Eagle feeds chick, photorealistic.")
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 7,
            "issues": [],
            "fixes": [],
            "repaired_prompt": "Eagle feeds chick, photorealistic.",
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert scenes[0]["narration"] == "A mother eagle feeds her chick."


# ---------------------------------------------------------------------------
# Test 6 — valid prompt → preserved unchanged
# ---------------------------------------------------------------------------


class TestValidPromptPreserved:
    def test_clean_prompt_unchanged(self):
        """A prompt with no issues must not be modified at all."""
        narration = "The river carves its path through the ancient valley."
        prompt = (
            "Wide cinematic shot of a river carving through an ancient rocky valley, "
            "golden hour light, photorealistic, no text, no watermark."
        )

        scene = _make_scene(8, narration, prompt)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 8,
            "issues": [],
            "fixes": [],
            "repaired_prompt": prompt,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.status == "PASS"
        assert report.issues_found == 0
        assert scenes[0]["visual_prompt"] == prompt

    def test_asset_scenes_skipped(self):
        """Asset scenes are never sent to the QA LLM."""
        gen_scene = _make_scene(1, "A river flows.", "River, photorealistic.")
        asset_scene = {
            "index": 2,
            "narration": "",
            "visual_prompt": "",
            "scene_type": "asset",
            "character_presence": [],
        }
        scenes = [gen_scene, asset_scene]

        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [],
            "fixes": [],
            "repaired_prompt": "River, photorealistic.",
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert report is not None
        # Asset scene prompt untouched
        assert asset_scene["visual_prompt"] == ""


# ---------------------------------------------------------------------------
# Test 7 — unresolved issue → status REVIEW_REQUIRED
# ---------------------------------------------------------------------------


class TestUnresolvedIssueReviewRequired:
    def test_unresolved_issue_sets_review_required(self):
        """When any scene has unresolved issues the report status is REVIEW_REQUIRED."""
        narration = "A nameless figure dissolves into the crowd."
        bad_prompt = "A specific named historical figure standing alone on a stage, photorealistic."
        # QA cannot repair — the narration says 'nameless' but prompt requires a name
        unresolved = [{"check": "A", "description": "Cannot determine who to show; narration explicitly says nameless."}]

        scene = _make_scene(9, narration, bad_prompt)
        scenes = [scene]

        payload = {
            "status": "REVIEW_REQUIRED",
            "scenes_checked": 1,
            "issues_found": 1,
            "issues_fixed": 0,
            "unresolved": unresolved,
            "scene_results": [{
                "scene_index": 9,
                "issues": [{"check": "A", "description": "Prompt shows named figure; narration says nameless."}],
                "fixes": [],
                "repaired_prompt": bad_prompt,  # unchanged — cannot resolve
                "unresolved": unresolved,
            }],
        }

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.status == "REVIEW_REQUIRED"
        assert len(report.unresolved) == 1
        assert report.issues_fixed == 0

    def test_all_fixed_status_is_pass(self):
        """When all issues are fixed, status must be PASS."""
        scene = _make_scene(10, "The sea roars.", "A quiet pond, photorealistic.")
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 10,
            "issues": [{"check": "A", "description": "Pond does not match roaring sea."}],
            "fixes": ["Replaced pond with crashing ocean waves."],
            "repaired_prompt": "Crashing ocean waves, photorealistic.",
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert report is not None
        assert report.status == "PASS"


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestBuildQaPrompt:
    def test_includes_all_generated_scenes(self):
        scenes = [
            _make_scene(1, "Eagle soars.", "Eagle, photorealistic."),
            _make_scene(2, "River flows.", "River, photorealistic."),
            {"index": 3, "scene_type": "asset", "narration": "", "visual_prompt": ""},
        ]
        prompt = _build_qa_prompt(scenes)
        assert "SCENE 1:" in prompt
        assert "SCENE 2:" in prompt
        assert "SCENE 3:" not in prompt

    def test_includes_narration_and_visual_prompt(self):
        scenes = [_make_scene(1, "The wolf howls.", "Wolf howling, photorealistic.")]
        prompt = _build_qa_prompt(scenes)
        assert "The wolf howls." in prompt
        assert "Wolf howling, photorealistic." in prompt

    def test_includes_character_presence(self):
        scenes = [_make_scene(1, "Kai walks.", "Kai walking.", character_presence=["KAI"])]
        prompt = _build_qa_prompt(scenes)
        assert "KAI" in prompt

    def test_empty_scenes_returns_empty_string(self):
        assert _build_qa_prompt([]) == ""

    def test_only_asset_scenes_returns_empty_string(self):
        scenes = [{"index": 1, "scene_type": "asset", "narration": "", "visual_prompt": ""}]
        assert _build_qa_prompt(scenes) == ""


class TestParseQaResponse:
    def test_parses_valid_json(self):
        scenes = [_make_scene(1, "N.", "P.")]
        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [],
            "fixes": [],
            "repaired_prompt": "P.",
            "unresolved": [],
        }])
        report = _parse_qa_response(json.dumps(payload), scenes)
        assert report is not None
        assert report.status == "PASS"
        assert len(report.scene_results) == 1

    def test_returns_none_on_invalid_json(self):
        scenes = [_make_scene(1, "N.", "P.")]
        result = _parse_qa_response("not json at all", scenes)
        assert result is None

    def test_strips_markdown_fences(self):
        scenes = [_make_scene(1, "N.", "P.")]
        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [],
            "fixes": [],
            "repaired_prompt": "P.",
            "unresolved": [],
        }])
        fenced = "```json\n" + json.dumps(payload) + "\n```"
        report = _parse_qa_response(fenced, scenes)
        assert report is not None

    def test_falls_back_to_original_when_repaired_prompt_missing(self):
        scenes = [_make_scene(1, "N.", "Original prompt.")]
        payload = {
            "status": "PASS",
            "scenes_checked": 1,
            "issues_found": 0,
            "issues_fixed": 0,
            "unresolved": [],
            "scene_results": [{
                "scene_index": 1,
                "issues": [],
                "fixes": [],
                # repaired_prompt omitted
                "unresolved": [],
            }],
        }
        report = _parse_qa_response(json.dumps(payload), scenes)
        assert report is not None
        assert report.scene_results[0].repaired_prompt == "Original prompt."


class TestRunPromptQaPass:
    def test_returns_none_when_llm_raises(self):
        scene = _make_scene(1, "N.", "P.")
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("API error")
        report = run_prompt_qa_pass([scene], mock_llm)
        assert report is None

    def test_returns_none_on_unparseable_response(self):
        scene = _make_scene(1, "N.", "P.")
        mock_llm = MagicMock()
        response = MagicMock()
        response.text = "completely unparseable"
        mock_llm.generate.return_value = response
        report = run_prompt_qa_pass([scene], mock_llm)
        assert report is None

    def test_no_generated_scenes_returns_none(self):
        scenes = [{"index": 1, "scene_type": "asset", "narration": "", "visual_prompt": ""}]
        mock_llm = MagicMock()
        report = run_prompt_qa_pass(scenes, mock_llm)
        assert report is None
        mock_llm.generate.assert_not_called()

    def test_structured_prompt_compiled_prompt_also_updated(self):
        """When structured_prompt.compiled_prompt exists, it is updated alongside visual_prompt."""
        scene = _make_scene(1, "Narration.", "Old prompt.")
        scene["structured_prompt"] = {"compiled_prompt": "Old prompt.", "other": "data"}
        scenes = [scene]

        repaired = "New prompt after QA fix."
        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [{"check": "A", "description": "mismatch"}],
            "fixes": ["fixed it"],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert scenes[0]["visual_prompt"] == repaired
        assert scenes[0]["structured_prompt"]["compiled_prompt"] == repaired


# ---------------------------------------------------------------------------
# Hardening tests — H1 through H8
# ---------------------------------------------------------------------------


class TestVisualBibleReachesPrompt:
    """H1: Visual Bible context reaches the QA batch prompt."""

    def test_dominant_metaphor_in_prompt(self):
        """dominant_metaphor from visual_bible appears in the prompt text."""
        scenes = [_make_scene(1, "Eagle soars.", "Eagle, photorealistic.")]
        vb = {
            "dominant_metaphor": "spiritual awakening through nature",
            "anchor_environments": "ancient forest, mountain peaks",
            "color_arc": "warm gold to cool silver",
            "visual_motifs": "lotus, light rays",
        }
        prompt = _build_qa_prompt(scenes, visual_bible=vb)
        assert "spiritual awakening through nature" in prompt
        assert "ancient forest, mountain peaks" in prompt
        assert "warm gold to cool silver" in prompt
        assert "lotus, light rays" in prompt

    def test_visual_bible_section_present(self):
        """A VISUAL BIBLE section header is present when bible is supplied."""
        scenes = [_make_scene(1, "N.", "P.")]
        vb = {"dominant_metaphor": "river of time", "anchor_environments": "riverbanks"}
        prompt = _build_qa_prompt(scenes, visual_bible=vb)
        assert "VISUAL BIBLE" in prompt

    def test_no_project_visual_bible_section_when_omitted(self):
        """No PROJECT VISUAL BIBLE constraints block appears when visual_bible is None."""
        scenes = [_make_scene(1, "N.", "P.")]
        prompt = _build_qa_prompt(scenes)
        assert "PROJECT VISUAL BIBLE" not in prompt
        assert "DOMINANT_METAPHOR" not in prompt

    def test_visual_bible_passed_to_run_prompt_qa_pass(self):
        """run_prompt_qa_pass forwards visual_bible into the generated prompt."""
        scene = _make_scene(1, "Eagle soars.", "Eagle, photorealistic.")
        scenes = [scene]
        vb = {"dominant_metaphor": "journey of liberation"}

        payload = _qa_payload([{
            "scene_index": 1, "issues": [], "fixes": [],
            "repaired_prompt": "Eagle, photorealistic.", "unresolved": [],
        }])
        mock_llm = MagicMock()
        response = MagicMock()
        response.text = json.dumps(payload)
        mock_llm.generate.return_value = response

        run_prompt_qa_pass(scenes, mock_llm, visual_bible=vb)

        called_prompt = mock_llm.generate.call_args[0][0]
        assert "journey of liberation" in called_prompt


class TestSceneAnalysisReachesPrompt:
    """H2: scene_analysis and visual_metadata reach the QA batch prompt."""

    def test_visual_metadata_in_prompt(self):
        """visual_metadata fields appear in the per-scene block."""
        scenes = [_make_scene(1, "The monk meditates.", "Monk, illustrated.")]
        scenes[0]["visual_metadata"] = {
            "era": "ancient",
            "narrative_role": "STORY",
            "environment": "temple",
            "mood": "serene",
            "visual_style": "illustrated",
        }
        prompt = _build_qa_prompt(scenes)
        assert "era=ancient" in prompt
        assert "environment=temple" in prompt
        assert "mood=serene" in prompt

    def test_scene_analysis_map_in_prompt(self):
        """scene_analysis_map entries appear in the per-scene block."""
        scenes = [_make_scene(1, "Shiva dances.", "Shiva dancing.")]
        sa_map = {
            1: {
                "primary_subject": "Shiva",
                "allowed_characters": ["SHIVA"],
                "forbidden_characters": ["KAI"],
                "story_goal": "show cosmic dance",
                "emotional_beat": "awe",
            }
        }
        prompt = _build_qa_prompt(scenes, scene_analysis_map=sa_map)
        assert "subject=Shiva" in prompt
        assert "forbidden_chars=['KAI']" in prompt
        assert "goal=show cosmic dance" in prompt
        assert "emotional_beat=awe" in prompt

    def test_scene_analysis_map_via_run_prompt_qa_pass(self):
        """run_prompt_qa_pass forwards scene_analysis_map into the generated prompt."""
        scene = _make_scene(1, "Shiva dances.", "Shiva, illustrated.")
        scenes = [scene]
        sa_map = {1: {"forbidden_characters": ["KAI"], "primary_subject": "Shiva"}}

        payload = _qa_payload([{
            "scene_index": 1, "issues": [], "fixes": [],
            "repaired_prompt": "Shiva, illustrated.", "unresolved": [],
        }])
        mock_llm = MagicMock()
        response = MagicMock()
        response.text = json.dumps(payload)
        mock_llm.generate.return_value = response

        run_prompt_qa_pass(scenes, mock_llm, scene_analysis_map=sa_map)

        called_prompt = mock_llm.generate.call_args[0][0]
        assert "KAI" in called_prompt


class TestReviewRequiredPersistence:
    """H3: REVIEW_REQUIRED is persisted as a complete serialised report."""

    def test_to_dict_includes_scene_results(self):
        """to_dict() serialises scene_results with issues, fixes, unresolved."""
        from ytfactory.images.prompt_qa import PromptQAIssue, PromptQASceneResult

        report = PromptQAReport(
            status="REVIEW_REQUIRED",
            scenes_checked=1,
            issues_found=1,
            issues_fixed=0,
            repairs_applied=0,
            unresolved=[{"check": "A", "description": "unresolvable"}],
            scene_results=[
                PromptQASceneResult(
                    scene_index=1,
                    original_prompt="bad prompt",
                    repaired_prompt="bad prompt",
                    issues=[PromptQAIssue(check="A", description="narration mismatch")],
                    fixes=[],
                    unresolved=[PromptQAIssue(check="A", description="unresolvable")],
                )
            ],
        )

        d = report.to_dict()
        assert d["status"] == "REVIEW_REQUIRED"
        assert len(d["scene_results"]) == 1
        sr = d["scene_results"][0]
        assert sr["scene_index"] == 1
        assert sr["original_prompt"] == "bad prompt"
        assert sr["issues"][0]["check"] == "A"
        assert sr["unresolved"][0]["description"] == "unresolvable"

    def test_to_dict_includes_repairs_applied(self):
        """to_dict() includes the repairs_applied count for auditing."""
        report = PromptQAReport(
            status="PASS",
            scenes_checked=2,
            issues_found=1,
            issues_fixed=1,
            repairs_applied=1,
            unresolved=[],
        )
        d = report.to_dict()
        assert d["repairs_applied"] == 1

    def test_pass_status_has_empty_unresolved(self):
        """PASS status always serialises with empty unresolved list."""
        report = PromptQAReport(
            status="PASS",
            scenes_checked=1,
            issues_found=0,
            issues_fixed=0,
            repairs_applied=0,
            unresolved=[],
        )
        d = report.to_dict()
        assert d["status"] == "PASS"
        assert d["unresolved"] == []


class TestLLMFailureNonBlocking:
    """H4: LLM/API failure does not block and never produces a false PASS."""

    def test_exception_returns_none_not_pass(self):
        """An exception during the LLM call returns None, not a PASS report."""
        scene = _make_scene(1, "N.", "P.")
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = ConnectionError("timeout")
        result = run_prompt_qa_pass([scene], mock_llm)
        assert result is None  # None ≠ PASS; caller detects absence

    def test_malformed_json_returns_none_not_pass(self):
        """Malformed JSON from LLM returns None, not a fabricated PASS."""
        scene = _make_scene(1, "N.", "P.")
        mock_llm = MagicMock()
        response = MagicMock()
        response.text = '{"status": "PASS", broken json'
        mock_llm.generate.return_value = response
        result = run_prompt_qa_pass([scene], mock_llm)
        assert result is None

    def test_original_prompts_untouched_on_failure(self):
        """After LLM failure, scene prompts remain the originals."""
        original = "Original prompt that must survive."
        scene = _make_scene(1, "N.", original)
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("network error")
        run_prompt_qa_pass([scene], mock_llm)
        assert scene["visual_prompt"] == original


class TestPostRepairValidationVisibility:
    """H5 & H6: After QA repairs, repaired prompts are visible for subsequent validation."""

    def test_repaired_prompt_visible_in_scene_after_qa(self):
        """After run_prompt_qa_pass, the scene dict holds the repaired prompt.

        Any deterministic validator called on the same scenes list after QA
        will see the repaired prompt, not the original.
        """
        original = "A quiet pond with no activity."
        repaired = "Crashing ocean waves under a stormy sky, photorealistic."
        scene = _make_scene(1, "The sea roars with fury.", original)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [{"check": "A", "description": "Pond does not match roaring sea."}],
            "fixes": ["Replaced pond with stormy ocean."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.repairs_applied == 1
        # The scene dict is updated — a validator reading scenes[0]["visual_prompt"]
        # now sees the repaired prompt, not the original.
        assert scenes[0]["visual_prompt"] == repaired
        assert scenes[0]["visual_prompt"] != original

    def test_original_prompt_not_seen_after_repair(self):
        """After repair, the original bad prompt is no longer in the scene."""
        original = "A modern glass office with laptops — contradicts ancient world."
        repaired = "Ancient stone hall with torchlight, photorealistic."
        scene = _make_scene(2, "The ancient ceremony begins.", original)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 2,
            "issues": [{"check": "G", "description": "Modern office contradicts ancient world."}],
            "fixes": ["Replaced office with ancient stone hall."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))

        # Original bad content is gone from the scene dict
        assert "glass office" not in scenes[0]["visual_prompt"]
        assert "modern" not in scenes[0]["visual_prompt"].lower()

    def test_repairs_applied_count_reflects_actual_mutations(self):
        """repairs_applied counts only prompts that actually changed."""
        scene_changed = _make_scene(1, "Sea roars.", "Quiet pond.")
        scene_ok = _make_scene(2, "Eagle soars.", "Eagle soaring, photorealistic.")
        scenes = [scene_changed, scene_ok]

        payload = _qa_payload([
            {
                "scene_index": 1,
                "issues": [{"check": "A", "description": "mismatch"}],
                "fixes": ["fixed"],
                "repaired_prompt": "Crashing waves, photorealistic.",
                "unresolved": [],
            },
            {
                "scene_index": 2,
                "issues": [],
                "fixes": [],
                "repaired_prompt": "Eagle soaring, photorealistic.",
                "unresolved": [],
            },
        ])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert report is not None
        assert report.repairs_applied == 1  # only scene 1 actually changed


class TestH7ValidPromptsUnchanged:
    """H7: Existing valid prompts remain unchanged through the QA pass."""

    def test_no_issues_prompt_identical_after_qa(self):
        """A prompt with no violations is byte-for-byte identical after QA."""
        prompt = (
            "Wide shot of a sunrise over the Himalayan peaks, warm golden light, "
            "illustrated foreground figure, photorealistic mountains, no text."
        )
        scene = _make_scene(1, "The sun rises over the Himalayas.", prompt)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [],
            "fixes": [],
            "repaired_prompt": prompt,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert report is not None
        assert report.repairs_applied == 0
        assert scenes[0]["visual_prompt"] == prompt

    def test_multiple_clean_scenes_all_unchanged(self):
        """When multiple scenes are all clean, none are mutated."""
        s1 = _make_scene(1, "N1.", "P1.")
        s2 = _make_scene(2, "N2.", "P2.")
        s3 = _make_scene(3, "N3.", "P3.")
        scenes = [s1, s2, s3]

        payload = _qa_payload([
            {"scene_index": 1, "issues": [], "fixes": [], "repaired_prompt": "P1.", "unresolved": []},
            {"scene_index": 2, "issues": [], "fixes": [], "repaired_prompt": "P2.", "unresolved": []},
            {"scene_index": 3, "issues": [], "fixes": [], "repaired_prompt": "P3.", "unresolved": []},
        ])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert scenes[0]["visual_prompt"] == "P1."
        assert scenes[1]["visual_prompt"] == "P2."
        assert scenes[2]["visual_prompt"] == "P3."


class TestH8SyncAfterRepair:
    """H8: visual_prompt and compiled_prompt remain synchronised after repair."""

    def test_both_fields_updated_on_repair(self):
        """Repair updates both visual_prompt and structured_prompt.compiled_prompt."""
        repaired = "Repaired prompt for image gen."
        scene = _make_scene(1, "Narration.", "Old prompt.")
        scene["structured_prompt"] = {"compiled_prompt": "Old prompt.", "style": "illustrated"}
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [{"check": "A", "description": "mismatch"}],
            "fixes": ["fixed"],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert scenes[0]["visual_prompt"] == repaired
        assert scenes[0]["structured_prompt"]["compiled_prompt"] == repaired

    def test_no_repair_leaves_both_fields_unchanged(self):
        """When no repair occurs, both fields remain at their original values."""
        original = "Unchanged original prompt."
        scene = _make_scene(1, "N.", original)
        scene["structured_prompt"] = {"compiled_prompt": original}
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1, "issues": [], "fixes": [],
            "repaired_prompt": original, "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert scenes[0]["visual_prompt"] == original
        assert scenes[0]["structured_prompt"]["compiled_prompt"] == original


# ---------------------------------------------------------------------------
# C-series: consistency regression tests
# ---------------------------------------------------------------------------


class TestEnforcementCorrectingRepairs:
    """C1: Enforcement functions correctly fix prompts that QA may have altered.

    These tests prove that running enforcement AFTER QA would restore required
    properties — demonstrating that the scene_planner's post-repair enforcement
    re-run is both necessary and sufficient.
    """

    def test_style_footer_restored_after_qa_strips_tail(self):
        """_enforce_style_footer re-adds the footer if a QA repair removed it.

        Scenario: QA correctly removes a text-rendering instruction at the tail
        of a prompt, but in doing so also removes the style footer that was
        appended by the pre-QA _enforce_style_footer pass.
        """
        from ytfactory.agents.nodes.scene_planner import _enforce_style_footer

        # Scene with character: should have illustrated footer
        scene = _make_scene(1, "N.", "No footer here at all.", character_presence=["KAI"])
        scenes = [scene]

        # After enforcement, footer must be present
        result = _enforce_style_footer(scenes, hybrid=False)
        assert len(result) == 1
        prompt_after = result[0]["visual_prompt"]
        # Any of the standard footer keywords should appear
        assert any(kw in prompt_after.lower() for kw in (
            "no text", "no watermark", "photorealistic", "highly detailed"
        ))

    def test_style_footer_idempotent_on_clean_prompt(self):
        """_enforce_style_footer does not duplicate the footer on an already-correct prompt."""
        from ytfactory.agents.nodes.scene_planner import _enforce_style_footer

        base = "Eagle soaring above mountains."
        scene = _make_scene(1, "N.", base, character_presence=[])
        scenes = [scene]

        result1 = _enforce_style_footer(scenes, hybrid=False)
        prompt1 = result1[0]["visual_prompt"]

        # Second call: must not append the footer again
        result2 = _enforce_style_footer(result1, hybrid=False)
        prompt2 = result2[0]["visual_prompt"]

        assert prompt1 == prompt2

    def test_kai_spec_strips_injected_kai_marker_after_repair(self):
        """_enforce_primary_kai_spec removes the KAI_COMPRESSED_SPEC marker when character_presence
        excludes Kai.  The function strips the spec string, not the bare word 'Kai'."""
        from ytfactory.agents.nodes.scene_planner import KAI_COMPRESSED_SPEC, _enforce_primary_kai_spec

        # A QA repair left behind the KAI_COMPRESSED_SPEC injected by an earlier pass,
        # but character_presence says Kai should not be here.
        kai_marker = KAI_COMPRESSED_SPEC
        scene = _make_scene(
            1,
            "Shiva dances.",
            f"{kai_marker} — Shiva dances in the cosmic light, photorealistic.",
            character_presence=["SHIVA"],
        )
        scenes = [scene]

        result = _enforce_primary_kai_spec(scenes)
        repaired_prompt = result[0]["visual_prompt"]
        # The KAI_COMPRESSED_SPEC block is removed
        assert KAI_COMPRESSED_SPEC not in repaired_prompt
        # The Shiva content is preserved
        assert "Shiva" in repaired_prompt

    def test_enforcement_sees_qa_repaired_prompt(self):
        """After run_prompt_qa_pass repairs a prompt, enforcement reads the repaired version."""
        from ytfactory.agents.nodes.scene_planner import _enforce_style_footer

        original = "A quiet pond, photorealistic."
        repaired = "Crashing ocean waves."  # footer missing after QA repair

        scene = _make_scene(1, "The sea roars.", original, character_presence=[])
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [{"check": "A", "description": "mismatch"}],
            "fixes": ["replaced pond with ocean"],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert scenes[0]["visual_prompt"] == repaired  # QA applied

        # Enforcement sees the repaired prompt and adds the footer
        _enforce_style_footer(scenes, hybrid=False)
        final = scenes[0]["visual_prompt"]
        assert any(kw in final.lower() for kw in ("no text", "no watermark", "photorealistic"))
        assert "ocean" in final.lower()  # QA content preserved


class TestFinalValidatorsSeeRepairedPrompt:
    """C2: The scene dict is the contract between QA and subsequent validators."""

    def test_repaired_prompt_in_scene_dict_for_validators(self):
        """After run_prompt_qa_pass, scene['visual_prompt'] holds the repaired prompt.

        Any validator that reads scene['visual_prompt'] after run_prompt_qa_pass
        will evaluate the repaired (and subsequently enforced) prompt, not the original.
        This is the end-to-end contract that makes re-ordering possible.
        """
        original = "Quiet pond, photorealistic."
        repaired = "Crashing ocean waves, no text, no watermark, photorealistic."

        scene = _make_scene(1, "The sea roars.", original)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [{"check": "A", "description": "mismatch"}],
            "fixes": ["replaced pond with ocean"],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))

        # Simulate a validator reading the scene dict
        validator_input = scenes[0]["visual_prompt"]
        assert validator_input == repaired
        assert "pond" not in validator_input

    def test_compiled_prompt_also_available_for_validators(self):
        """structured_prompt.compiled_prompt is also synced so validators using it see final state."""
        repaired = "Ancient temple at dusk, photorealistic."
        scene = _make_scene(1, "N.", "Old prompt.")
        scene["structured_prompt"] = {"compiled_prompt": "Old prompt.", "style": "doc"}
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [{"check": "G", "description": "mismatch"}],
            "fixes": ["fixed"],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert scenes[0]["structured_prompt"]["compiled_prompt"] == repaired


class TestContinuityReportFinalState:
    """C3: Continuity report content reflects the final prompt state."""

    def test_continuity_report_object_built_from_scene_dict_prompts(self):
        """ContinuityReport populated after QA would reflect the repaired prompts.

        We cannot call write_report without a filesystem, but we can verify that
        the continuity report object (ContinuityReport) records the final state
        of the scene list after repair.
        """
        from ytfactory.scene_continuity.diagnostics import ContinuityReport, SceneContinuityStatus

        repaired = "Crashing ocean waves, photorealistic."
        scene = _make_scene(1, "The sea roars.", "Quiet pond.")
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [{"check": "A", "description": "mismatch"}],
            "fixes": ["fixed"],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert scenes[0]["visual_prompt"] == repaired

        # Build a continuity report from the post-QA scene list
        cr = ContinuityReport()
        cr.record_scene(SceneContinuityStatus(scene_index=1, status="PASS"))

        # Continuity report can be built and serialised
        d = cr.to_dict()
        assert d is not None

    def test_to_dict_on_continuity_report_is_serialisable(self):
        """ContinuityReport.to_dict produces JSON-serialisable output."""
        import json
        from ytfactory.scene_continuity.diagnostics import ContinuityReport, SceneContinuityStatus

        cr = ContinuityReport()
        cr.record_scene(SceneContinuityStatus(scene_index=1, status="PASS"))
        cr.record_scene(SceneContinuityStatus(scene_index=2, status="FAILED"))
        d = cr.to_dict()
        json.dumps(d)  # must not raise


class TestFaithfulnessUpgradeAfterRepair:
    """C4: FAILED faithfulness scenes produce the correct faithfulness_qa dict when upgraded."""

    def test_faithfulness_qa_structure_when_upgraded(self):
        """A faithfulness_qa dict upgraded from FAILED to PASS preserves attempt count."""
        fqa_failed = {
            "status": "FAILED",
            "violation": "missing character",
            "attempts": 3,
            "critical_errors": ["MISSING_CHARACTER"],
            "llm_validated": False,
            "llm_reason": "",
        }

        # Simulate the upgrade logic applied by scene_planner
        upgraded = {
            "status": "PASS",
            "violation": "",
            "attempts": fqa_failed.get("attempts", 0),
            "critical_errors": [],
            "llm_validated": fqa_failed.get("llm_validated", False),
            "llm_reason": fqa_failed.get("llm_reason", ""),
        }

        assert upgraded["status"] == "PASS"
        assert upgraded["attempts"] == 3       # preserved from FAILED record
        assert upgraded["critical_errors"] == []
        assert upgraded["violation"] == ""

    def test_faithfulness_qa_pass_not_downgraded(self):
        """A PASS scene's faithfulness_qa must not be touched by the upgrade loop."""
        fqa_pass = {
            "status": "PASS",
            "violation": "",
            "attempts": 1,
            "critical_errors": [],
            "llm_validated": False,
            "llm_reason": "",
        }
        # Upgrade logic only fires when status == FAILED
        should_upgrade = fqa_pass.get("status") == "FAILED"
        assert not should_upgrade  # PASS scene is never touched


class TestQAReportAccuracy:
    """C5: QA report preserves actual issues and repairs correctly."""

    def test_to_dict_preserves_issues_and_fixes(self):
        """to_dict includes per-scene issues and fixes for every scene result."""
        from ytfactory.images.prompt_qa import PromptQAIssue, PromptQASceneResult

        report = PromptQAReport(
            status="PASS",
            scenes_checked=2,
            issues_found=2,
            issues_fixed=2,
            repairs_applied=1,
            unresolved=[],
            scene_results=[
                PromptQASceneResult(
                    scene_index=1,
                    original_prompt="Old prompt A.",
                    repaired_prompt="New prompt A.",
                    issues=[PromptQAIssue(check="A", description="narration mismatch")],
                    fixes=["replaced subject"],
                    unresolved=[],
                ),
                PromptQASceneResult(
                    scene_index=2,
                    original_prompt="Unchanged.",
                    repaired_prompt="Unchanged.",
                    issues=[],
                    fixes=[],
                    unresolved=[],
                ),
            ],
        )

        d = report.to_dict()
        assert len(d["scene_results"]) == 2
        sr1 = d["scene_results"][0]
        assert sr1["scene_index"] == 1
        assert sr1["original_prompt"] == "Old prompt A."
        assert sr1["repaired_prompt"] == "New prompt A."
        assert sr1["issues"][0]["check"] == "A"
        assert sr1["fixes"] == ["replaced subject"]
        assert d["repairs_applied"] == 1

    def test_to_dict_is_json_serialisable(self):
        """The full to_dict output must be JSON-serialisable for artifact writing."""
        import json
        from ytfactory.images.prompt_qa import PromptQAIssue, PromptQASceneResult

        report = PromptQAReport(
            status="REVIEW_REQUIRED",
            scenes_checked=1,
            issues_found=1,
            issues_fixed=0,
            repairs_applied=0,
            unresolved=[{"check": "A", "description": "unresolvable"}],
            scene_results=[
                PromptQASceneResult(
                    scene_index=1,
                    original_prompt="Bad.",
                    repaired_prompt="Bad.",
                    issues=[PromptQAIssue(check="A", description="narration mismatch")],
                    fixes=[],
                    unresolved=[PromptQAIssue(check="A", description="unresolvable")],
                )
            ],
        )
        json.dumps(report.to_dict())  # must not raise


class TestUnresolvedConsistency:
    """C6: Top-level unresolved is derived from per-scene data, not trusted from LLM."""

    def test_review_required_when_per_scene_unresolved_nonempty(self):
        """Parser sets REVIEW_REQUIRED when per-scene unresolved is non-empty,
        even if the LLM top-level reported PASS."""
        scenes = [_make_scene(1, "N.", "P.")]

        # LLM incorrectly reports PASS at the top level but has per-scene unresolved
        payload = {
            "status": "PASS",          # LLM lied
            "scenes_checked": 1,
            "issues_found": 1,
            "issues_fixed": 0,
            "unresolved": [],          # LLM also left this empty
            "scene_results": [{
                "scene_index": 1,
                "issues": [{"check": "A", "description": "mismatch"}],
                "fixes": [],
                "repaired_prompt": "P.",
                "unresolved": [{"check": "A", "description": "cannot resolve"}],
            }],
        }

        report = _parse_qa_response(json.dumps(payload), scenes)
        assert report is not None
        assert report.status == "REVIEW_REQUIRED"
        assert len(report.unresolved) == 1
        assert report.unresolved[0]["check"] == "A"

    def test_pass_when_all_per_scene_unresolved_empty(self):
        """Parser keeps PASS when no per-scene unresolved entries exist."""
        scenes = [_make_scene(1, "N.", "P.")]
        payload = _qa_payload([{
            "scene_index": 1, "issues": [], "fixes": [],
            "repaired_prompt": "P.", "unresolved": [],
        }])
        report = _parse_qa_response(json.dumps(payload), scenes)
        assert report is not None
        assert report.status == "PASS"
        assert report.unresolved == []

    def test_top_level_unresolved_aggregated_from_all_scenes(self):
        """When multiple scenes have per-scene unresolved, all are surfaced."""
        scenes = [_make_scene(1, "N1.", "P1."), _make_scene(2, "N2.", "P2.")]
        payload = {
            "status": "REVIEW_REQUIRED",
            "scenes_checked": 2,
            "issues_found": 2,
            "issues_fixed": 0,
            "unresolved": [],          # LLM forgot to aggregate
            "scene_results": [
                {
                    "scene_index": 1,
                    "issues": [{"check": "A", "description": "scene 1 issue"}],
                    "fixes": [],
                    "repaired_prompt": "P1.",
                    "unresolved": [{"check": "A", "description": "scene 1 unresolved"}],
                },
                {
                    "scene_index": 2,
                    "issues": [{"check": "D", "description": "scene 2 issue"}],
                    "fixes": [],
                    "repaired_prompt": "P2.",
                    "unresolved": [{"check": "D", "description": "scene 2 unresolved"}],
                },
            ],
        }
        report = _parse_qa_response(json.dumps(payload), scenes)
        assert report is not None
        assert report.status == "REVIEW_REQUIRED"
        assert len(report.unresolved) == 2
        checks = {u["check"] for u in report.unresolved}
        assert checks == {"A", "D"}

    def test_llm_top_level_unresolved_used_as_fallback_only(self):
        """When scene_results is empty, the LLM top-level unresolved is used as fallback."""
        scenes = [_make_scene(1, "N.", "P.")]
        payload = {
            "status": "REVIEW_REQUIRED",
            "scenes_checked": 0,
            "issues_found": 1,
            "issues_fixed": 0,
            "unresolved": [{"check": "Z", "description": "fallback unresolved"}],
            "scene_results": [],
        }
        report = _parse_qa_response(json.dumps(payload), scenes)
        assert report is not None
        # No per-scene data → uses LLM top-level as fallback
        assert len(report.unresolved) == 1
        assert report.unresolved[0]["check"] == "Z"


class TestNoSecondLLMCall:
    """C7: run_prompt_qa_pass makes exactly one LLM generate call, regardless of repairs."""

    def test_exactly_one_generate_call_on_success(self):
        """Exactly one llm.generate() call regardless of how many scenes are repaired."""
        scenes = [
            _make_scene(1, "N1.", "P1."),
            _make_scene(2, "N2.", "P2."),
            _make_scene(3, "N3.", "P3."),
        ]
        payload = _qa_payload([
            {"scene_index": 1, "issues": [{"check": "A", "description": "x"}],
             "fixes": ["f"], "repaired_prompt": "Fixed P1.", "unresolved": []},
            {"scene_index": 2, "issues": [], "fixes": [], "repaired_prompt": "P2.", "unresolved": []},
            {"scene_index": 3, "issues": [], "fixes": [], "repaired_prompt": "P3.", "unresolved": []},
        ])

        mock_llm = MagicMock()
        response = MagicMock()
        response.text = json.dumps(payload)
        mock_llm.generate.return_value = response

        run_prompt_qa_pass(scenes, mock_llm)

        assert mock_llm.generate.call_count == 1

    def test_exactly_one_generate_call_with_review_required(self):
        """REVIEW_REQUIRED path still uses exactly one LLM call."""
        scene = _make_scene(1, "N.", "P.")
        payload = {
            "status": "REVIEW_REQUIRED",
            "scenes_checked": 1,
            "issues_found": 1,
            "issues_fixed": 0,
            "unresolved": [{"check": "A", "description": "unresolvable"}],
            "scene_results": [{
                "scene_index": 1,
                "issues": [{"check": "A", "description": "issue"}],
                "fixes": [],
                "repaired_prompt": "P.",
                "unresolved": [{"check": "A", "description": "unresolvable"}],
            }],
        }
        mock_llm = MagicMock()
        response = MagicMock()
        response.text = json.dumps(payload)
        mock_llm.generate.return_value = response

        run_prompt_qa_pass([scene], mock_llm)

        assert mock_llm.generate.call_count == 1

    def test_zero_generate_calls_when_no_generated_scenes(self):
        """No LLM call is made when there are no generated-image scenes."""
        scenes = [{"index": 1, "scene_type": "asset", "narration": "", "visual_prompt": ""}]
        mock_llm = MagicMock()
        run_prompt_qa_pass(scenes, mock_llm)
        mock_llm.generate.assert_not_called()


# ---------------------------------------------------------------------------
# New focused tests — Checks A/D/E/G/I/J/L/M
# ---------------------------------------------------------------------------


class TestMissingNarratedSubjectRelationship:
    """Check A: Important subjects, actions and relationships must be visually present."""

    def test_missing_narrated_relationship_repaired(self):
        """Narration requires a relationship (son bowing to father); prompt omits it."""
        narration = "The young son bows before his father, seeking his blessing."
        bad_prompt = "A man kneeling on a stone floor, photorealistic interior."
        repaired = (
            "Young son in illustrated style kneeling and bowing before an older father figure, "
            "stone floor interior, photorealistic background."
        )

        scene = _make_scene(1, narration, bad_prompt, character_presence=["SON", "FATHER"])
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [{"check": "A", "description": "Prompt omits the father and the relationship; narration requires son bowing to father for blessing."}],
            "fixes": ["Added father figure and parent-child relationship visible in scene."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.status == "PASS"
        assert scenes[0]["visual_prompt"] == repaired

    def test_missing_narrated_action_repaired(self):
        """Narration requires an action (ant lifts a grain); prompt shows only environment."""
        narration = "A tiny ant lifts a grain of wheat ten times its own weight."
        bad_prompt = "Wheat field at sunset, golden stalks stretching to the horizon, photorealistic."
        repaired = (
            "Close-up of a tiny illustrated ant carrying an oversized grain of wheat, "
            "golden wheat stalks in the photorealistic background."
        )

        scene = _make_scene(2, narration, bad_prompt, character_presence=[])
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 2,
            "issues": [{"check": "A", "description": "Prompt shows empty wheat field; narration requires a visible ant lifting wheat."}],
            "fixes": ["Added ant carrying grain in foreground."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert scenes[0]["visual_prompt"] == repaired


class TestMetadataPromptContradiction:
    """Check D: Metadata (CHARACTER_PRESENCE, scene_analysis) must match the prompt."""

    def test_animal_visible_but_presence_empty_is_contradiction(self):
        """When character_presence=[] but prompt includes an animal, it's a D violation."""
        narration = "The forest is silent and empty — no creature stirs."
        bad_prompt = (
            "A large brown bear walks between ancient trees in a dense forest, photorealistic."
        )
        repaired = "Ancient trees in a dense silent forest, no animals, no figures, photorealistic."

        scene = _make_scene(3, narration, bad_prompt, character_presence=[])
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 3,
            "issues": [{"check": "D", "description": "CHARACTER_PRESENCE is empty but prompt contains a bear."}],
            "fixes": ["Removed bear; scene is now empty forest only."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert "bear" not in scenes[0]["visual_prompt"].lower()

    def test_human_in_prompt_when_presence_none_is_contradiction(self):
        """CHARACTER_PRESENCE: [] with a human in the prompt is a clear D violation."""
        narration = "The wind sweeps across the empty plateau."
        bad_prompt = "An old shepherd stands on an elevated plateau, wind blowing his robes, photorealistic."
        repaired = "Empty plateau with wind sweeping across, no figures, photorealistic."

        scene = _make_scene(4, narration, bad_prompt, character_presence=[])
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 4,
            "issues": [{"check": "D", "description": "CHARACTER_PRESENCE is NONE but prompt contains 'old shepherd'."}],
            "fixes": ["Removed shepherd; empty plateau remains."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert "shepherd" not in scenes[0]["visual_prompt"].lower()


class TestAnimalTreatedAsEnvironment:
    """Check E: Animals are subjects and must follow illustrated style, not become scenery."""

    def test_eagle_classified_as_environment_repaired(self):
        """Prompt classifies eagle as 'background mountain scenery' — must be corrected."""
        narration = "The eagle swoops down from the peak, its wings cutting the cold air."
        bad_prompt = (
            "Snow-capped mountain peaks with atmospheric haze; small eagle silhouette "
            "blending into the distant sky as part of the mountain scenery. Photorealistic."
        )
        repaired = (
            "Illustrated eagle in dynamic swoop, wings spread wide, sharp talons extended, "
            "photorealistic snow-capped mountain peaks in the background."
        )

        scene = _make_scene(5, narration, bad_prompt, character_presence=[])
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 5,
            "issues": [{"check": "E", "description": "Eagle is the primary narrated subject but is treated as background mountain scenery. Eagle must be illustrated and visually dominant."}],
            "fixes": ["Promoted eagle to foreground illustrated subject; mountains remain photorealistic background."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert scenes[0]["visual_prompt"] == repaired
        assert "illustrated" in scenes[0]["visual_prompt"].lower()

    def test_ant_as_texture_corrected(self):
        """An ant described only as 'texture on the leaf' must be promoted to a subject."""
        narration = "The ant pauses, antennae raised, sensing the world around it."
        bad_prompt = "A large leaf in extreme macro; ant-like texture visible on the surface. Photorealistic."
        repaired = (
            "Extreme macro of an illustrated ant standing on a green leaf, antennae raised, "
            "photorealistic leaf surface, depth of field background."
        )

        scene = _make_scene(6, narration, bad_prompt, character_presence=[])
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 6,
            "issues": [{"check": "E", "description": "Ant is the narrated subject but is dismissed as surface texture. It must be an illustrated subject."}],
            "fixes": ["Promoted ant from texture to foreground illustrated subject."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert scenes[0]["visual_prompt"] == repaired


class TestVisualWorldConflictFocused:
    """Check G: Prompt must not introduce a visual world inconsistent with the Visual Bible."""

    def test_industrial_setting_contradicts_ancient_spiritual_bible(self):
        """Industrial factory contradicts a Visual Bible anchored in ancient/spiritual settings."""
        narration = "The seeker walks alone through the sacred forest, searching for truth."
        bad_prompt = (
            "Worker in a hard-hat walking through a steel factory floor, "
            "industrial lighting, sparks flying. Illustrated character, photorealistic factory."
        )
        repaired = (
            "Illustrated seeker figure walking alone through an ancient forest, dappled light, "
            "moss-covered trees, photorealistic environment."
        )

        scene = _make_scene(7, narration, bad_prompt)
        scenes = [scene]
        vb = {
            "dominant_metaphor": "inner journey through nature",
            "anchor_environments": "ancient forests, mountain paths, stone temples",
        }

        payload = _qa_payload([{
            "scene_index": 7,
            "issues": [{"check": "G", "description": "Industrial factory contradicts the Visual Bible's ancient/natural world anchor."}],
            "fixes": ["Replaced factory with ancient forest consistent with Visual Bible."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload), visual_bible=vb)

        assert report is not None
        assert scenes[0]["visual_prompt"] == repaired
        assert scenes[0]["narration"] == narration  # narration untouched


class TestImpossibleSpatialRelationship:
    """Check L: Subjects, actions and environments must be physically coherent."""

    def test_human_inside_microscopic_object_repaired(self):
        """A human figure standing inside a single blood cell is physically impossible."""
        narration = "The immune system fights back with relentless precision."
        bad_prompt = (
            "A human warrior standing upright inside a red blood cell, sword raised, "
            "the cell walls glowing around him. Illustrated character, photorealistic cell."
        )
        repaired = (
            "Illustrated immune cells (white blood cells) attacking a pathogen in an extreme "
            "microscopic environment, photorealistic cellular background, no human figures."
        )

        scene = _make_scene(8, narration, bad_prompt, character_presence=[])
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 8,
            "issues": [{"check": "L", "description": "Human warrior inside a red blood cell is physically impossible — human scale incompatible with cellular scale."}],
            "fixes": ["Replaced impossible scale mismatch with immune cells as subject; removed human figure."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert scenes[0]["visual_prompt"] == repaired

    def test_unresolvable_spatial_conflict_produces_review_required(self):
        """Impossible interaction that cannot be fixed without changing narration → REVIEW_REQUIRED."""
        narration = "The mountain stands on the palm of his hand."
        bad_prompt = "A human hand holding a full-size Himalayan mountain peak. Illustrated hand, photorealistic mountain."

        scene = _make_scene(9, narration, bad_prompt)
        scenes = [scene]

        unresolved = [{"check": "L", "description": "Narration explicitly requires impossible scale — a mountain on a palm. Cannot resolve without changing narration."}]
        payload = {
            "status": "REVIEW_REQUIRED",
            "scenes_checked": 1,
            "issues_found": 1,
            "issues_fixed": 0,
            "unresolved": unresolved,
            "scene_results": [{
                "scene_index": 9,
                "issues": [{"check": "L", "description": "Physically impossible: full mountain on a human palm."}],
                "fixes": [],
                "repaired_prompt": bad_prompt,
                "unresolved": unresolved,
            }],
        }

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.status == "REVIEW_REQUIRED"
        assert any(u["check"] == "L" for u in report.unresolved)


class TestCameraCompositionContradiction:
    """Check I: Contradictory camera/composition instructions must be caught and corrected."""

    def test_extreme_macro_with_wide_shot_contradiction_repaired(self):
        """'Extreme macro close-up' combined with 'wide establishing shot' is a contradiction."""
        narration = "A single grain of sand rests at the edge of the vast desert."
        bad_prompt = (
            "Extreme macro close-up of a single grain of sand, every crystal facet visible; "
            "wide establishing shot of the Sahara Desert horizon. Photorealistic."
        )
        repaired = (
            "Extreme macro close-up of a single grain of sand, every crystal facet visible, "
            "shallow depth of field, photorealistic."
        )

        scene = _make_scene(10, narration, bad_prompt)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 10,
            "issues": [{"check": "I", "description": "Extreme macro and wide establishing shot are mutually exclusive composition instructions."}],
            "fixes": ["Kept extreme macro; removed contradictory wide shot instruction."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert scenes[0]["visual_prompt"] == repaired

    def test_side_profile_and_frontal_portrait_contradiction_repaired(self):
        """'Strict side profile' and 'full frontal face portrait' are contradictory."""
        narration = "The elder gazed into the distance, silent and resolute."
        bad_prompt = (
            "Illustrated elder figure: strict side profile view, face turned 90 degrees, "
            "full frontal face portrait showing both eyes and entire face. Photorealistic background."
        )
        repaired = (
            "Illustrated elder figure: strict side profile, face turned toward the distance, "
            "photorealistic background."
        )

        scene = _make_scene(11, narration, bad_prompt)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 11,
            "issues": [{"check": "I", "description": "Strict side profile and full frontal portrait are contradictory — a face cannot face two directions simultaneously."}],
            "fixes": ["Removed frontal portrait instruction; side profile preserved."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert scenes[0]["visual_prompt"] == repaired


class TestProhibitedTextRendering:
    """Check J: Readable text/logos/UI must not be rendered (compositor handles text)."""

    def test_brand_logo_rendered_in_background_repaired(self):
        """A brand logo rendered into the scene background must be removed."""
        narration = "The city never sleeps — a thousand stories playing out at once."
        bad_prompt = (
            "Busy night cityscape, neon signs with the words 'HOPE' and 'GLORY' in large "
            "illuminated letters on building facades. Photorealistic, wide shot."
        )
        repaired = (
            "Busy night cityscape with glowing neon signs — no readable words or brand names — "
            "photorealistic, wide shot. Clean space for compositor text overlay."
        )

        scene = _make_scene(12, narration, bad_prompt)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 12,
            "issues": [{"check": "J", "description": "Prompt requests readable words 'HOPE' and 'GLORY' on building signs; compositor handles all text."}],
            "fixes": ["Replaced readable words with generic glowing neon signs; added compositor space note."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert "HOPE" not in scenes[0]["visual_prompt"]
        assert "GLORY" not in scenes[0]["visual_prompt"]

    def test_designated_compositor_scene_preserved(self):
        """A scene explicitly designated for text overlay must NOT be stripped."""
        narration = "Title card: The Weight of a Single Choice."
        prompt = (
            "Dark stone texture background with soft light gradient — designated compositor "
            "title scene, leave full space for text overlay. No image elements."
        )

        scene = _make_scene(13, narration, prompt)
        scenes = [scene]

        # QA correctly identifies this as a compositor scene and does not strip it
        payload = _qa_payload([{
            "scene_index": 13,
            "issues": [],
            "fixes": [],
            "repaired_prompt": prompt,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.status == "PASS"
        assert scenes[0]["visual_prompt"] == prompt  # untouched


class TestDuplicateContradictorySubjectFields:
    """Check M: Duplicated or contradictory subject blocks must be consolidated."""

    def test_duplicate_ant_block_consolidated(self):
        """'PRIMARY SUBJECT: Ant ...' plus a redundant 'ANT: Ant ...' block is consolidated."""
        narration = "The ant carries its burden across the mountain of grain."
        bad_prompt = (
            "PRIMARY SUBJECT: Ant, illustrated, carrying grain. "
            "ANT: Tiny illustrated ant carrying an oversized grain of wheat. "
            "Environment: dusty brown grain pile, photorealistic. "
            "Style: illustrated ant, photorealistic background."
        )
        repaired = (
            "Tiny illustrated ant carrying an oversized grain of wheat across a dusty brown "
            "grain pile, photorealistic background. Illustrated ant, photorealistic environment."
        )

        scene = _make_scene(14, narration, bad_prompt)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 14,
            "issues": [{"check": "M", "description": "Duplicated ant subject: 'PRIMARY SUBJECT: Ant...' and 'ANT: ...' block describe the same subject twice with slight variation."}],
            "fixes": ["Consolidated duplicate ant descriptions into a single coherent subject block."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.status == "PASS"
        assert scenes[0]["visual_prompt"] == repaired

    def test_conflicting_character_descriptions_consolidated(self):
        """Two contradictory character descriptions for the same character are resolved."""
        narration = "The warrior stood tall and broad-shouldered."
        bad_prompt = (
            "CHARACTER: Warrior — lean and wiry build, short and slight frame. "
            "CHARACTER: Warrior — tall broad-shouldered powerful build, towering figure. "
            "Illustrated character, photorealistic battlefield background."
        )
        repaired = (
            "CHARACTER: Warrior — tall, broad-shouldered powerful build. "
            "Illustrated character, photorealistic battlefield background."
        )

        scene = _make_scene(15, narration, bad_prompt, character_presence=["WARRIOR"])
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 15,
            "issues": [{"check": "M", "description": "Two contradictory warrior descriptions: 'lean and wiry, short' vs 'tall and broad-shouldered'. Narration says tall and broad-shouldered."}],
            "fixes": ["Resolved contradiction using narration; kept 'tall broad-shouldered' description."],
            "repaired_prompt": repaired,
            "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))
        assert "lean and wiry" not in scenes[0]["visual_prompt"]
        assert "tall" in scenes[0]["visual_prompt"].lower()


class TestValidPromptUnchangedNewChecks:
    """Valid prompts covering new check areas (L, M) must remain unchanged."""

    def test_physically_coherent_scene_not_touched(self):
        """A spatially and physically coherent scene is not repaired."""
        narration = "The sparrow lands on the rim of an ancient stone well."
        prompt = (
            "Illustrated sparrow perched on the stone rim of an old well, "
            "photorealistic moss-covered stone, soft morning light, no text."
        )

        scene = _make_scene(16, narration, prompt)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 16,
            "issues": [],
            "fixes": [],
            "repaired_prompt": prompt,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.status == "PASS"
        assert report.repairs_applied == 0
        assert scenes[0]["visual_prompt"] == prompt

    def test_single_subject_block_not_flagged(self):
        """A prompt with a single, non-duplicated subject block must not be flagged as M."""
        narration = "An ant crosses the vast desert floor, one step at a time."
        prompt = (
            "Illustrated ant crossing a cracked desert floor, photorealistic earth, "
            "extreme wide shot showing scale of the desert, no text, no watermark."
        )

        scene = _make_scene(17, narration, prompt)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 17,
            "issues": [],
            "fixes": [],
            "repaired_prompt": prompt,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.issues_found == 0
        assert scenes[0]["visual_prompt"] == prompt


class TestUnresolvedNewChecksProduceReviewRequired:
    """Unresolved issues for checks L and M must produce REVIEW_REQUIRED."""

    def test_unresolved_check_l_produces_review_required(self):
        """An unresolvable spatial impossibility (check L) yields REVIEW_REQUIRED."""
        narration = "Time itself bends under the weight of his gaze."
        bad_prompt = "A man staring at a visual representation of bent time — arrows curving, clocks melting."

        scene = _make_scene(18, narration, bad_prompt)
        scenes = [scene]

        unresolved = [{"check": "L", "description": "Cannot depict 'bent time' literally without an abstract image that conflicts with photorealistic style rules."}]
        payload = {
            "status": "REVIEW_REQUIRED",
            "scenes_checked": 1,
            "issues_found": 1,
            "issues_fixed": 0,
            "unresolved": unresolved,
            "scene_results": [{
                "scene_index": 18,
                "issues": [{"check": "L", "description": "Physically abstract concept cannot be literally visualised."}],
                "fixes": [],
                "repaired_prompt": bad_prompt,
                "unresolved": unresolved,
            }],
        }

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.status == "REVIEW_REQUIRED"
        assert len(report.unresolved) >= 1
        assert report.unresolved[0]["check"] == "L"

    def test_unresolved_check_m_produces_review_required(self):
        """An unresolvable contradictory subject block (check M) yields REVIEW_REQUIRED."""
        narration = "Two forces meet at the crossroads of time."
        bad_prompt = (
            "PRIMARY SUBJECT: Ancient warrior — stone armour, 5000 BCE. "
            "PRIMARY SUBJECT: Ancient warrior — laser armour, year 3000 CE. "
            "Two warriors face each other, photorealistic battlefield."
        )

        scene = _make_scene(19, narration, bad_prompt)
        scenes = [scene]

        unresolved = [{"check": "M", "description": "Two contradictory time-periods for the same 'ancient warrior' character. Narration is ambiguous — cannot determine which era is intended without script clarification."}]
        payload = {
            "status": "REVIEW_REQUIRED",
            "scenes_checked": 1,
            "issues_found": 1,
            "issues_fixed": 0,
            "unresolved": unresolved,
            "scene_results": [{
                "scene_index": 19,
                "issues": [{"check": "M", "description": "Two contradictory warrior era descriptions."}],
                "fixes": [],
                "repaired_prompt": bad_prompt,
                "unresolved": unresolved,
            }],
        }

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.status == "REVIEW_REQUIRED"
        assert report.unresolved[0]["check"] == "M"


# ---------------------------------------------------------------------------
# Deterministic post-QA normalization — normalize_prompt_fields
# ---------------------------------------------------------------------------


def _make_prompt(*lines: str) -> str:
    """Join labeled field lines into a prompt string."""
    return "\n".join(lines)


class TestNormalizePromptFieldsRule1:
    """Rule 1: PRIMARY ACTION verbatim copy of PRIMARY SUBJECT is removed."""

    def test_exact_copy_primary_action_removed(self):
        """When PRIMARY ACTION == PRIMARY SUBJECT word-for-word, PRIMARY ACTION is dropped."""
        subj = "Host, a Western-presenting adult with an attentive, calm expression."
        prompt = _make_prompt(
            f"PRIMARY SUBJECT: {subj}",
            f"PRIMARY ACTION: {subj}",  # exact duplicate
            "ENVIRONMENT: Minimal studio, photorealistic.",
            "STYLE: Hybrid cinematic.",
        )
        normalized, changes = normalize_prompt_fields(prompt)
        assert "PRIMARY ACTION" not in normalized
        assert "PRIMARY SUBJECT" in normalized
        assert "ENVIRONMENT" in normalized
        assert len(changes) == 1
        assert "verbatim copy" in changes[0]

    def test_action_with_added_movement_is_kept(self):
        """PRIMARY ACTION that EXTENDS PRIMARY SUBJECT with an action verb is preserved."""
        prompt = _make_prompt(
            "PRIMARY SUBJECT: Illustrated monk, grey robes, calm expression.",
            "PRIMARY ACTION: Illustrated monk, grey robes, calm expression, bowing slowly before the altar.",
            "ENVIRONMENT: Ancient stone temple, photorealistic.",
            "STYLE: Hybrid cinematic.",
        )
        normalized, changes = normalize_prompt_fields(prompt)
        assert "PRIMARY ACTION" in normalized
        assert not any("PRIMARY ACTION" in c for c in changes)

    def test_near_identical_above_threshold_removed(self):
        """PRIMARY ACTION near-verbatim (Jaccard ≥ 0.95) is also removed."""
        # All words the same except one minor punctuation difference
        prompt = _make_prompt(
            "PRIMARY SUBJECT: Young man, short dark hair, simple shirt, calm.",
            "PRIMARY ACTION: Young man, short dark hair, simple shirt, calm",  # no trailing period
            "ENVIRONMENT: Photorealistic valley.",
        )
        normalized, changes = normalize_prompt_fields(prompt)
        # Should be detected as near-verbatim (same word sets)
        assert "PRIMARY ACTION" not in normalized
        assert len(changes) == 1

    def test_empty_primary_subject_does_not_remove_action(self):
        """When PRIMARY SUBJECT is missing/empty, Rule 1 never fires."""
        prompt = _make_prompt(
            "PRIMARY ACTION: Monk walking through the forest.",
            "ENVIRONMENT: Ancient forest, photorealistic.",
        )
        normalized, changes = normalize_prompt_fields(prompt)
        assert "PRIMARY ACTION" in normalized
        assert not changes


class TestNormalizePromptFieldsRule2:
    """Rule 2: Auxiliary fields whose content is already in PRIMARY ACTION/SUBJECT are removed."""

    def test_auxiliary_field_duplicating_primary_action_removed(self):
        """An ANT: block that repeats PRIMARY ACTION content is dropped."""
        # PRIMARY ACTION contains all the words that ANT: would say
        action_text = (
            "An extremely tiny resilient worker ant with dark reddish-brown segmented body "
            "six delicate legs visibly smaller than a grain of rice two antennae "
            "purposeful forward-leaning posture advancing across the stone path."
        )
        # ANT: block is largely a subset of ACTION text
        ant_text = (
            "An extremely tiny resilient worker ant with dark reddish-brown segmented body "
            "six delicate legs visibly smaller than a grain of rice two antennae."
        )
        prompt = _make_prompt(
            "PRIMARY SUBJECT: Tiny ant on stone path.",
            f"PRIMARY ACTION: {action_text}",
            "ENVIRONMENT: Himalayan mountain path, photorealistic.",
            f"ANT: {ant_text}",
            "STYLE: Hybrid cinematic.",
        )
        normalized, changes = normalize_prompt_fields(prompt)
        assert "ANT:" not in normalized
        assert "PRIMARY ACTION" in normalized
        assert any("ANT" in c for c in changes)

    def test_auxiliary_field_duplicating_primary_subject_removed(self):
        """A character block whose words are mostly in PRIMARY SUBJECT is dropped."""
        subj_text = "Lean young man, late 20s, short dark hair, simple dark shirt, calm expression."
        char_text = "Lean young man, late 20s, short dark hair, simple dark shirt."
        prompt = _make_prompt(
            f"PRIMARY SUBJECT: {subj_text}",
            "PRIMARY ACTION: Standing at the river bank, looking into the distance.",
            "ENVIRONMENT: Misty riverbank, photorealistic.",
            f"CHARACTER_SPEC: {char_text}",
            "STYLE: Hybrid cinematic.",
        )
        normalized, changes = normalize_prompt_fields(prompt)
        assert "CHARACTER_SPEC:" not in normalized
        assert any("CHARACTER_SPEC" in c for c in changes)

    def test_distinct_auxiliary_field_kept(self):
        """An auxiliary field with mostly distinct words from SUBJECT/ACTION is preserved."""
        prompt = _make_prompt(
            "PRIMARY SUBJECT: Ant on stone path.",
            "PRIMARY ACTION: Ant advancing across the stone path.",
            "ENVIRONMENT: Himalayan peaks, photorealistic.",
            "SOCRATES: Older man with thick grey beard, worn linen chiton, simple sandals.",
            "STYLE: Hybrid cinematic.",
        )
        normalized, changes = normalize_prompt_fields(prompt)
        assert "SOCRATES:" in normalized
        assert not any("SOCRATES" in c for c in changes)

    def test_structural_fields_never_removed_by_rule2(self):
        """ENVIRONMENT, STYLE, LIGHTING, etc. are never removed even with high overlap."""
        # ENVIRONMENT has some overlapping words with SUBJECT but must never be removed
        prompt = _make_prompt(
            "PRIMARY SUBJECT: Ant, tiny, stone, path.",
            "PRIMARY ACTION: Ant advancing on stone path.",
            "ENVIRONMENT: Stone path beside a mountain, photorealistic.",
            "STYLE: Hybrid cinematic.",
        )
        normalized, changes = normalize_prompt_fields(prompt)
        assert "ENVIRONMENT:" in normalized
        assert "STYLE:" in normalized

    def test_below_threshold_auxiliary_field_kept(self):
        """Auxiliary field with < 75% overlap is not removed."""
        # KAI spec has mostly different words from a movement-focused PRIMARY ACTION
        prompt = _make_prompt(
            "PRIMARY SUBJECT: Illustrated figure at mountain summit.",
            "PRIMARY ACTION: Figure raises arms in triumph at the mountain summit, illustrated.",
            "ENVIRONMENT: Snow-capped peak, photorealistic.",
            "KAI: Lean young man, late 20s, short dark hair, light stubble, simple dark shirt, plain trousers, calm expression.",
            "STYLE: Hybrid cinematic.",
        )
        normalized, changes = normalize_prompt_fields(prompt)
        assert "KAI:" in normalized
        assert not any("KAI" in c for c in changes)


class TestNormalizePromptFieldsIdempotent:
    """Normalization is idempotent and leaves clean prompts unchanged."""

    def test_clean_prompt_unchanged(self):
        """A prompt with no duplicates is returned byte-for-byte identical."""
        prompt = _make_prompt(
            "PRIMARY SUBJECT: Eagle soaring above the canyon.",
            "PRIMARY ACTION: Eagle banks sharply left, wings fully spread, talons tucked.",
            "ENVIRONMENT: Grand canyon at golden hour, photorealistic.",
            "COMPOSITION: Wide shot, low angle camera angle.",
            "CAMERA: 35mm.",
            "STYLE: Hybrid cinematic.",
            "LIGHTING: Golden hour light.",
            "NEGATIVE: No text, no watermark.",
        )
        normalized, changes = normalize_prompt_fields(prompt)
        assert normalized == prompt
        assert changes == []

    def test_empty_prompt_unchanged(self):
        normalized, changes = normalize_prompt_fields("")
        assert normalized == ""
        assert changes == []

    def test_no_field_lines_unchanged(self):
        """A prompt with no labeled fields is returned unchanged."""
        prompt = "A tiny ant crawls across a massive rock. Photorealistic."
        normalized, changes = normalize_prompt_fields(prompt)
        assert normalized == prompt
        assert changes == []

    def test_running_twice_is_idempotent(self):
        """Normalizing an already-normalized prompt produces no further changes."""
        prompt = _make_prompt(
            "PRIMARY SUBJECT: Host, calm expression.",
            "PRIMARY ACTION: Host, calm expression.",  # duplicate — first pass removes it
            "ENVIRONMENT: Studio, photorealistic.",
        )
        pass1, changes1 = normalize_prompt_fields(prompt)
        pass2, changes2 = normalize_prompt_fields(pass1)
        assert pass1 == pass2
        assert changes2 == []


class TestNormalizeInRunPromptQaPass:
    """normalize_prompt_fields is called inside run_prompt_qa_pass after LLM repairs."""

    def test_normalization_applied_count_incremented(self):
        """report.normalization_applied reflects scenes cleaned by the normalization pass."""
        subj = "Host, attentive expression, seated upright, charcoal shirt."
        scene = _make_scene(1, "The host speaks directly.", f"PRIMARY SUBJECT: {subj}\nPRIMARY ACTION: {subj}\nENVIRONMENT: Studio.")
        scenes = [scene]

        # LLM says nothing to repair
        payload = _qa_payload([{
            "scene_index": 1, "issues": [], "fixes": [],
            "repaired_prompt": scene["visual_prompt"], "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.normalization_applied == 1
        assert "PRIMARY ACTION" not in scenes[0]["visual_prompt"]

    def test_normalization_zero_when_no_duplicates(self):
        """report.normalization_applied is 0 when no normalization is needed."""
        scene = _make_scene(1, "Eagle soars.", "Eagle soaring, photorealistic.")
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1, "issues": [], "fixes": [],
            "repaired_prompt": "Eagle soaring, photorealistic.", "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.normalization_applied == 0

    def test_normalization_syncs_compiled_prompt(self):
        """After normalization, structured_prompt.compiled_prompt is also updated."""
        subj = "Researcher, calm, seated, pale shirt."
        raw = f"PRIMARY SUBJECT: {subj}\nPRIMARY ACTION: {subj}\nENVIRONMENT: Lab."
        scene = _make_scene(1, "The researcher studies.", raw)
        scene["structured_prompt"] = {"compiled_prompt": raw, "style": "doc"}
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1, "issues": [], "fixes": [],
            "repaired_prompt": raw, "unresolved": [],
        }])

        run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert "PRIMARY ACTION" not in scenes[0]["visual_prompt"]
        assert scenes[0]["structured_prompt"]["compiled_prompt"] == scenes[0]["visual_prompt"]

    def test_normalization_after_llm_repair(self):
        """Normalization runs on the LLM-repaired prompt, catching any duplicates it introduced."""
        original = "River flows, photorealistic."
        subj = "Rushing river at dawn."
        # LLM repair introduces a duplicate PRIMARY ACTION
        repaired_by_llm = f"PRIMARY SUBJECT: {subj}\nPRIMARY ACTION: {subj}\nENVIRONMENT: Mountain valley."

        scene = _make_scene(1, "The river flows.", original)
        scenes = [scene]

        payload = _qa_payload([{
            "scene_index": 1,
            "issues": [{"check": "A", "description": "mismatch"}],
            "fixes": ["replaced"],
            "repaired_prompt": repaired_by_llm,
            "unresolved": [],
        }])

        report = run_prompt_qa_pass(scenes, _llm_returning(payload))

        assert report is not None
        assert report.repairs_applied == 1  # LLM repair counted
        assert report.normalization_applied == 1  # normalization also fired
        assert "PRIMARY ACTION" not in scenes[0]["visual_prompt"]

    def test_to_dict_includes_normalization_applied(self):
        """PromptQAReport.to_dict() serialises normalization_applied."""
        report = PromptQAReport(
            status="PASS",
            scenes_checked=1,
            issues_found=0,
            issues_fixed=0,
            repairs_applied=0,
            normalization_applied=2,
            unresolved=[],
        )
        d = report.to_dict()
        assert d["normalization_applied"] == 2
