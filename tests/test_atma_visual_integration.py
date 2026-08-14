"""Tests for Atma Theory narrative integration into the visual pipeline.

Verifies that:
- ScriptIdentity reaches VisualBible and StoryBible generation.
- 7-beat structure is assigned across scenes.
- Atma projects do not require script-segments.json for emotional metadata.
- Beat information reaches Phase 2 prompt generation.
- Scene-specific narrative context reaches V2 structured prompts.
- Narrative context reaches remediation.
- Legacy projects (no beats / no script_identity) degrade gracefully.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from ytfactory.agents.nodes.scene_planner import (
    _assign_beat_metadata,
    _BEAT_INTENSITIES,
    _BEAT_PURPOSES,
    _make_identity_context,
    _make_scene_narrative_context,
)
from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt
from ytfactory.prompts.remediation_engine import RemediationEngine
from ytfactory.story_bible.generator import generate_story_bible
from video_core.providers.vision.models import IssueSeverity, VisionIssue, VisionReviewResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

_BEATS_7 = [
    {"id": 1, "beat": "DISRUPT"},
    {"id": 2, "beat": "CHALLENGE"},
    {"id": 3, "beat": "PROVE"},
    {"id": 4, "beat": "REVEAL"},
    {"id": 5, "beat": "FRAME"},
    {"id": 6, "beat": "APPLY"},
    {"id": 7, "beat": "TRANSFORM"},
]

_IDENTITY = {
    "core_topic": "Stoic philosophy",
    "core_thesis": "Happiness is found in virtue, not in external circumstances.",
    "emotional_promise": "The viewer will feel grounded and purposeful.",
    "central_conflict": "The desire for comfort versus the call to live rightly.",
    "important_visual_moments": [
        "A man sitting alone by a fire in a vast dark field.",
        "An empty throne in a dust-filled throne room.",
    ],
    "important_factual_details": [],
    "intended_audience_takeaway": "Choose virtue daily.",
    "strong_original_ideas": [],
    "key_story": "",
    "key_philosophical_insight": "",
}


def _scene(idx: int, scene_type: str = "generated_image") -> dict:
    return {
        "index": idx,
        "title": f"Scene {idx}",
        "narration": f"Narration for scene {idx}.",
        "duration_seconds": 10.0,
        "scene_type": scene_type,
    }


def _generated_scenes(n: int) -> list[dict]:
    return [_scene(i + 1) for i in range(n)]


# ── _make_identity_context ────────────────────────────────────────────────────


def test_make_identity_context_returns_empty_for_empty_dict():
    assert _make_identity_context({}) == ""


def test_make_identity_context_includes_core_thesis():
    ctx = _make_identity_context(_IDENTITY)
    assert "Happiness is found in virtue" in ctx
    assert "Core thesis:" in ctx


def test_make_identity_context_includes_visual_moments():
    ctx = _make_identity_context(_IDENTITY)
    assert "A man sitting alone" in ctx


def test_make_identity_context_includes_emotional_promise():
    ctx = _make_identity_context(_IDENTITY)
    assert "grounded and purposeful" in ctx


def test_make_identity_context_header_present():
    ctx = _make_identity_context(_IDENTITY)
    assert "APPROVED SCRIPT IDENTITY" in ctx


# ── _assign_beat_metadata ─────────────────────────────────────────────────────


def test_assign_beat_metadata_empty_beats_is_noop():
    scenes = _generated_scenes(5)
    _assign_beat_metadata(scenes, [])
    assert not any(s.get("assigned_beat") for s in scenes)


def test_assign_beat_metadata_single_beat_all_scenes_get_it():
    scenes = _generated_scenes(3)
    _assign_beat_metadata(scenes, [{"id": 1, "beat": "DISRUPT"}])
    assert all(s["assigned_beat"] == "DISRUPT" for s in scenes)


def test_assign_beat_metadata_7beats_first_scene_is_disrupt():
    scenes = _generated_scenes(14)
    _assign_beat_metadata(scenes, _BEATS_7)
    assert scenes[0]["assigned_beat"] == "DISRUPT"


def test_assign_beat_metadata_7beats_last_scene_is_transform():
    scenes = _generated_scenes(14)
    _assign_beat_metadata(scenes, _BEATS_7)
    assert scenes[-1]["assigned_beat"] == "TRANSFORM"


def test_assign_beat_metadata_all_beats_represented():
    scenes = _generated_scenes(21)
    _assign_beat_metadata(scenes, _BEATS_7)
    assigned = {s["assigned_beat"] for s in scenes}
    expected = {b["beat"] for b in _BEATS_7}
    assert assigned == expected


def test_assign_beat_metadata_is_hook_only_on_first_beat_group():
    scenes = _generated_scenes(7)
    _assign_beat_metadata(scenes, _BEATS_7)
    assert scenes[0]["is_hook"] is True
    assert all(not s.get("is_hook") for s in scenes[1:])


def test_assign_beat_metadata_resolves_story_only_on_last_beat_group():
    scenes = _generated_scenes(7)
    _assign_beat_metadata(scenes, _BEATS_7)
    assert scenes[-1]["resolves_story"] is True
    assert all(not s.get("resolves_story") for s in scenes[:-1])


def test_assign_beat_metadata_sets_narrative_purpose():
    scenes = _generated_scenes(7)
    _assign_beat_metadata(scenes, _BEATS_7)
    assert scenes[0]["narrative_purpose"] == _BEAT_PURPOSES["DISRUPT"]


def test_assign_beat_metadata_does_not_overwrite_existing_emotional_intensity():
    scenes = _generated_scenes(3)
    scenes[0]["emotional_intensity"] = 0.42  # pre-existing from script-segments.json
    _assign_beat_metadata(scenes, _BEATS_7[:3])
    assert scenes[0]["emotional_intensity"] == 0.42  # preserved


def test_assign_beat_metadata_fills_in_missing_emotional_intensity():
    scenes = _generated_scenes(3)
    _assign_beat_metadata(scenes, [{"id": 1, "beat": "REVEAL"}] * 3)
    assert scenes[0]["emotional_intensity"] == _BEAT_INTENSITIES["REVEAL"]


def test_assign_beat_metadata_skips_non_generated_scenes():
    scenes = _generated_scenes(3)
    brand_card = _scene(4, scene_type="brand_card")
    all_scenes = scenes + [brand_card]
    _assign_beat_metadata(all_scenes, _BEATS_7)
    assert "assigned_beat" not in brand_card


# ── _make_scene_narrative_context ─────────────────────────────────────────────


def test_make_scene_narrative_context_empty_when_no_beat_or_identity():
    scene = _scene(1)
    assert _make_scene_narrative_context(scene, {}) == ""


def test_make_scene_narrative_context_includes_beat():
    scene = {**_scene(1), "assigned_beat": "REVEAL"}
    ctx = _make_scene_narrative_context(scene, {})
    assert "REVEAL" in ctx
    assert "pivotal discovery" in ctx


def test_make_scene_narrative_context_includes_core_thesis():
    scene = {**_scene(1), "assigned_beat": "APPLY"}
    ctx = _make_scene_narrative_context(scene, _IDENTITY)
    assert "Happiness is found in virtue" in ctx


def test_make_scene_narrative_context_has_header():
    scene = {**_scene(1), "assigned_beat": "TRANSFORM"}
    ctx = _make_scene_narrative_context(scene, _IDENTITY)
    assert "NARRATIVE CONTEXT" in ctx


# ── Phase 2 prompt includes beat ─────────────────────────────────────────────


def test_build_visual_prompts_prompt_includes_beat_when_present():
    scenes = [
        {
            "index": 1,
            "narration": "A philosopher writes at dawn.",
            "shot_type": "medium",
            "assigned_beat": "DISRUPT",
            "scene_type": "generated_image",
        }
    ]
    prompt = build_visual_prompts_prompt(scenes)
    assert "DISRUPT" in prompt


def test_build_visual_prompts_prompt_no_beat_when_absent():
    scenes = [
        {
            "index": 1,
            "narration": "A philosopher writes at dawn.",
            "shot_type": "medium",
            "scene_type": "generated_image",
        }
    ]
    prompt = build_visual_prompts_prompt(scenes)
    # Should not contain beat labels when no beats assigned
    assert "Narrative beat:" not in prompt


# ── Atma projects: no script-segments.json needed ─────────────────────────────


def test_assign_beat_metadata_produces_emotional_metadata_without_segments():
    """An Atma project gets emotional metadata purely from beat assignment."""
    scenes = _generated_scenes(7)
    # No script-segments.json → scenes start with no emotional metadata
    _assign_beat_metadata(scenes, _BEATS_7)
    assert all(s.get("emotional_intensity") is not None for s in scenes)
    assert scenes[0]["is_hook"] is True
    assert scenes[-1]["resolves_story"] is True


# ── Legacy compatibility ───────────────────────────────────────────────────────


def test_legacy_scenes_without_beats_retain_existing_linked_segment(tmp_path):
    """Legacy projects with script-segments.json keep their linked_segment untouched."""
    from ytfactory.agents.nodes.scene_planner import _attach_emotional_metadata

    project_id = "legacy-test"
    script_dir = tmp_path / project_id / "script"
    script_dir.mkdir(parents=True)
    segments_data = {
        "segments": [
            {
                "text": "Narration for scene 1.",
                "emotional_intensity": 0.9,
                "is_hook": True,
                "is_rehook": False,
                "is_frame_label": False,
                "is_bridge": False,
                "resolves_story": False,
            }
        ]
    }
    (script_dir / "script-segments.json").write_text(
        json.dumps(segments_data), encoding="utf-8"
    )

    scenes = [_scene(1)]

    with patch("ytfactory.agents.nodes.scene_planner.WORKSPACE_DIR", str(tmp_path)):
        _attach_emotional_metadata(project_id, scenes)

    # linked_segment populated from old segmentation file
    assert "linked_segment" in scenes[0]
    assert scenes[0]["linked_segment"]["emotional_intensity"] == 0.9
    assert scenes[0]["linked_segment"]["is_hook"] is True

    # No beats → _assign_beat_metadata is a no-op → legacy metadata preserved
    _assign_beat_metadata(scenes, [])
    assert scenes[0]["linked_segment"]["emotional_intensity"] == 0.9


# ── StoryBible generation with identity context ───────────────────────────────


def test_generate_story_bible_prepends_identity_context():
    """generate_story_bible includes identity context in the LLM prompt."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = MagicMock(
        text=json.dumps({
            "world": {
                "era": "HISTORICAL",
                "cultural_context": "medieval Europe",
                "key_objects": {},
                "recurring_symbols": [],
                "architectural_style": "stone halls",
                "time_period_note": "pre-industrial",
            },
            "characters": [],
            "locations": [],
            "do_not_change": [],
        })
    )

    identity_ctx = "APPROVED SCRIPT IDENTITY:\n- Core thesis: test thesis\n\n"
    generate_story_bible(["Scene 1 narration."], mock_llm, script_identity_context=identity_ctx)

    call_args = mock_llm.generate.call_args
    prompt_sent = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    assert "APPROVED SCRIPT IDENTITY" in prompt_sent
    assert "test thesis" in prompt_sent


