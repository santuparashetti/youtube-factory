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