def test_generate_story_bible_no_identity_context_skips_block():
    """generate_story_bible works normally when no identity context provided."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = MagicMock(
        text=json.dumps({
            "world": {
                "era": "MODERN",
                "cultural_context": "contemporary",
                "key_objects": {},
                "recurring_symbols": [],
                "architectural_style": "office",
                "time_period_note": "",
            },
            "characters": [],
            "locations": [],
            "do_not_change": [],
        })
    )

    generate_story_bible(["Scene narration."], mock_llm)
    call_args = mock_llm.generate.call_args
    prompt_sent = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    assert "APPROVED SCRIPT IDENTITY" not in prompt_sent


# ── RemediationEngine: narrative context ──────────────────────────────────────


def _make_environment_fail() -> VisionReviewResult:
    return VisionReviewResult(
        status="FAIL",
        score=40.0,
        confidence=80.0,
        issues=[
            VisionIssue(
                category="environment",
                description="Scene shows a modern office instead of ancient ruins.",
                severity=IssueSeverity.HIGH,
            )
        ],
    )


def _make_anatomy_fail() -> VisionReviewResult:
    return VisionReviewResult(
        status="FAIL",
        score=55.0,
        confidence=85.0,
        issues=[
            VisionIssue(
                category="anatomy",
                description="Malformed hand with six fingers.",
                severity=IssueSeverity.HIGH,
            )
        ],
    )


def test_remediation_engine_adds_narrative_intent_for_environment_issue():
    engine = RemediationEngine()
    ctx = {
        "narration": "Marcus Aurelius alone in ancient Roman ruins at dusk.",
        "assigned_beat": "REVEAL",
        "narrative_purpose": "The pivotal discovery.",
        "story_context": "",
        "action_constraints": "",
        "scene_analysis": {},
    }
    package = engine.build(
        original_prompt="Ancient ruins, wide shot.",
        result=_make_environment_fail(),
        scene_context=ctx,
    )
    assert "NARRATIVE INTENT" in package.remediated_prompt
    assert "Marcus Aurelius" in package.remediated_prompt
    assert "REVEAL" in package.remediated_prompt


def test_remediation_engine_no_narrative_intent_for_anatomy_issue():
    """Anatomy issues are visual-quality only — no narrative intent block needed."""
    engine = RemediationEngine()
    ctx = {
        "narration": "A man walks through the forest.",
        "assigned_beat": "CHALLENGE",
        "narrative_purpose": "",
        "story_context": "",
        "action_constraints": "",
        "scene_analysis": {},
    }
    package = engine.build(
        original_prompt="Man walking in forest, medium shot.",
        result=_make_anatomy_fail(),
        scene_context=ctx,
    )
    # Anatomy-only issue → no narrative intent prefix needed
    assert "NARRATIVE INTENT" not in package.remediated_prompt


def test_remediation_engine_without_scene_context_unchanged():
    """Passing no scene_context preserves existing behavior."""
    engine = RemediationEngine()
    package = engine.build(
        original_prompt="Wide shot of empty stone hall.",
        result=_make_anatomy_fail(),
    )
    assert "NARRATIVE INTENT" not in package.remediated_prompt


def test_remediation_engine_empty_narration_skips_intent():
    """Empty narration → no narrative intent injected even for environment issues."""
    engine = RemediationEngine()
    ctx = {
        "narration": "",
        "assigned_beat": "REVEAL",
        "narrative_purpose": "",
        "story_context": "",
        "action_constraints": "",
        "scene_analysis": {},
    }
    package = engine.build(
        original_prompt="Wide shot.",
        result=_make_environment_fail(),
        scene_context=ctx,
    )
    assert "NARRATIVE INTENT" not in package.remediated_prompt


# ── VisualBible: identity context in prompt ───────────────────────────────────


def test_generate_visual_bible_includes_identity_context():
    """VisualBible LLM call includes the script identity block."""
    from ytfactory.agents.nodes.scene_planner import _generate_visual_bible

    mock_llm = MagicMock()
    mock_llm.generate.return_value = MagicMock(
        text=json.dumps({
            "dominant_metaphor": "A river seeking the sea",
            "anchor_environments": ["Forest clearing", "Mountaintop"],
            "color_arc": {
                "hook": "desaturated blue",
                "opening": "cool grey",
                "build": "warm amber",
                "climax": "intense gold",
                "resolution": "soft golden",
            },
            "visual_motifs": ["running water", "open sky"],
            "shot_arc": {
                "opening_scenes": "wide",
                "build_scenes": "medium",
                "climax_scene": "close-up",
                "resolution_scenes": "pull back",
            },
        })
    )

    mock_settings = MagicMock()
    mock_settings.VISUAL_BIBLE_ENABLED = True
    mock_settings.HYBRID_STYLE_ENABLED = True
    type(mock_settings).AUDIENCE_PROFILE = "western_english"

    identity_ctx = "APPROVED SCRIPT IDENTITY:\n- Core thesis: Virtue is its own reward.\n\n"
    _generate_visual_bible("Test script text.", mock_llm, mock_settings, script_identity_context=identity_ctx)

    call_args = mock_llm.generate.call_args
    prompt_sent = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    assert "APPROVED SCRIPT IDENTITY" in prompt_sent
    assert "Virtue is its own reward" in prompt_sent


# ── Fix 3: beat/scene mismatch regression ────────────────────────────────────


def test_assign_beat_metadata_fewer_scenes_than_beats():
    """3 scenes with 7 beats: proportional distribution, no crash."""
    scenes = [{"index": i} for i in range(3)]
    beats = _BEATS_7

    _assign_beat_metadata(scenes, beats)

    # i=0 → beat_idx = min(int(0 * 7 / 3), 6) = 0 → DISRUPT
    # i=1 → beat_idx = min(int(1 * 7 / 3), 6) = 2 → PROVE
    # i=2 → beat_idx = min(int(2 * 7 / 3), 6) = 4 → FRAME
    assert scenes[0]["assigned_beat"] == "DISRUPT"
    assert scenes[1]["assigned_beat"] == "PROVE"
    assert scenes[2]["assigned_beat"] == "FRAME"


def test_assign_beat_metadata_more_scenes_than_beats():
    """14 scenes with 7 beats: each beat assigned to two consecutive scenes."""
    scenes = [{"index": i} for i in range(14)]
    _assign_beat_metadata(scenes, _BEATS_7)

    # i=0 → idx=0 DISRUPT, i=1 → idx=0 DISRUPT, i=2 → idx=1 CHALLENGE …
    assert scenes[0]["assigned_beat"] == "DISRUPT"
    assert scenes[1]["assigned_beat"] == "DISRUPT"
    assert scenes[2]["assigned_beat"] == "CHALLENGE"
    assert scenes[13]["assigned_beat"] == "TRANSFORM"


# ── Fix 1 & 2: VisualBible / StoryBible cache invalidation ───────────────────


def test_identity_hash_stable_for_same_input():
    """_identity_hash produces identical output for the same dict."""
    from ytfactory.agents.nodes.scene_planner import _identity_hash
    d = {"core_topic": "Stoicism", "core_thesis": "Virtue is all."}
    assert _identity_hash(d) == _identity_hash(d)


def test_identity_hash_empty_returns_empty_string():
    """Empty dict → empty string (legacy compat: no cache invalidation)."""
    from ytfactory.agents.nodes.scene_planner import _identity_hash
    assert _identity_hash({}) == ""


def test_identity_hash_differs_on_content_change():
    """Different identity dicts produce different hashes."""
    from ytfactory.agents.nodes.scene_planner import _identity_hash
    h1 = _identity_hash({"core_topic": "A"})
    h2 = _identity_hash({"core_topic": "B"})
    assert h1 != h2
    assert len(h1) == 16


def test_story_bible_cache_hit_new_format(tmp_path):
    """load_or_generate_story_bible returns cached bible when hash matches."""
    from ytfactory.story_bible.generator import load_or_generate_story_bible, _story_bible_identity_hash

    ctx = "SCRIPT IDENTITY: some context"
    current_hash = _story_bible_identity_hash(ctx)

    bible_data = {
        "world": {"era": "ANCIENT", "cultural_context": "", "key_objects": {}, "recurring_symbols": [], "architectural_style": "", "time_period_note": ""},
        "characters": [],
        "locations": [],
        "style": {},
        "do_not_change": [],
    }
    cache = {"identity_hash": current_hash, "bible": bible_data}
    bible_dir = tmp_path / "proj123" / "story-bible"
    bible_dir.mkdir(parents=True)
    (bible_dir / "bible.json").write_text(json.dumps(cache), encoding="utf-8")

    mock_llm = MagicMock()
    result = load_or_generate_story_bible(
        "proj123", str(tmp_path), ["Narration 1"], mock_llm,
        script_identity_context=ctx,
    )
    mock_llm.generate.assert_not_called()
    assert result is not None


def test_story_bible_cache_invalidated_on_hash_mismatch(tmp_path):
    """load_or_generate_story_bible regenerates when identity_hash differs."""
    from ytfactory.story_bible.generator import load_or_generate_story_bible

    bible_data = {
        "world": {"era": "ANCIENT", "cultural_context": "", "key_objects": {}, "recurring_symbols": [], "architectural_style": "", "time_period_note": ""},
        "characters": [],
        "locations": [],
        "style": {},
        "do_not_change": [],
    }
    cache = {"identity_hash": "stale0000000000", "bible": bible_data}
    bible_dir = tmp_path / "proj999" / "story-bible"
    bible_dir.mkdir(parents=True)
    (bible_dir / "bible.json").write_text(json.dumps(cache), encoding="utf-8")

    mock_llm = MagicMock()
    mock_llm.generate.return_value = MagicMock(text=json.dumps({
        "world": {"era": "MODERN", "cultural_context": "", "key_objects": {}, "recurring_symbols": [], "architectural_style": "", "time_period_note": ""},
        "characters": [], "locations": [], "do_not_change": [],
    }))

    result = load_or_generate_story_bible(
        "proj999", str(tmp_path), ["Narration 1"], mock_llm,
        script_identity_context="NEW IDENTITY: changed",
    )
    mock_llm.generate.assert_called_once()
    assert result is not None


def test_story_bible_legacy_format_loads_without_invalidation(tmp_path):
    """Old-format bible.json (no 'bible' key) loads without hash check."""
    from ytfactory.story_bible.generator import load_or_generate_story_bible

    legacy_data = {
        "world": {"era": "HISTORICAL", "cultural_context": "", "key_objects": {}, "recurring_symbols": [], "architectural_style": "", "time_period_note": ""},
        "characters": [],
        "locations": [],
        "style": {},
        "do_not_change": [],
    }
    bible_dir = tmp_path / "legacy_proj" / "story-bible"
    bible_dir.mkdir(parents=True)
    (bible_dir / "bible.json").write_text(json.dumps(legacy_data), encoding="utf-8")

    mock_llm = MagicMock()
    result = load_or_generate_story_bible(
        "legacy_proj", str(tmp_path), ["Narration 1"], mock_llm,
        script_identity_context="any identity",
    )
    mock_llm.generate.assert_not_called()
    assert result is not None


# ── _extract_narrative_ending unit tests ──────────────────────────────────────


class TestExtractNarrativeEnding:
    """Tests for the narrative-ending extraction function used by the quality gate.

    Covers all four extraction priorities and the key failure-mode scenarios
    that caused genuine narrative closure to be misidentified as missing.
    """

    def setup_method(self):
        from ytfactory.agents.nodes.scene_planner import _extract_narrative_ending
        self.extract = _extract_narrative_ending

    # ── Priority 1: explicit [NARRATIVE_ENDING] marker ────────────────────────

    def test_marker_extraction_returns_paragraph_after_marker(self):
        script = (
            "He had climbed for forty days.\n\n"
            "[NARRATIVE_ENDING]\n"
            "He reached the summit. Not because it was there — because he had stopped\n"
            "asking whether he could.\n\n"
            "[ENGAGEMENT: subscribe_promise]\n"
            "If this landed for you, subscribe.\n\n"
            "[ENGAGEMENT: branding_end]\n"
            "This is Atma Theory."
        )
        result = self.extract(script)
        assert "reached the summit" in result
        assert "subscribe" not in result.lower()

    def test_marker_extraction_excludes_engagement_content(self):
        """Content after [ENGAGEMENT: ...] must not bleed into narrative ending."""
        script = (
            "Opening tension.\n\n"
            "[NARRATIVE_ENDING]\n"
            "The tension resolved here.\n\n"
            "[ENGAGEMENT: subscribe_promise]\n"
            "Subscribe for more.\n\n"
            "[ENGAGEMENT: branding_end]\n"
            "This is Atma Theory."
        )
        result = self.extract(script)
        assert "tension resolved" in result
        assert "Subscribe" not in result

    def test_marker_extraction_supports_multi_sentence_resolution(self):
        """[NARRATIVE_ENDING] should return the full paragraph, not one line."""
        script = (
            "Opening.\n\n"
            "[NARRATIVE_ENDING]\n"
            "He stopped running. He sat down.\n"
            "The mountain did not move. But he did.\n\n"
            "[ENGAGEMENT: branding_end]\n"
            "This is Atma Theory."
        )
        result = self.extract(script)
        assert "stopped running" in result
        assert "mountain did not move" in result

    # ── Priority 2: closing engagement marker boundary ────────────────────────

    def test_engagement_boundary_extracts_last_narrative_para(self):
        """When no [NARRATIVE_ENDING] marker, use subscribe_promise as boundary."""
        script = (
            "Opening image: an ant on Everest.\n\n"
            "The ant did not know it was climbing Everest.\n\n"
            "[ENGAGEMENT: comment_prompt]\n"
            "Which principle resonates most?\n\n"
            "That is the lesson of the ant.\n\n"
            "[ENGAGEMENT: subscribe_promise]\n"
            "If this resonated, subscribe.\n\n"
            "[ENGAGEMENT: branding_end]\n"
            "This is Atma Theory."
        )
        result = self.extract(script)
        assert "lesson of the ant" in result
        assert "subscribe" not in result.lower()

    def test_engagement_boundary_skips_engagement_para_before_closing(self):
        """comment_prompt paragraph must not be returned as narrative ending."""
        script = (
            "She walked into the room.\n\n"
            "[ENGAGEMENT: comment_prompt]\n"
            "Which struggle resonates most?\n\n"
            "[ENGAGEMENT: subscribe_promise]\n"
            "Subscribe for more.\n\n"
            "[ENGAGEMENT: branding_end]\n"
            "This is Atma Theory."
        )
        result = self.extract(script)
        # The last narrative para before subscribe_promise is "She walked into the room."
        assert "walked into the room" in result
        assert "Which struggle" not in result

    def test_cta_only_ending_does_not_become_narrative_ending(self):
        """A script ending purely in CTA+branding must not return a CTA line."""
        script = (
            "A craftsman worked for thirty years.\n\n"
            "[ENGAGEMENT: subscribe_promise]\n"
            "Subscribe so the next idea finds you.\n\n"
            "[ENGAGEMENT: branding_end]\n"
            "This is Atma Theory."
        )
        result = self.extract(script)
        # Should return the narrative paragraph, not the CTA
        assert "craftsman" in result or "thirty years" in result
        assert "Subscribe so the next" not in result

    # ── Priority 3: legacy brand marker detection ─────────────────────────────

    def test_legacy_script_with_brand_marker_extracts_full_paragraph(self):
        """Old-style scripts without engagement markers use legacy brand detection."""
        script = (
            "He stood at the edge of the canyon.\n"
            "The wind did not stop. Neither did he.\n\n"
            "This is Atma Theory. Clear mind. Meaningful life."
        )
        result = self.extract(script)
        assert "canyon" in result or "wind" in result
        # Must not include the brand phrase itself
        assert "Atma Theory" not in result

    def test_legacy_fallback_does_not_return_empty(self):
        """Legacy path must always return non-empty text for a non-empty script."""
        script = (
            "The river keeps moving.\n\n"
            "This is Atma Theory."
        )
        result = self.extract(script)
        assert result.strip()

    # ── Priority 4: final fallback ────────────────────────────────────────────

    def test_no_markers_returns_last_paragraph(self):
        """Unmarked script with no brand phrases returns the last paragraph."""
        script = (
            "He began at sunrise.\n\n"
            "He finished at dusk.\n\n"
            "The work was done."
        )
        result = self.extract(script)
        assert "work was done" in result

    def test_empty_script_returns_empty(self):
        result = self.extract("")
        assert result == ""

    # ── Narrative vs CTA separation ───────────────────────────────────────────

    def test_subscribe_message_never_returned_as_narrative_ending(self):
        """Marker-based path must never return subscribe content."""
        script = (
            "The question remained open.\n\n"
            "[NARRATIVE_ENDING]\n"
            "The question resolved here — quietly.\n\n"
            "[ENGAGEMENT: subscribe_promise]\n"
            "Subscribe so the next one finds you.\n\n"
            "[ENGAGEMENT: branding_end]\n"
            "This is Atma Theory."
        )
        result = self.extract(script)
        assert "Subscribe" not in result
        assert "resolved here" in result

    def test_branding_end_never_returned_as_narrative_ending(self):
        """branding_end content must never bleed into narrative ending."""
        script = (
            "The candle burned down.\n\n"
            "[NARRATIVE_ENDING]\n"
            "And in the dark, she finally saw clearly.\n\n"
            "[ENGAGEMENT: branding_end]\n"
            "This is Atma Theory. Clear mind. Meaningful life."
        )
        result = self.extract(script)
        assert "finally saw clearly" in result
        assert "Clear mind" not in result
        assert "Atma Theory" not in result


# ── Beat coverage calibration ─────────────────────────────────────────────────


class TestBeatCoverageCalibration:
    """Regression tests for beat pattern calibration.

    Ensures:
    - Action-first / documentary-style openings are not false-positively flagged.
    - Existing valid patterns still fire.
    - CTA / engagement text cannot satisfy TRANSFORM.
    - UI uses "Beat coverage:" not "Beats covered:".
    """

    def setup_method(self):
        from ytfactory.atma_refiner.validator import _check_beat_coverage
        self._check = _check_beat_coverage

    # ── DISRUPT: action-first openings accepted ───────────────────────────────

    def test_disrupt_action_first_he_had(self):
        """'He had done it ten thousand times.' must match DISRUPT."""
        coverage = self._check("He had done it ten thousand times. The blade was perfect.")
        assert coverage["DISRUPT"] is True

    def test_disrupt_action_first_she_stood(self):
        """'She stood at the edge of the platform.' must match DISRUPT."""
        coverage = self._check("She stood at the edge of the platform, not knowing what came next.")
        assert coverage["DISRUPT"] is True

    def test_disrupt_for_years(self):
        """'For years he had searched.' must match DISRUPT."""
        coverage = self._check("For years he had searched the archives.")
        assert coverage["DISRUPT"] is True

    def test_disrupt_day_after_day(self):
        """'Day after day, the craftsman returned.' must match DISRUPT."""
        coverage = self._check("Day after day, the craftsman returned to the same stone.")
        assert coverage["DISRUPT"] is True

    def test_disrupt_one_morning(self):
        """'One morning, the answer came.' must match DISRUPT."""
        coverage = self._check("One morning, the answer came not as a thought but as a feeling.")
        assert coverage["DISRUPT"] is True

    # ── DISRUPT: existing patterns still fire ─────────────────────────────────

    def test_disrupt_imagine_still_works(self):
        """Legacy 'Imagine...' opener must still match DISRUPT."""
        coverage = self._check("Imagine standing at the top of a mountain.")
        assert coverage["DISRUPT"] is True

    def test_disrupt_what_if_still_works(self):
        """Legacy 'What if' opener must still match DISRUPT."""
        coverage = self._check("What if everything you believed was wrong?")
        assert coverage["DISRUPT"] is True

    # ── APPLY: documentary-style application accepted ─────────────────────────

    def test_apply_in_daily_practice(self):
        """'In daily practice, this shows up as...' must match APPLY."""
        coverage = self._check("In daily practice, this shows up as a moment of hesitation.")
        assert coverage["APPLY"] is True

    def test_apply_for_anyone(self):
        """'For anyone who faces this...' must match APPLY."""
        coverage = self._check("For anyone who faces this kind of choice, the principle is the same.")
        assert coverage["APPLY"] is True

    def test_apply_this_applies(self):
        """'This applies whenever...' must match APPLY."""
        coverage = self._check("This applies whenever the stakes feel too high to act clearly.")
        assert coverage["APPLY"] is True

    def test_apply_this_changes_how(self):
        """'This changes how we approach...' must match APPLY."""
        coverage = self._check("This changes how we approach every creative decision.")
        assert coverage["APPLY"] is True

    # ── APPLY: existing patterns still fire ──────────────────────────────────

    def test_apply_in_your_life_still_works(self):
        """Legacy 'in your life' must still match APPLY."""
        coverage = self._check("In your life, this principle shows up as a small daily choice.")
        assert coverage["APPLY"] is True

    def test_apply_when_you_still_works(self):
        """Legacy 'when you' must still match APPLY."""
        coverage = self._check("When you face a difficult decision, remember this.")
        assert coverage["APPLY"] is True

    # ── TRANSFORM: engagement/CTA text cannot satisfy beat ───────────────────

    def test_transform_subscribe_cta_does_not_count(self):
        """Subscribe CTA alone must not satisfy TRANSFORM."""
        script = (
            "A narrative paragraph here.\n\n"
            "[ENGAGEMENT: subscribe_promise]\n"
            "If this resonated, subscribe so the next one finds you.\n\n"
            "[ENGAGEMENT: branding_end]\n"
            "This is Atma Theory. Clear mind. Meaningful life."
        )
        coverage = self._check(script)
        assert coverage["TRANSFORM"] is False

    def test_transform_this_is_atma_theory_in_branding_does_not_count(self):
        """'This is Atma Theory' inside branding_end must not satisfy TRANSFORM."""
        script = (
            "He walked forward.\n\n"
            "[ENGAGEMENT: branding_end]\n"
            "This is Atma Theory. Clear mind. Meaningful life."
        )
        coverage = self._check(script)
        assert coverage["TRANSFORM"] is False

    def test_transform_real_narrative_content_is_accepted(self):
        """Genuine TRANSFORM narrative content must still match."""
        script = (
            "A narrative opening.\n\n"
            "The real measure of success is not what you achieve but what you become.\n\n"
            "Stop chasing the outcome. Start building the practice.\n\n"
            "[ENGAGEMENT: subscribe_promise]\n"
            "If this resonated, subscribe.\n\n"
            "[ENGAGEMENT: branding_end]\n"
            "This is Atma Theory."
        )
        coverage = self._check(script)
        assert coverage["TRANSFORM"] is True

    # ── UI wording ────────────────────────────────────────────────────────────

    def test_ui_uses_beat_coverage_label(self):
        """Review panel must say 'Beat coverage:' — not 'Beats covered:'."""
        import inspect
        from ytfactory.agents.nodes import atma_refiner as _mod
        source = inspect.getsource(_mod)
        assert "Beat coverage" in source
        assert "Beats covered:" not in source


# ── Semantic Beat Evidence ────────────────────────────────────────────────────

class TestSemanticBeatEvidence:
    """Validator uses LLM semantic evidence as primary check with regex fallback."""

    from ytfactory.atma_refiner.validator import ScriptValidator, _check_beat_coverage_with_evidence
    from ytfactory.domain.script_revision import BeatEvidence, ScriptIdentity

    def _make_evidence(self, beat: str, evidence_text: str, present: bool = True) -> dict:
        from ytfactory.domain.script_revision import BeatEvidence
        return {beat: BeatEvidence(present=present, evidence=evidence_text, reason="test")}

    def _check_with_evidence(self, script: str, evidence: dict) -> dict:
        from ytfactory.atma_refiner.validator import _check_beat_coverage_with_evidence
        return _check_beat_coverage_with_evidence(script, evidence)

    def _validate(self, script: str, evidence: dict | None = None) -> object:
        from ytfactory.atma_refiner.validator import ScriptValidator
        from ytfactory.domain.script_revision import ScriptIdentity
        validator = ScriptValidator()
        identity = ScriptIdentity(core_topic="test", core_thesis="test")
        return validator.validate(script, identity, beat_evidence=evidence)

    # ── Evidence → beat covered ───────────────────────────────────────────────

    def test_valid_evidence_covers_beat_without_regex_match(self):
        """LLM evidence present=True with excerpt in script covers the beat."""
        script = "The craftsman refined his practice day after day."
        evidence = self._make_evidence("DISRUPT", "The craftsman refined his practice day after day.")
        coverage = self._check_with_evidence(script, evidence)
        assert coverage["DISRUPT"] is True

    def test_apply_covered_via_evidence_when_regex_would_fail(self):
        """Conditional instructional APPLY form covered via evidence even if regex misses it."""
        script = (
            "This is where the philosophy becomes practical. "
            "If your goal is to learn a language, give it twenty focused minutes today."
        )
        evidence = self._make_evidence(
            "APPLY",
            "If your goal is to learn a language, give it twenty focused minutes today.",
        )
        coverage = self._check_with_evidence(script, evidence)
        assert coverage["APPLY"] is True

    # ── Engagement content cannot satisfy a beat ──────────────────────────────

    def test_evidence_from_engagement_block_does_not_cover_beat(self):
        """Evidence text that appears only in an engagement block must not cover the beat."""
        script = (
            "A narrative paragraph.\n\n"
            "[ENGAGEMENT: value_promise]\n\n"
            "Stay with this, and you'll see the secret.\n\n"
            "More narrative here."
        )
        # The evidence excerpt lives only in the engagement block
        evidence = self._make_evidence("DISRUPT", "Stay with this, and you'll see the secret.")
        coverage = self._check_with_evidence(script, evidence)
        assert coverage["DISRUPT"] is False

    def test_evidence_from_subscribe_promise_does_not_cover_transform(self):
        """Subscribe CTA used as TRANSFORM evidence must not cover the beat."""
        script = (
            "A narrative ending.\n\n"
            "[ENGAGEMENT: subscribe_promise]\n\n"
            "If this resonated, subscribe to Atma Theory.\n\n"
            "[ENGAGEMENT: branding_end]\n\n"
            "This is Atma Theory."
        )
        evidence = self._make_evidence("TRANSFORM", "If this resonated, subscribe to Atma Theory.")
        coverage = self._check_with_evidence(script, evidence)
        assert coverage["TRANSFORM"] is False

    # ── Evidence not in script → beat not covered ─────────────────────────────

    def test_evidence_not_in_script_does_not_cover_beat(self):
        """If evidence text doesn't appear verbatim in the script, beat is not covered."""
        script = "He walked forward without hesitation."
        evidence = self._make_evidence("DISRUPT", "He ran backward in fear.")
        coverage = self._check_with_evidence(script, evidence)
        assert coverage["DISRUPT"] is False

    # ── present=False → beat not covered ─────────────────────────────────────

    def test_present_false_does_not_cover_beat(self):
        """present=False means beat is not covered regardless of evidence text."""
        script = "He had done it ten thousand times."
        evidence = self._make_evidence("DISRUPT", "He had done it ten thousand times.", present=False)
        coverage = self._check_with_evidence(script, evidence)
        assert coverage["DISRUPT"] is False

    # ── Empty evidence → beat not covered ────────────────────────────────────

    def test_empty_evidence_text_does_not_cover_beat(self):
        """present=True but empty evidence text must not cover the beat."""
        from ytfactory.domain.script_revision import BeatEvidence
        script = "He had done it ten thousand times."
        evidence = {"DISRUPT": BeatEvidence(present=True, evidence="", reason="")}
        coverage = self._check_with_evidence(script, evidence)
        assert coverage["DISRUPT"] is False

    # ── Missing beat in dict → regex fallback ────────────────────────────────

    def test_missing_beat_in_evidence_falls_back_to_regex(self):
        """When a beat is absent from evidence dict, regex is used as fallback."""
        # "When you face a difficult decision" matches the legacy 'when you' APPLY pattern
        script = "When you face a difficult decision, remember this principle."
        evidence = {}  # No APPLY in evidence → regex fallback
        coverage = self._check_with_evidence(script, evidence)
        assert coverage["APPLY"] is True

    # ── Old script (no evidence delimiter) → full regex fallback ─────────────

    def test_old_script_without_evidence_uses_regex_fallback(self):
        """Validate() with no evidence dict falls back to pure regex for all beats."""
        script = "When you face a hard choice, this principle applies in your life."
        result = self._validate(script, evidence=None)
        assert result.beat_coverage["APPLY"] is True
        assert result.beat_evidence == {}

    # ── Engagement Format A excluded ─────────────────────────────────────────

    def test_engagement_format_a_excluded_from_beat_check(self):
        """Format A engagement (marker alone, content in next para) excluded from beats."""
        script = (
            "Narrative opening line.\n\n"
            "[ENGAGEMENT: value_promise]\n\n"
            "Stop wondering about consistency — subscribe to find out.\n\n"
            "More narrative content here."
        )
        # subscribe-style language only in engagement block
        evidence = self._make_evidence("DISRUPT", "Stop wondering about consistency — subscribe to find out.")
        coverage = self._check_with_evidence(script, evidence)
        assert coverage["DISRUPT"] is False

    # ── Engagement Format B excluded ─────────────────────────────────────────

    def test_engagement_format_b_excluded_from_beat_check(self):
        """Format B engagement (marker + content same paragraph) excluded from beats."""
        script = (
            "Narrative opening.\n\n"
            "[ENGAGEMENT: subscribe_promise]\nIf this resonated, subscribe to Atma Theory.\n\n"
            "Closing narrative."
        )
        evidence = self._make_evidence("TRANSFORM", "If this resonated, subscribe to Atma Theory.")
        coverage = self._check_with_evidence(script, evidence)
        assert coverage["TRANSFORM"] is False

    # ── beat_evidence propagates through validate() ───────────────────────────

    def test_validate_propagates_beat_evidence_to_result(self):
        """ScriptValidationResult.beat_evidence must carry the passed evidence."""
        script = "He had done it ten thousand times. When you begin, this principle applies in your life."
        from ytfactory.domain.script_revision import BeatEvidence
        evidence = {"DISRUPT": BeatEvidence(present=True, evidence="He had done it ten thousand times.", reason="action-first opening")}
        result = self._validate(script, evidence=evidence)
        assert "DISRUPT" in result.beat_evidence
        assert result.beat_evidence["DISRUPT"].present is True
