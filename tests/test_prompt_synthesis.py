"""
Tests for Image Prompt Synthesis V2.

Covers the 11 scenarios from docs/image-prompt/image_prompt_synthesis_v2_spec.md:
  1. narration subject/action preservation
  2. explicit visual-direction preservation
  3. adjacent-context usage
  4. Visual Bible continuity
  5. hybrid human/animal + environment styling
  6. no invented subjects
  7. no global Kai
  8. no-narration scene handling
  9. compositor text handling
 10. continuity across recurring subjects
 11. single LLM call
 12. final prompt contract
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from video_core.domain.llm import LLMResponse
from ytfactory.images.prompt_synthesis import (
    SynthesisIssue,
    SynthesisReport,
    _BROKEN_JOIN_RE,
    _COMPOSITOR_CTA_TYPES,
    _CTA_ENDSCREEN_PLACEHOLDER,
    _CTA_SUBSCRIBE_PLACEHOLDER,
    _ENGAGEMENT_RE,
    _KAI_INJECTION_MARKERS,
    _LEADING_ORPHAN_RE,
    _MID_SENTENCE_SPLICE_RE,
    _REPAIR_SYSTEM_PROMPT,
    _SYNTHESIS_SYSTEM_PROMPT,
    _TRAILING_TRUNCATION_RE,
    _build_scene_block,
    _build_visual_bible_section,
    _extract_visual_direction,
    _lookup_character_spec,
    _parse_synthesis_response,
    synthesize_visual_prompts,
    validate_synthesis_result,
)
from ytfactory.scenes.models import VisualBible
from ytfactory.story_bible.models import CharacterEntry, StoryBible


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_visual_bible(**overrides) -> VisualBible:
    defaults = dict(
        dominant_metaphor="light through darkness",
        anchor_environments=["ancient forest", "stone courtyard"],
        color_arc={
            "opening": "cool blue-grey",
            "build": "warm amber",
            "climax": "deep gold",
            "resolution": "soft white",
        },
        visual_motifs=["falling leaves", "candlelight"],
        shot_arc={
            "opening_scenes": "establishing_wide",
            "build_scenes": "medium",
            "climax_scene": "close_up",
            "resolution_scenes": "medium",
        },
    )
    defaults.update(overrides)
    return VisualBible(**defaults)


def _make_story_bible(characters=None) -> StoryBible:
    chars = characters or []
    return StoryBible(characters=chars)


def _make_scene(
    index: int = 1,
    narration: str = "A traveller walks through an ancient forest.",
    shot_type: str = "medium",
    character_presence: list[str] | None = None,
    scene_type: str = "generated_image",
    **extra,
) -> dict:
    return {
        "index": index,
        "narration": narration,
        "shot_type": shot_type,
        "character_presence": character_presence or [],
        "scene_type": scene_type,
        **extra,
    }


def _make_llm(response_text: str) -> MagicMock:
    llm = MagicMock()
    llm.generate.return_value = LLMResponse(
        text=response_text,
        model="test-model",
        prompt_tokens=10,
        completion_tokens=50,
        finish_reason="stop",
    )
    return llm


def _json_response(items: list[dict]) -> str:
    return json.dumps(items)


# ── Scenario 1: narration subject/action preservation ─────────────────────────


def test_narration_preserved_in_scene_block():
    """_build_scene_block must include the narration text."""
    scene = _make_scene(
        narration="An elder kneels beside a dying fire, whispering ancient prayers."
    )
    block = _build_scene_block(scene, None, None, None)
    assert "elder" in block
    assert "dying fire" in block or "whispering" in block


def test_narration_subject_in_synthesis_prompt(tmp_path):
    """synthesize_visual_prompts must pass narration to LLM and return prompt for scene."""
    vb = _make_visual_bible()
    scene = _make_scene(
        narration="A child releases a paper boat into a moonlit river."
    )
    prompt_text = "Illustrated child beside moonlit river, paper boat floating away, cinematic."
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": prompt_text}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 1 in report.prompts
    assert report.prompts[1] == prompt_text
    # LLM received a prompt containing the narration
    call_args = llm.generate.call_args
    user_prompt = call_args[0][0]
    assert "paper boat" in user_prompt
    assert "moonlit river" in user_prompt


# ── Scenario 2: explicit visual-direction preservation ────────────────────────


def test_explicit_visual_direction_in_scene_block():
    """[Visual:] tags are extracted into VISUAL_DIRECTION field; content must be present."""
    scene = _make_scene(
        narration="Fear grips the village. [Visual: extreme close-up of trembling hands clasping a torch.]"
    )
    block = _build_scene_block(scene, None, None, None)
    assert "VISUAL_DIRECTION:" in block
    assert "extreme close-up" in block
    assert "trembling hands" in block
    assert "[Visual:" not in block


# ── Scenario 3: adjacent-context usage ───────────────────────────────────────


def test_adjacent_context_appears_in_scene_block():
    """Prev and next narrations must appear in each scene's block."""
    prev_scene = _make_scene(index=1, narration="Dawn breaks over the mountains.")
    curr_scene = _make_scene(index=2, narration="The pilgrim rises and begins the climb.")
    next_scene = _make_scene(index=3, narration="Storm clouds gather at the summit.")

    block = _build_scene_block(curr_scene, prev_scene, next_scene, None)

    assert "Dawn breaks" in block
    assert "Storm clouds" in block
    assert "pilgrim" in block


def test_adjacent_context_none_when_first_last_scene():
    """First and last scenes should show 'none' for prev/next."""
    scene = _make_scene(index=1, narration="The beginning.")
    block = _build_scene_block(scene, None, None, None)
    assert "PREV_NARRATION: none" in block


# ── Scenario 4: Visual Bible continuity ──────────────────────────────────────


def test_visual_bible_appears_in_user_prompt(tmp_path):
    """Visual Bible content must be included in the user prompt sent to LLM."""
    vb = _make_visual_bible(dominant_metaphor="ocean tides")
    scene = _make_scene()
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": "Wide ocean shot."}]))

    synthesize_visual_prompts([scene], llm, visual_bible=vb)

    user_prompt = llm.generate.call_args[0][0]
    assert "ocean tides" in user_prompt
    assert "ancient forest" in user_prompt  # anchor environment
    assert "falling leaves" in user_prompt  # visual motif


def test_visual_bible_section_builder():
    """_build_visual_bible_section must include all fields."""
    vb = _make_visual_bible()
    section = _build_visual_bible_section(vb)

    assert "VISUAL BIBLE" in section
    assert "light through darkness" in section
    assert "ancient forest" in section
    assert "stone courtyard" in section
    assert "cool blue-grey" in section
    assert "falling leaves" in section
    assert "establishing_wide" in section


# ── Scenario 5: hybrid human/animal + environment styling ────────────────────


def test_synthesis_system_prompt_contains_hybrid_style():
    """The system prompt encoding hybrid style must be sent to the LLM."""
    from ytfactory.images.prompt_synthesis import _SYNTHESIS_SYSTEM_PROMPT

    assert "100% photorealistic" in _SYNTHESIS_SYSTEM_PROMPT
    assert "hand-painted" in _SYNTHESIS_SYSTEM_PROMPT or "illustrated" in _SYNTHESIS_SYSTEM_PROMPT
    assert "2D" in _SYNTHESIS_SYSTEM_PROMPT or "storybook" in _SYNTHESIS_SYSTEM_PROMPT
    # Must NOT instruct to convert the whole scene to one style
    assert "independently" in _SYNTHESIS_SYSTEM_PROMPT


def test_hybrid_style_prompt_passed_to_llm():
    """System prompt with hybrid style rules must be forwarded to LLM.generate."""
    from ytfactory.images.prompt_synthesis import _SYNTHESIS_SYSTEM_PROMPT

    vb = _make_visual_bible()
    scene = _make_scene()
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": "A forest scene."}]))

    synthesize_visual_prompts([scene], llm, visual_bible=vb)

    call_kwargs = llm.generate.call_args[1]
    assert call_kwargs.get("system_prompt") == _SYNTHESIS_SYSTEM_PROMPT


# ── Scenario 6: no invented subjects ─────────────────────────────────────────


def test_validation_does_not_flag_valid_prompt():
    """A clean prompt with no violations must produce no issues."""
    prompt = (
        "Wide shot of an empty stone courtyard bathed in golden hour light. "
        "Long shadows stretch across ancient cobblestones. No people visible. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=1, character_presence=[])
    assert issues == []


def test_validation_empty_prompt_flagged():
    issues = validate_synthesis_result("", scene_index=1, character_presence=[])
    assert any(i.check == "empty_prompt" for i in issues)


def test_validation_too_short_flagged():
    issues = validate_synthesis_result("Short.", scene_index=1, character_presence=[])
    assert any(i.check == "too_short" for i in issues)


def test_validation_too_long_flagged():
    long_prompt = " ".join(["word"] * 501)
    issues = validate_synthesis_result(long_prompt, scene_index=1, character_presence=[])
    assert any(i.check == "too_long" for i in issues)


# ── Scenario 7: no global Kai ─────────────────────────────────────────────────


def test_no_kai_marker_in_scene_block_when_no_character():
    """Scene blocks must not mention hardcoded Kai markers when character_presence is empty."""
    from ytfactory.images.prompt_synthesis import _SYNTHESIS_SYSTEM_PROMPT

    # The system prompt must not hard-code Kai
    kai_phrases = ["lean young man", "light stubble", "simple dark shirt", "KAI_COMPRESSED_SPEC"]
    for phrase in kai_phrases:
        assert phrase not in _SYNTHESIS_SYSTEM_PROMPT, f"Kai marker '{phrase}' found in system prompt"


def test_kai_injection_detected_in_environment_only_scene():
    """Kai markers in an environment-only scene (character_presence=[]) are a validation failure."""
    prompt = (
        "A lean young man with light stubble walks through the forest. "
        "Warm golden light streams through the trees."
    )
    issues = validate_synthesis_result(prompt, scene_index=3, character_presence=[])
    kai_issues = [i for i in issues if i.check == "kai_injection"]
    assert kai_issues, "Expected kai_injection issue"
    assert "lean young man" in kai_issues[0].detail or "light stubble" in kai_issues[0].detail


def test_kai_markers_allowed_when_character_listed():
    """If 'KAI' is in character_presence, Kai descriptors are expected and not flagged."""
    prompt = (
        "A lean young man with light stubble stands in the doorway. "
        "Soft candlelight illuminates simple dark shirt. 16:9 aspect ratio."
    )
    # When KAI is listed in character_presence, the injection check is skipped
    issues = validate_synthesis_result(prompt, scene_index=1, character_presence=["KAI"])
    kai_issues = [i for i in issues if i.check == "kai_injection"]
    assert not kai_issues, "Kai descriptors should NOT be flagged when KAI is in character_presence"


def test_synthesis_system_prompt_forbids_global_character_injection():
    """The system prompt must forbid injecting recurring characters not listed in CHARACTERS_PRESENT."""
    from ytfactory.images.prompt_synthesis import _SYNTHESIS_SYSTEM_PROMPT

    assert "CHARACTERS_PRESENT" in _SYNTHESIS_SYSTEM_PROMPT
    assert "global" in _SYNTHESIS_SYSTEM_PROMPT.lower() or "inject" in _SYNTHESIS_SYSTEM_PROMPT.lower()


# ── Scenario 8: no-narration scene handling ───────────────────────────────────


def test_empty_narration_shows_placeholder_in_block():
    """Scenes with no narration must include a placeholder, not be silently dropped."""
    scene = _make_scene(narration="", story_context="Interstitial environment shot.")
    block = _build_scene_block(scene, None, None, None)
    assert "(no narration)" in block
    assert "STORY_CONTEXT" in block and "Interstitial" in block


def test_no_narration_scene_still_gets_prompt():
    """synthesize_visual_prompts must still return a prompt even for narration-free scenes."""
    vb = _make_visual_bible()
    scene = _make_scene(narration="", story_context="Transition shot.")
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": "Empty forest path, golden light."}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 1 in report.prompts
    assert report.prompts[1]


# ── Scenario 9: compositor text handling ─────────────────────────────────────


def test_text_branding_directive_flagged():
    """Prompts that tell the image generator to create readable text must be flagged."""
    bad_prompt = (
        "Show the title card in large letters at the top of the frame. "
        "Include the channel logo in the corner."
    )
    issues = validate_synthesis_result(bad_prompt, scene_index=1, character_presence=[])
    text_issues = [i for i in issues if i.check == "text_branding"]
    assert text_issues, "Expected text_branding issue for 'Show the title'"


def test_clean_compositor_framing_not_flagged():
    """Prompts that leave clean space for compositor text must NOT be flagged."""
    clean_prompt = (
        "Wide establishing shot of the mountain range at dusk. "
        "Upper third deliberately left clear with soft sky gradient. "
        "No text or graphics in frame. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(clean_prompt, scene_index=1, character_presence=[])
    text_issues = [i for i in issues if i.check == "text_branding"]
    assert not text_issues


def test_meta_instruction_block_flagged():
    """Prompts with old-style metadata headers must be flagged."""
    bad_prompt = (
        "PRIMARY SUBJECT: An elder\n"
        "PRIMARY ACTION: Standing by the fire\n"
        "Warm cinematic lighting."
    )
    issues = validate_synthesis_result(bad_prompt, scene_index=1, character_presence=[])
    meta_issues = [i for i in issues if i.check == "meta_instructions"]
    assert meta_issues, "Expected meta_instructions issue"


# ── Scenario 10: continuity across recurring subjects ─────────────────────────


def test_character_spec_lookup_from_story_bible():
    """_lookup_character_spec must return appearance + clothing from the Story Bible."""
    char = CharacterEntry(
        name="Elder Miriam",
        slug="elder_miriam",
        appearance="an aged woman with silver braided hair and weathered skin",
        clothing="a dark wool cloak with a bronze clasp",
        role="guide",
    )
    bible = _make_story_bible(characters=[char])

    spec = _lookup_character_spec("elder_miriam", bible)
    assert "Elder Miriam" in spec
    assert "silver braided hair" in spec
    assert "dark wool cloak" in spec


def test_character_spec_lookup_missing_returns_id():
    """When a character ID isn't in the Story Bible, return the raw ID."""
    bible = _make_story_bible()
    spec = _lookup_character_spec("UNKNOWN_CHAR", bible)
    assert spec == "UNKNOWN_CHAR"


def test_character_spec_appears_in_scene_block():
    """Scene block must include full character spec from Story Bible."""
    char = CharacterEntry(
        name="Young Prince",
        slug="young_prince",
        appearance="tall youth with copper skin and close-cropped hair",
        clothing="simple linen tunic",
        role="protagonist",
    )
    bible = _make_story_bible(characters=[char])
    scene = _make_scene(character_presence=["young_prince"])

    block = _build_scene_block(scene, None, None, bible)

    assert "Young Prince" in block
    assert "copper skin" in block
    assert "linen tunic" in block


def test_environment_only_scene_block_has_no_character():
    """Scenes with empty character_presence must state 'environment-only' in block."""
    scene = _make_scene(character_presence=[])
    block = _build_scene_block(scene, None, None, None)
    assert "ENVIRONMENT-ONLY" in block.upper()


# ── Scenario 11: single LLM call ─────────────────────────────────────────────


def test_single_llm_call_for_small_batch():
    """For a batch of 3 scenes (below batch_size), exactly ONE LLM call must be made."""
    vb = _make_visual_bible()
    scenes = [
        _make_scene(index=i, narration=f"Scene {i} narration.")
        for i in range(1, 4)
    ]
    resp = _json_response([
        {"index": i, "visual_prompt": f"Cinematic prompt for scene {i}."}
        for i in range(1, 4)
    ])
    llm = _make_llm(resp)

    report = synthesize_visual_prompts(scenes, llm, visual_bible=vb, batch_size=10)

    assert llm.generate.call_count == 1, (
        f"Expected 1 LLM call, got {llm.generate.call_count}"
    )
    assert report.llm_call_count == 1


def test_multiple_batches_produce_correct_call_count():
    """With batch_size=2 and 5 scenes, exactly 3 LLM calls must be made (ceil(5/2)=3)."""
    vb = _make_visual_bible()
    scenes = [
        _make_scene(index=i, narration=f"Scene {i}.")
        for i in range(1, 6)
    ]

    def _side_effect(prompt, **kwargs):
        # Determine which scenes are in this batch from the user prompt
        # and return matching prompts
        indices = []
        for i in range(1, 6):
            if f"SCENE {i}" in prompt:
                indices.append(i)
        items = [{"index": i, "visual_prompt": f"Prompt {i}."} for i in indices]
        return LLMResponse(
            text=json.dumps(items),
            model="test",
            prompt_tokens=10,
            completion_tokens=20,
            finish_reason="stop",
        )

    llm = MagicMock()
    llm.generate.side_effect = _side_effect

    report = synthesize_visual_prompts(scenes, llm, visual_bible=vb, batch_size=2)

    assert llm.generate.call_count == 3
    assert report.llm_call_count == 3


# ── Scenario 12: final prompt contract ───────────────────────────────────────


def test_brand_card_scenes_excluded_from_synthesis():
    """Scenes with scene_type='brand_card' must be excluded from synthesis."""
    vb = _make_visual_bible()
    brand = _make_scene(index=1, narration="Subscribe!", scene_type="brand_card")
    gen = _make_scene(index=2, narration="A river at dusk.")
    llm = _make_llm(_json_response([{"index": 2, "visual_prompt": "River at dusk, golden hour."}]))

    report = synthesize_visual_prompts([brand, gen], llm, visual_bible=vb)

    assert 2 in report.prompts
    assert 1 not in report.prompts  # brand_card excluded
    user_prompt = llm.generate.call_args[0][0]
    assert "SCENE 2" in user_prompt
    assert "SCENE 1" not in user_prompt


def test_report_structure_is_complete():
    """SynthesisReport must have .prompts, .validation_issues, .failed_scenes, .llm_call_count."""
    vb = _make_visual_bible()
    scene = _make_scene()
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": "A forest at dawn."}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert isinstance(report, SynthesisReport)
    assert isinstance(report.prompts, dict)
    assert isinstance(report.validation_issues, list)
    assert isinstance(report.failed_scenes, list)
    assert isinstance(report.llm_call_count, int)
    assert report.llm_call_count >= 1


def test_index_remapping_when_llm_resets_indexes():
    """If LLM returns wrong indexes (e.g. 1–3 instead of 5–7), remap by position."""
    vb = _make_visual_bible()
    scenes = [_make_scene(index=i, narration=f"Scene {i}.") for i in range(5, 8)]
    # LLM incorrectly returns indexes 1–3 instead of 5–7
    llm = _make_llm(
        _json_response([
            {"index": 1, "visual_prompt": "Prompt for scene 5."},
            {"index": 2, "visual_prompt": "Prompt for scene 6."},
            {"index": 3, "visual_prompt": "Prompt for scene 7."},
        ])
    )

    report = synthesize_visual_prompts(scenes, llm, visual_bible=vb, batch_size=10)

    # Should be remapped to correct scene indexes
    assert 5 in report.prompts
    assert 6 in report.prompts
    assert 7 in report.prompts
    assert "Prompt for scene 5." in report.prompts[5]


def test_parse_synthesis_response_handles_markdown_fences():
    """_parse_synthesis_response must strip ```json ... ``` code fences."""
    batch = [_make_scene(index=1)]
    text = '```json\n[{"index": 1, "visual_prompt": "A mountain scene."}]\n```'
    result = _parse_synthesis_response(text, batch)
    assert result == {1: "A mountain scene."}


def test_parse_synthesis_response_handles_json_embedded_in_text():
    """_parse_synthesis_response must extract JSON array from prose-wrapped text."""
    batch = [_make_scene(index=2)]
    text = 'Here are the prompts:\n[{"index": 2, "visual_prompt": "Sunset over the hills."}]'
    result = _parse_synthesis_response(text, batch)
    assert result == {2: "Sunset over the hills."}


def test_parse_synthesis_response_returns_none_on_malformed():
    """_parse_synthesis_response must return None when response is unparseable."""
    batch = [_make_scene(index=1)]
    result = _parse_synthesis_response("This is not JSON at all.", batch)
    assert result is None


def test_validation_clean_prompt_no_issues():
    """A well-formed prompt with characters must pass all checks."""
    prompt = (
        "Medium shot of an illustrated young woman in a wool cloak standing at the edge of a "
        "photorealistic misty lake. Hand-painted 2D figure against the real-world fog-shrouded "
        "water. Soft morning light filters through birch trees. Muted blue-grey palette. "
        "16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=1, character_presence=["PROTAGONIST"])
    assert issues == []


def test_empty_scene_list_returns_empty_report():
    """An empty scene list must return an empty report without calling the LLM."""
    vb = _make_visual_bible()
    llm = MagicMock()
    report = synthesize_visual_prompts([], llm, visual_bible=vb)
    assert report.prompts == {}
    llm.generate.assert_not_called()


def test_all_brand_card_scenes_returns_empty_report():
    """If all scenes are brand_cards, LLM must not be called."""
    vb = _make_visual_bible()
    scenes = [_make_scene(index=i, scene_type="brand_card") for i in range(1, 4)]
    llm = MagicMock()
    report = synthesize_visual_prompts(scenes, llm, visual_bible=vb)
    assert report.prompts == {}
    llm.generate.assert_not_called()


# ── Regression: json_object mode dict-wrapping (the-power-of-relentless-focus) ──
# Root cause: json_mode=True sends response_format={"type":"json_object"} which
# causes some models (gpt-5.6-luna-pro, DeepSeek) to wrap the array in a JSON
# object like {"scenes":[...]} instead of returning a bare array. json.loads()
# succeeded but isinstance(data, list) was False → _parse_synthesis_response
# returned None for every batch → vp_map empty → all scenes used the 7-word
# title-based fallback "Cinematic wide shot, {title}, golden hour lighting...".


def test_parse_synthesis_response_handles_dict_wrapped_array():
    """Parser must unwrap {"scenes":[...]} that json_object mode produces."""
    batch = [_make_scene(index=1), _make_scene(index=2)]
    wrapped = json.dumps({
        "scenes": [
            {"index": 1, "visual_prompt": "Illustrated ant on a vast mountainside, tiny against towering peaks."},
            {"index": 2, "visual_prompt": "A bird soaring over the ant's path, photorealistic sky."},
        ]
    })
    result = _parse_synthesis_response(wrapped, batch)
    assert result is not None, "dict-wrapped array must not return None"
    assert result[1] == "Illustrated ant on a vast mountainside, tiny against towering peaks."
    assert result[2] == "A bird soaring over the ant's path, photorealistic sky."


def test_parse_synthesis_response_handles_result_key_wrapper():
    """Parser must unwrap {"result":[...]} variant."""
    batch = [_make_scene(index=5)]
    wrapped = json.dumps({
        "result": [{"index": 5, "visual_prompt": "Deep forest path, golden shafts of light."}]
    })
    result = _parse_synthesis_response(wrapped, batch)
    assert result == {5: "Deep forest path, golden shafts of light."}


def test_synthesize_does_not_use_json_mode():
    """LLM generate must not be called with json_mode=True (causes dict-wrapping)."""
    vb = _make_visual_bible()
    scene = _make_scene(
        index=1,
        narration="An ant smaller than a grain of rice climbs a mountain that would take a human a lifetime.",
    )
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": "Macro lens on a tiny ant."}]))

    synthesize_visual_prompts([scene], llm, visual_bible=vb)

    call_kwargs = llm.generate.call_args[1]
    assert not call_kwargs.get("json_mode", False), (
        "json_mode=True sends response_format={'type':'json_object'} which causes "
        "models to wrap the array in a dict, breaking _parse_synthesis_response"
    )


def test_realistic_scene_produces_substantial_synthesized_prompt():
    """Full multi-sentence narration + scene context must produce a rich final prompt.

    Regression: before the fix, all scenes received the 7-word title fallback
    'Cinematic wide shot, {title}, golden hour lighting...' because every batch
    parse returned None and vp_map stayed empty.
    """
    vb = _make_visual_bible(
        dominant_metaphor="relentless small steps",
        anchor_environments=["mountain trail", "ancient forest floor"],
        visual_motifs=["ant on a pebble", "falling leaves"],
    )
    scene = _make_scene(
        index=1,
        narration=(
            "A tiny ant—with legs smaller than a grain of rice—has decided to climb "
            "Mount Everest. Not the metaphorical version. The real one. "
            "Step by step, the ant moves forward without pausing to calculate how far it has to go."
        ),
        shot_type="extreme_close_up",
        scene_analysis={
            "environment": "rocky mountain trail at dawn",
            "primary_subject": "tiny ant",
            "emotional_beat": "quiet determination",
            "story_goal": "establish the relentless-focus theme",
        },
        story_context="Opening scene: the ant as the central metaphor for sustained, unglamorous effort.",
        assigned_beat="OPENING",
    )

    expected_prompt = (
        "Extreme close-up of a tiny illustrated ant—hand-painted 2D style with ink outlines—"
        "navigating rough grey granite at dawn. The ant's legs are barely visible against the "
        "pebble-textured surface. Photorealistic rocky mountain trail environment: early morning "
        "mist rolls in from below, cool blue-grey light catches the stone edges. The ant moves "
        "forward steadily, each leg precisely placed. No hesitation, no looking back. "
        "Depth-of-field isolates the ant against an out-of-focus mountain backdrop. "
        "Quiet determination. No text, no watermark."
    )
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": expected_prompt}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    # The synthesized prompt must be stored
    assert 1 in report.prompts, "Scene 1 must be in prompts — not in failed_scenes"
    assert report.failed_scenes == [], f"No scenes should fail; got: {report.failed_scenes}"

    stored = report.prompts[1]

    # Must be the synthesized prompt, not the fallback
    assert not stored.startswith("Cinematic wide shot,"), (
        f"Got the 7-word title fallback instead of synthesis output: {stored[:80]!r}"
    )
    # Must be substantially longer than the fallback (fallback ≈ 20 words)
    word_count = len(stored.split())
    assert word_count >= 30, f"Synthesized prompt too short ({word_count} words): {stored[:80]!r}"

    # LLM received the scene's narration
    user_prompt = llm.generate.call_args[0][0]
    assert "grain of rice" in user_prompt
    assert "Mount Everest" in user_prompt
    # LLM received scene context fields
    assert "rocky mountain trail" in user_prompt
    assert "quiet determination" in user_prompt.lower() or "emotional" in user_prompt.lower()
    # LLM received Visual Bible
    assert "relentless small steps" in user_prompt


# ── Regression: broken-join detection ─────────────────────────────────────────
# Observed in the-power-of-relentless-focus IMAGE_PROMPTS.md: prompts contained
# fragments like "through a The figure", "at the foot of an immense The repeated
# marks", "of a Leave clearly framed" — article followed by a capitalised article,
# indicating a truncated sentence merged into the next sentence's opening.


@pytest.mark.parametrize("bad_prompt", [
    # Scene 4 pattern: "at the foot of an immense The repeated marks form..."
    (
        "A lone figure stands at the foot of an immense The repeated marks form "
        "a visible ascending path toward the peak."
    ),
    # Scene 9 pattern: "moves laterally through a Their separate actions..."
    (
        "A cinematic tracking-shot composition moves laterally through a Their "
        "separate actions are connected by a continuous line."
    ),
    # Scene 19 pattern: "walking path through a The figure takes..."
    (
        "A person choosing a modest repeatable walking path through a The figure "
        "takes an ordinary measured step."
    ),
    # Scene 22 pattern: "Drone-like overhead view of a Leave clearly framed"
    (
        "Drone-like overhead view of a The clearly framed uncluttered spaces "
        "for two related-video suggestion panels."
    ),
    # Minimal article-article case
    "An illustrated ant crawls across a The massive rock surface.",
])
def test_broken_join_flagged_by_validator(bad_prompt):
    """validate_synthesis_result must flag broken article-article joins."""
    issues = validate_synthesis_result(bad_prompt, scene_index=1, character_presence=[])
    broken = [i for i in issues if i.check == "broken_join"]
    assert broken, (
        f"Expected broken_join issue for: {bad_prompt[:80]!r}\n"
        f"Got issues: {[i.check for i in issues]}"
    )


def test_clean_prompt_not_flagged_for_broken_join():
    """Well-formed prompts with 'a' before proper nouns must NOT be flagged."""
    prompt = (
        "A tiny illustrated ant crawls across a massive weathered gray rock. "
        "The ant's legs are smaller than a grain of rice. "
        "In the background a photorealistic Himalayan peak rises into the mist. "
        "An extreme wide shot establishes the impossible scale. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=1, character_presence=[])
    broken = [i for i in issues if i.check == "broken_join"]
    assert not broken, f"False positive broken_join on clean prompt: {broken}"


def test_broken_join_regex_matches_known_fragments():
    """_BROKEN_JOIN_RE must directly match the fragment patterns from real output."""
    bad_fragments = [
        "through a The figure",
        "of an immense The repeated",
        "view of a The clearly",
        "foot of a An ant",
    ]
    for fragment in bad_fragments:
        assert _BROKEN_JOIN_RE.search(fragment), (
            f"_BROKEN_JOIN_RE did not match known-bad fragment: {fragment!r}"
        )


def test_broken_join_regex_does_not_match_valid_phrases():
    """_BROKEN_JOIN_RE must not fire on valid English phrases."""
    valid_phrases = [
        "a mountain trail",
        "the ancient forest",
        "an illustrated ant",
        "the ant crosses a pebble",
        "through a narrow alpine path",
        "beside a photorealistic environment",
    ]
    for phrase in valid_phrases:
        assert not _BROKEN_JOIN_RE.search(phrase), (
            f"_BROKEN_JOIN_RE false-positive on valid phrase: {phrase!r}"
        )


# ── Regression: required subject preservation ─────────────────────────────────


def test_system_prompt_requires_narration_first():
    """System prompt must encode narration-first methodology."""
    assert "NARRATION" in _SYNTHESIS_SYSTEM_PROMPT
    assert "WHAT" in _SYNTHESIS_SYSTEM_PROMPT
    assert "HOW" in _SYNTHESIS_SYSTEM_PROMPT


def test_system_prompt_requires_visual_direction_tag():
    """System prompt must treat VISUAL_DIRECTION as primary image anchor."""
    assert "VISUAL_DIRECTION" in _SYNTHESIS_SYSTEM_PROMPT
    assert "PRIMARY" in _SYNTHESIS_SYSTEM_PROMPT or "primary" in _SYNTHESIS_SYSTEM_PROMPT


def test_visual_direction_in_narration_passes_through_to_llm():
    """[Visual:] tag content is extracted into VISUAL_DIRECTION and forwarded to the LLM."""
    vb = _make_visual_bible()
    scene = _make_scene(
        narration=(
            "So how do you stay consistent when motivation runs out? "
            "[Visual: Dramatic text animation of the Sanskrit Yoga Sutra quote, "
            "with English translations highlighting key words.]"
        )
    )
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": "Stone surface, calligraphic glow."}]))

    synthesize_visual_prompts([scene], llm, visual_bible=vb)

    user_prompt = llm.generate.call_args[0][0]
    assert "VISUAL_DIRECTION:" in user_prompt
    assert "[Visual:" not in user_prompt
    assert "Sanskrit" in user_prompt or "Yoga Sutra" in user_prompt


def test_host_on_camera_visual_direction_in_scene_block():
    """[Visual:] tag is extracted into VISUAL_DIRECTION; prose narration is separate."""
    scene = _make_scene(
        narration=(
            "[Visual: Host on camera with a clean background. Title graphic pops up.] "
            "Greatness is never built overnight."
        )
    )
    block = _build_scene_block(scene, None, None, None)
    assert "VISUAL_DIRECTION:" in block
    assert "Host on camera" in block
    assert "[Visual:" not in block
    assert "Greatness is never built overnight" in block


# ── Regression: hybrid character + environment ────────────────────────────────


def test_system_prompt_never_says_no_characters_from_style():
    """System prompt must not use 'environment only' to exclude narration-required subjects."""
    # The hybrid style section must not globally ban characters; it should only
    # instruct on how to render them (illustrated), not whether they appear.
    assert "NEVER means" in _SYNTHESIS_SYSTEM_PROMPT
    assert "no characters" in _SYNTHESIS_SYSTEM_PROMPT  # must appear as something FORBIDDEN


def test_system_prompt_illustrated_characters_in_photorealistic_env():
    """System prompt must specify hand-painted illustrated style for characters."""
    assert "hand-painted" in _SYNTHESIS_SYSTEM_PROMPT
    assert "photorealistic" in _SYNTHESIS_SYSTEM_PROMPT
    assert "independently" in _SYNTHESIS_SYSTEM_PROMPT  # styles applied independently


def test_ant_scene_narration_contains_character_in_block():
    """Scene with ant in narration must have the narration in the block for LLM."""
    scene = _make_scene(
        narration=(
            "A tiny ant—with legs smaller than a grain of rice—has decided to climb Mount Everest. "
            "[Visual: A tiny ant crawls across a massive rock, then the image expands into towering Himalayan peaks.]"
        ),
        character_presence=[],  # ant not in character_presence but IS in narration
    )
    block = _build_scene_block(scene, None, None, None)
    assert "ant" in block
    assert "Mount Everest" in block or "Himalayan" in block


# ── Regression: abstract narration ────────────────────────────────────────────


def test_system_prompt_forbids_generic_fallback():
    """System prompt must explicitly forbid generic landscape/path/mountain fallbacks."""
    prompt_lower = _SYNTHESIS_SYSTEM_PROMPT.lower()
    assert "generic" in prompt_lower
    assert "landscape" in prompt_lower or "mountain" in prompt_lower


def test_system_prompt_requires_concrete_metaphor_for_abstract():
    """System prompt must instruct use of concrete visual metaphors for abstract narration."""
    assert "abstract" in _SYNTHESIS_SYSTEM_PROMPT.lower() or "philosophical" in _SYNTHESIS_SYSTEM_PROMPT.lower()
    assert "concrete" in _SYNTHESIS_SYSTEM_PROMPT.lower()


def test_abstract_narration_passes_to_llm():
    """Abstract philosophical narration must still be passed in full to the LLM."""
    vb = _make_visual_bible()
    scene = _make_scene(
        narration=(
            "When these three come together, your skill becomes Dridhabhumih — "
            "firmly grounded, unbreakable, and permanent."
        ),
        story_context="Conceptual scene — no specific figure required.",
    )
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": "Three layered structure on a stone surface."}]))

    synthesize_visual_prompts([scene], llm, visual_bible=vb)

    user_prompt = llm.generate.call_args[0][0]
    assert "Dridhabhumih" in user_prompt
    assert "firmly grounded" in user_prompt


# ── Regression: production metadata tags ──────────────────────────────────────


def test_system_prompt_treats_engagement_tags_as_metadata():
    """System prompt must instruct that [ENGAGEMENT:*] tags are metadata, not image content."""
    assert "ENGAGEMENT" in _SYNTHESIS_SYSTEM_PROMPT
    assert "metadata" in _SYNTHESIS_SYSTEM_PROMPT.lower()


def test_engagement_tag_in_narration_excluded_from_llm():
    """[ENGAGEMENT:] scenes are pre-assigned compositor templates and must NOT be sent to the LLM."""
    vb = _make_visual_bible()
    scene = _make_scene(
        narration=(
            "[ENGAGEMENT: subscribe_promise] If this perspective stayed with you, "
            "subscribe to Atma Theory."
        )
    )
    llm = _make_llm(_json_response([]))  # LLM returns empty — engagement scenes excluded

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    # LLM must not have been called at all (all scenes were engagement scenes)
    llm.generate.assert_not_called()
    # The scene must be pre-assigned a compositor template
    assert 1 in report.prompts
    assert report.prompts[1] == _CTA_SUBSCRIBE_PLACEHOLDER


# ── Regression: no Kai injection (extended) ──────────────────────────────────


def test_system_prompt_has_no_kai_hardcoding():
    """System prompt must contain no hardcoded Kai-specific descriptors."""
    kai_forbidden = [
        "lean young man",
        "light stubble",
        "simple dark shirt",
        "plain trousers",
        "KAI_COMPRESSED_SPEC",
        "KAI",
    ]
    for marker in kai_forbidden:
        assert marker not in _SYNTHESIS_SYSTEM_PROMPT, (
            f"Kai marker {marker!r} found in synthesis system prompt"
        )


# ── Aspect ratio 16:9 hard rule ───────────────────────────────────────────────


def test_aspect_ratio_missing_is_flagged():
    """Prompts without '16:9' must be flagged with missing_aspect_ratio."""
    prompt = (
        "Wide shot of an illustrated ant crossing a photorealistic mountain trail at dawn. "
        "Cool blue-grey light, atmospheric mist, no text."
    )
    issues = validate_synthesis_result(prompt, scene_index=1, character_presence=[])
    ar_issues = [i for i in issues if i.check == "missing_aspect_ratio"]
    assert ar_issues, "Expected missing_aspect_ratio issue for prompt without '16:9'"


def test_aspect_ratio_present_not_flagged():
    """Prompts that include '16:9' must pass the aspect-ratio check."""
    prompt = (
        "Wide shot of an illustrated ant crossing a photorealistic mountain trail at dawn. "
        "Cool blue-grey light, atmospheric mist, no text. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=1, character_presence=[])
    ar_issues = [i for i in issues if i.check == "missing_aspect_ratio"]
    assert not ar_issues


def test_aspect_ratio_slash_form_accepted():
    """The '16 / 9' form must also satisfy the aspect-ratio check."""
    prompt = (
        "Cinematic medium shot, illustrated figure against a photorealistic stone wall, "
        "warm amber light, 16 / 9."
    )
    issues = validate_synthesis_result(prompt, scene_index=1, character_presence=[])
    ar_issues = [i for i in issues if i.check == "missing_aspect_ratio"]
    assert not ar_issues


def test_system_prompt_requires_16_9():
    """System prompt must instruct LLM to include '16:9 aspect ratio' in every prompt."""
    assert "16:9" in _SYNTHESIS_SYSTEM_PROMPT


def test_synthesized_prompt_without_ratio_logged_as_validation_issue():
    """synthesize_visual_prompts must log missing_aspect_ratio through validation pipeline."""
    vb = _make_visual_bible()
    scene = _make_scene(narration="A lone traveller walks the ancient road.")
    # LLM returns a prompt WITHOUT 16:9
    prompt_no_ratio = "Illustrated traveller on a photorealistic ancient road, warm light."
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": prompt_no_ratio}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 1 in report.prompts
    ar_issues = [i for i in report.validation_issues if i.check == "missing_aspect_ratio"]
    assert ar_issues, (
        "missing_aspect_ratio must appear in SynthesisReport.validation_issues "
        "when the stored prompt lacks '16:9'"
    )


# ── Regression: capital-article broken joins (IMAGE_PROMPTS.md malformed patterns) ──────────────
# Previously _BROKEN_JOIN_RE was case-sensitive for the first article group, so
# capital-A sentence starts were not caught.  These tests pin the fix.


def test_broken_join_capital_a_the_flagged():
    """'A The pages show…' must be flagged — capital A + The = broken article-article join."""
    prompt = (
        "A The pages show only non-readable marks and changing geometric arrangements, "
        "suggesting a long span of time without visible text. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=14, character_presence=[])
    assert any(i.check == "broken_join" for i in issues), (
        f"Expected broken_join for 'A The' pattern: {prompt[:60]!r}"
    )


def test_broken_join_capital_a_calm_a_flagged():
    """'A calm A tiny…' must be flagged — capital A + adjective + capital A = broken join."""
    prompt = (
        "A calm A tiny hand-painted 2D storybook ant with a fine ink outline moves steadily "
        "along a narrow granite trail. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=10, character_presence=[])
    assert any(i.check == "broken_join" for i in issues), (
        f"Expected broken_join for 'A calm A' pattern: {prompt[:60]!r}"
    )


def test_broken_join_capital_a_a_flagged():
    """'A A thin ant trail…' must be flagged — two capital-A articles = broken join."""
    prompt = (
        "A A thin ant-trail pencil line connects the pages without forming legible writing, "
        "while the mountain beyond the window stays fixed in the background. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=15, character_presence=[])
    assert any(i.check == "broken_join" for i in issues), (
        f"Expected broken_join for 'A A' pattern: {prompt[:60]!r}"
    )


def test_broken_join_ignorecase_does_not_fire_on_hyphenated_article():
    """'a a-frame cabin' must NOT trigger broken_join — hyphen prevents false positive."""
    assert not _BROKEN_JOIN_RE.search("a a-frame cabin"), (
        "False positive: 'a a-frame' should not match _BROKEN_JOIN_RE"
    )


# ── Regression: leading orphan article before preposition ──────────────────────────────────────
# Patterns like "A Above it, …", "A Behind it, …", "A At the center, …" indicate a
# truncated first sentence where only the article survived.


def test_leading_orphan_above_flagged():
    """'A Above it, an illustrated bird…' must flag leading_orphan."""
    prompt = (
        "A Above it, an illustrated bird with painterly cel-shaded feathers perches on a low "
        "rock and bends its head downward, clearly seeing the ant. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=2, character_presence=[])
    assert any(i.check == "leading_orphan" for i in issues), (
        f"Expected leading_orphan for 'A Above': {prompt[:60]!r}"
    )


def test_leading_orphan_behind_flagged():
    """'A Behind it, the window…' must flag leading_orphan."""
    prompt = (
        "A Behind it, the window opens toward the same distant snow-covered mountain range, "
        "linking ancient wisdom to the ongoing journey. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=13, character_presence=[])
    assert any(i.check == "leading_orphan" for i in issues), (
        f"Expected leading_orphan for 'A Behind': {prompt[:60]!r}"
    )


def test_leading_orphan_at_flagged():
    """'A At the center…' must flag leading_orphan."""
    prompt = (
        "A At the center, the three courses lock into one compact, firmly grounded structure "
        "that supports a narrow earth path. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=17, character_presence=[])
    assert any(i.check == "leading_orphan" for i in issues), (
        f"Expected leading_orphan for 'A At': {prompt[:60]!r}"
    )


def test_leading_orphan_regex_matches_known_bad_patterns():
    """_LEADING_ORPHAN_RE must match every observed malformed prefix from IMAGE_PROMPTS.md,
    including prepositions, adjectives, and number words."""
    bad_starts = [
        # preposition orphans (historical)
        "A Above it, an illustrated bird",
        "A Behind it, the window opens",
        "A At the center, three courses",
        "An Over the hill, a figure",
        "The In front of the mountain",
        # adjective orphan (Root Cause B — scene 13)
        "A Loose paper, stacked notebooks, and a small brass lamp surround the manuscript",
        # number-word orphan (Root Cause B — scene 17)
        "A Three subtle physical traces converge into the repeated mark",
    ]
    for text in bad_starts:
        assert _LEADING_ORPHAN_RE.search(text), (
            f"_LEADING_ORPHAN_RE did not match known-bad pattern: {text!r}"
        )


def test_leading_orphan_valid_starts_not_flagged():
    """Valid article + noun phrases must NOT fire leading_orphan."""
    valid_starts = [
        "An illustrated ant crawls across a massive weathered rock.",
        "A lone worker lays bricks in a photorealistic courtyard.",
        "The distant mountain catches first light in a cold alpine dawn.",
        "An over-the-shoulder view of a craftsperson at work.",
        "A beyond-the-horizon feeling of persistent effort.",
        "An outside perspective on the mountain trail.",
        "A forward-thinking approach to incremental progress.",
    ]
    for prompt in valid_starts:
        issues = validate_synthesis_result(
            prompt + " 16:9 aspect ratio.", scene_index=1, character_presence=[]
        )
        assert not any(i.check == "leading_orphan" for i in issues), (
            f"False positive leading_orphan on valid prompt: {prompt[:60]!r}"
        )


# ── Regression: trailing truncation ──────────────────────────────────────────────────────────


def test_trailing_truncation_bare_the_flagged():
    """Prompt ending with bare 'The' (no period) must flag trailing_truncation."""
    prompt = (
        "A tiny hand-painted 2D storybook ant pauses on a narrow granite path and faces an "
        "illustrated bird, creating the visual impression of a quiet answer. The"
    )
    issues = validate_synthesis_result(prompt, scene_index=3, character_presence=[])
    assert any(i.check == "trailing_truncation" for i in issues), (
        f"Expected trailing_truncation for prompt ending 'The': {prompt[-30:]!r}"
    )


def test_trailing_truncation_regex_matches_bare_articles():
    """_TRAILING_TRUNCATION_RE must match prompts ending with a bare article."""
    for tail in ["...bringing it closer. The", "a narrow path and a", "the summit an"]:
        assert _TRAILING_TRUNCATION_RE.search(tail), (
            f"_TRAILING_TRUNCATION_RE did not match truncated tail: {tail!r}"
        )


def test_trailing_truncation_complete_prompt_not_flagged():
    """A prompt ending properly (period, ratio) must NOT trigger trailing_truncation."""
    prompt = (
        "An illustrated ant crawls across a massive weathered rock in photorealistic alpine "
        "light. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=1, character_presence=[])
    assert not any(i.check == "trailing_truncation" for i in issues), (
        "False positive trailing_truncation on complete prompt"
    )


# ── Regression: broken prompts are removed from report.prompts ──────────────────────────────


def test_leading_orphan_prompt_rejected_from_report_prompts():
    """A leading-orphan prompt that also fails repair must land a clean placeholder in
    report.prompts (not the broken text) and be recorded in failed_scenes."""
    vb = _make_visual_bible()
    scene = _make_scene(index=2, narration="A bird observes the ant from above.")
    broken_prompt = (
        "A Above it, an illustrated bird with painterly cel-shaded feathers perches on a low "
        "rock and bends its head downward, clearly seeing and questioning the ant; both living "
        "subjects are small but legible within the immense landscape. 16:9 aspect ratio."
    )
    # _make_llm returns same broken prompt for both synthesis AND repair call
    llm = _make_llm(_json_response([{"index": 2, "visual_prompt": broken_prompt}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 2 in report.failed_scenes, "Scene with broken prompt must be in failed_scenes"
    assert 2 in report.prompts, "Failed scene must have a clean placeholder in report.prompts"
    assert report.prompts[2].startswith("Cinematic wide shot, "), "Placeholder must not contain broken text"
    assert broken_prompt not in report.prompts[2], "Broken text must not reach report.prompts"


def test_broken_join_prompt_rejected_from_report_prompts():
    """A broken-join prompt that also fails repair must land a clean placeholder in report.prompts."""
    vb = _make_visual_bible()
    scene = _make_scene(index=14, narration="The pages turn without leaving any readable marks.")
    broken_prompt = (
        "A The pages show only non-readable marks and changing geometric arrangements, "
        "suggesting a long span of time without visible text on the stone surface. "
        "16:9 aspect ratio."
    )
    llm = _make_llm(_json_response([{"index": 14, "visual_prompt": broken_prompt}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 14 in report.failed_scenes
    assert 14 in report.prompts, "Failed scene must have a clean placeholder in report.prompts"
    assert report.prompts[14].startswith("Cinematic wide shot, "), "Placeholder must not contain broken text"


def test_trailing_truncation_prompt_rejected_from_report_prompts():
    """A prompt ending with a bare article that also fails repair must land a clean placeholder."""
    vb = _make_visual_bible()
    scene = _make_scene(index=3, narration="The ant answers with a philosophy of relentless steps.")
    truncated_prompt = (
        "A tiny hand-painted 2D storybook ant pauses on a narrow granite path, its body and "
        "posture oriented toward a distant snow-covered mountain. Small footprints trail from "
        "the foreground toward the peak to express every step bringing it closer. The"
    )
    llm = _make_llm(_json_response([{"index": 3, "visual_prompt": truncated_prompt}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 3 in report.failed_scenes
    assert 3 in report.prompts, "Failed scene must have a clean placeholder in report.prompts"
    assert report.prompts[3].startswith("Cinematic wide shot, "), "Placeholder must not contain broken text"


def test_clean_prompt_not_rejected_from_report():
    """A structurally clean prompt must remain in report.prompts and not appear in failed_scenes."""
    vb = _make_visual_bible()
    scene = _make_scene(
        index=1,
        narration="A tiny ant has decided to climb Mount Everest.",
        character_presence=["ant"],
    )
    clean_prompt = (
        "A minuscule hand-painted 2D storybook ant with fine ink outlines and cel-shaded "
        "painterly detail crawls across the rough face of an immense weathered granite boulder, "
        "its legs visibly smaller than grains of rice. The ant's posture is resolute. "
        "Photorealistic Himalayan peaks rise in the background. Cool dawn light, no text. "
        "16:9 aspect ratio."
    )
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": clean_prompt}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 1 in report.prompts, "Clean prompt must remain in report.prompts"
    assert 1 not in report.failed_scenes, "Clean prompt must not be in failed_scenes"
    assert report.prompts[1] == clean_prompt, (
        "Stored prompt must be the exact value that validation inspected — no mutation"
    )


def test_validated_prompt_and_report_value_are_identical():
    """The string stored in report.prompts must be the exact string that validate_synthesis_result
    received — no post-validation prefix/suffix/field substitution must occur.  This guarantees
    that visual_prompt in scene-plan.json and IMAGE_PROMPTS.md contain the same value that
    the validation gate inspected."""
    vb = _make_visual_bible()
    scene = _make_scene(
        index=5,
        narration="Stay with this and you will see why enormous goals become possible.",
    )
    synthesized = (
        "An over-the-shoulder-style view across a worn timber desk shows a hand-drawn "
        "blueprint of tiny sequential steps climbing toward a large firmly constructed "
        "stone foundation; beside it lie stacked stones, repeated pencil strokes, and "
        "blank manuscript pages as evidence of consistency. Through a rough-plaster window "
        "the same distant mountain landscape links the blueprint to the journey. "
        "16:9 aspect ratio."
    )
    llm = _make_llm(_json_response([{"index": 5, "visual_prompt": synthesized}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 5 in report.prompts, "Scene must be in report.prompts"
    assert report.prompts[5] == synthesized, (
        f"Stored prompt differs from synthesized value.\n"
        f"Expected: {synthesized[:80]!r}\n"
        f"Got:      {report.prompts.get(5, '')[:80]!r}"
    )


# ── Regression: adjective and number orphans caught by structural leading-orphan check ──


def test_leading_orphan_loose_adjective_flagged():
    """'A Loose paper, …' must flag leading_orphan — adjective at sentence start after orphaned article."""
    prompt = (
        "A Loose paper, stacked notebooks, and a small brass lamp surround the manuscript; "
        "no readable text, logos, or modern typography. Profile-oriented cinematic composition "
        "with a shallow focus plane across the page. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=13, character_presence=[])
    assert any(i.check == "leading_orphan" for i in issues), (
        f"Expected leading_orphan for 'A Loose': {prompt[:60]!r}"
    )


def test_leading_orphan_number_word_flagged():
    """'A Three subtle physical traces…' must flag leading_orphan — number word after orphaned article."""
    prompt = (
        "A Three subtle physical traces converge into it: a long calendar-mark path, "
        "a continuous thread-like line across the table, and a carefully repeated row "
        "of identical practice marks, all rendered without readable text. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=17, character_presence=[])
    assert any(i.check == "leading_orphan" for i in issues), (
        f"Expected leading_orphan for 'A Three': {prompt[:60]!r}"
    )


# ── Regression: engagement/CTA scenes receive compositor-aware templates ─────────────────


def test_engagement_subscribe_scene_gets_compositor_template():
    """A scene whose narration starts with [ENGAGEMENT: subscribe…] must receive the
    compositor subscribe placeholder — the LLM must NOT be called for it."""
    vb = _make_visual_bible()
    scene = _make_scene(
        index=21,
        narration="[ENGAGEMENT: subscribe_promise] If this stayed with you, subscribe.",
    )
    llm = _make_llm(_json_response([]))  # LLM returns nothing (should not be called for scene 21)

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 21 in report.prompts, "Engagement scene must have a compositor template in report.prompts"
    assert report.prompts[21] == _CTA_SUBSCRIBE_PLACEHOLDER
    assert 21 not in report.failed_scenes, "Pre-assigned template is intentional, not a failure"
    llm.generate.assert_not_called()


def test_engagement_endscreen_scene_gets_compositor_template():
    """A scene whose narration starts with [ENGAGEMENT: branding_end] must receive the
    end-screen placeholder — the LLM must NOT be called for it."""
    vb = _make_visual_bible()
    scene = _make_scene(
        index=22,
        narration="[ENGAGEMENT: branding_end] [End Screen: Related video suggestions.]",
    )
    llm = _make_llm(_json_response([]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 22 in report.prompts
    assert report.prompts[22] == _CTA_ENDSCREEN_PLACEHOLDER
    assert 22 not in report.failed_scenes
    llm.generate.assert_not_called()


def test_engagement_re_matches_known_narration_prefixes():
    """_ENGAGEMENT_RE must match the exact narration prefixes used in CTA scenes."""
    bad_narrations = [
        "[ENGAGEMENT: subscribe_promise] If this perspective stayed with you…",
        "[ENGAGEMENT: branding_end] [End Screen: Related video suggestions…]",
        "[ENGAGEMENT: cta_outro] Thanks for watching.",
    ]
    for narration in bad_narrations:
        assert _ENGAGEMENT_RE.match(narration), (
            f"_ENGAGEMENT_RE did not match CTA narration prefix: {narration[:60]!r}"
        )


# ── REGRESSION: the core invariant — no invalid or stale prompt can reach report.prompts ─


def test_blocked_prompt_rejected_after_failed_repair():
    """REGRESSION GATE: any prompt that fails a blocking check AND whose repair also fails
    must land a clean placeholder in report.prompts (never the broken text) and be recorded
    in failed_scenes.  vp_map always has a usable entry; the broken text never reaches export."""
    vb = _make_visual_bible()

    broken_prompts = {
        5: "A calm composition through a The broken join here. 16:9 aspect ratio.",
        13: "A Loose paper, stacked notebooks, and a small brass lamp. 16:9 aspect ratio.",
        22: "",
    }

    # First LLM call (synthesis) returns broken prompts.
    # Second LLM call (repair) also returns broken prompts — repair fails.
    llm = MagicMock()
    llm.generate.side_effect = [
        LLMResponse(
            text=_json_response([
                {"index": 5, "visual_prompt": broken_prompts[5]},
                {"index": 13, "visual_prompt": broken_prompts[13]},
                {"index": 22, "visual_prompt": broken_prompts[22]},
            ]),
            model="test-model", prompt_tokens=10, completion_tokens=50, finish_reason="stop",
        ),
        # Repair call — returns still-broken prompts
        LLMResponse(
            text=_json_response([
                {"index": 5, "visual_prompt": broken_prompts[5]},   # still broken
                {"index": 13, "visual_prompt": broken_prompts[13]}, # still broken
                {"index": 22, "visual_prompt": ""},                  # still empty
            ]),
            model="test-model", prompt_tokens=10, completion_tokens=50, finish_reason="stop",
        ),
    ]

    report = synthesize_visual_prompts(
        [
            _make_scene(index=5, narration="The focus holds through a smooth workflow."),
            _make_scene(index=13, narration="Paper and notebooks on a worn desk."),
            _make_scene(index=22, narration="End scene."),
        ],
        llm,
        visual_bible=vb,
    )

    for idx in (5, 13, 22):
        assert idx in report.failed_scenes, f"Scene {idx} must be in failed_scenes"
        assert idx in report.prompts, f"Scene {idx} must have a clean placeholder in report.prompts"
        assert report.prompts[idx].startswith("Cinematic wide shot, "), (
            f"Scene {idx} placeholder must not contain broken text"
        )
    # Two LLM calls total: 1 synthesis + 1 repair
    assert llm.generate.call_count == 2


# ── New hardening tests ───────────────────────────────────────────────────────


# 1. Non-compositor engagement types go through LLM
def test_value_promise_engagement_goes_through_llm():
    """[ENGAGEMENT: value_promise] has real narration content and must go through LLM synthesis,
    NOT be pre-assigned a compositor template."""
    vb = _make_visual_bible()
    scene = _make_scene(
        index=5,
        narration=(
            "[ENGAGEMENT: value_promise] Stay with this, and you'll see why enormous goals "
            "become possible through tiny, unbroken steps."
        ),
    )
    synthesized = "Illustrated ant trail across stone surface, warm amber light, 16:9 aspect ratio."
    llm = _make_llm(_json_response([{"index": 5, "visual_prompt": synthesized}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    llm.generate.assert_called_once()  # LLM must be called for this scene
    assert 5 in report.prompts
    assert report.prompts[5] == synthesized
    assert 5 not in report.failed_scenes


def test_journey_invitation_engagement_goes_through_llm():
    """[ENGAGEMENT: journey_invitation] is not a compositor CTA type — goes through LLM."""
    vb = _make_visual_bible()
    scene = _make_scene(
        index=10,
        narration=(
            "[ENGAGEMENT: journey_invitation] Atma Theory returns each week to one idea "
            "that explains something your mind already does."
        ),
    )
    synthesized = "Rustic workroom desk with handwritten notes, warm lamp, 16:9 aspect ratio."
    llm = _make_llm(_json_response([{"index": 10, "visual_prompt": synthesized}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    llm.generate.assert_called_once()
    assert 10 in report.prompts
    assert report.prompts[10] == synthesized


def test_compositor_cta_types_are_only_subscribe_and_branding():
    """Only subscribe_promise and branding_end should receive compositor templates.
    All other engagement types go through LLM."""
    assert "subscribe_promise" in _COMPOSITOR_CTA_TYPES
    assert "branding_end" in _COMPOSITOR_CTA_TYPES
    # These common engagement types must NOT be in the set
    for non_compositor in ("value_promise", "journey_invitation", "cta_outro", "hook", "teaser"):
        assert non_compositor not in _COMPOSITOR_CTA_TYPES, (
            f"'{non_compositor}' should not be a compositor CTA type — it has real narration content"
        )


# 2. Anchor environments
def test_anchor_environments_in_system_prompt_section():
    """The synthesis system prompt must instruct the LLM on how to use anchor environments."""
    assert "ANCHOR ENVIRONMENTS" in _SYNTHESIS_SYSTEM_PROMPT
    assert "anchor" in _SYNTHESIS_SYSTEM_PROMPT.lower()
    # Must mention continuity use
    assert "continuity" in _SYNTHESIS_SYSTEM_PROMPT.lower() or "recurring" in _SYNTHESIS_SYSTEM_PROMPT.lower()


def test_anchor_environments_in_user_prompt():
    """Anchor environments from VisualBible must appear in the user prompt sent to LLM."""
    vb = _make_visual_bible(anchor_environments=["vast alpine landscape", "rustic workroom"])
    scene = _make_scene()
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": "Wide shot, 16:9 aspect ratio."}]))

    synthesize_visual_prompts([scene], llm, visual_bible=vb)

    user_prompt = llm.generate.call_args[0][0]
    assert "vast alpine landscape" in user_prompt
    assert "rustic workroom" in user_prompt


def test_anchor_environments_in_coverage_contract_reminder():
    """The per-batch user prompt must remind the LLM to use anchor environments."""
    vb = _make_visual_bible(anchor_environments=["stone courtyard", "mountain trail"])
    scene = _make_scene()
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": "Stone courtyard shot, 16:9 aspect ratio."}]))

    synthesize_visual_prompts([scene], llm, visual_bible=vb)

    user_prompt = llm.generate.call_args[0][0]
    assert "anchor environment" in user_prompt.lower()


# 3. Repair mechanism
def test_repair_called_once_for_blocking_failures():
    """When a blocking validation failure occurs, the LLM must be called exactly twice:
    once for synthesis and once for repair — no more."""
    vb = _make_visual_bible()
    scene = _make_scene(index=1, narration="The ant moves steadily up the mountain path.")
    broken = "A The ant moves across the a The rocky path. 16:9 aspect ratio."
    repaired = (
        "A hand-painted 2D storybook ant with fine ink outlines and cel-shaded legs moves "
        "steadily across a narrow rocky mountain path, Himalayan peaks in the photorealistic "
        "background, warm dawn light, no text, no watermark. 16:9 aspect ratio."
    )

    llm = MagicMock()
    llm.generate.side_effect = [
        LLMResponse(
            text=_json_response([{"index": 1, "visual_prompt": broken}]),
            model="test-model", prompt_tokens=10, completion_tokens=50, finish_reason="stop",
        ),
        LLMResponse(
            text=_json_response([{"index": 1, "visual_prompt": repaired}]),
            model="test-model", prompt_tokens=10, completion_tokens=80, finish_reason="stop",
        ),
    ]

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert llm.generate.call_count == 2, "Exactly 2 LLM calls: 1 synthesis + 1 repair"
    assert 1 not in report.failed_scenes, "Successfully repaired scene must NOT be in failed_scenes"
    assert report.prompts[1] == repaired, "Repaired prompt must be used in report.prompts"


def test_repair_passes_uses_repaired_prompt():
    """When repair produces a valid prompt, that prompt (not a placeholder) must be exported."""
    vb = _make_visual_bible()
    scene = _make_scene(index=7, narration="A stone carved by a river over ten thousand years.")
    broken = "A Above the riverbank, time erodes the stone The carved face emerges. 16:9 aspect ratio."
    repaired = (
        "Close-up photorealistic shot of a smooth river-worn stone resting on the bank; "
        "the surface shows gradual erosion marks representing ten thousand years of flowing water; "
        "shallow depth of field, cool morning light, no text. 16:9 aspect ratio."
    )

    llm = MagicMock()
    llm.generate.side_effect = [
        LLMResponse(
            text=_json_response([{"index": 7, "visual_prompt": broken}]),
            model="test-model", prompt_tokens=10, completion_tokens=50, finish_reason="stop",
        ),
        LLMResponse(
            text=_json_response([{"index": 7, "visual_prompt": repaired}]),
            model="test-model", prompt_tokens=10, completion_tokens=80, finish_reason="stop",
        ),
    ]

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert report.prompts[7] == repaired
    assert 7 not in report.failed_scenes
    assert report.llm_call_count == 2


def test_repair_failure_scene_in_failed_scenes_rejected_from_prompts():
    """When repair also fails, scene must be in failed_scenes and a clean placeholder must be
    stored in report.prompts — the broken text must never reach the vp_map."""
    vb = _make_visual_bible()
    scene = _make_scene(index=3, narration="A contemplative pause in the middle of the path.")
    broken = "A The pause deepens. 16:9 aspect ratio."

    llm = MagicMock()
    llm.generate.side_effect = [
        LLMResponse(
            text=_json_response([{"index": 3, "visual_prompt": broken}]),
            model="test-model", prompt_tokens=10, completion_tokens=50, finish_reason="stop",
        ),
        # Repair returns same broken prompt — still fails
        LLMResponse(
            text=_json_response([{"index": 3, "visual_prompt": broken}]),
            model="test-model", prompt_tokens=10, completion_tokens=50, finish_reason="stop",
        ),
    ]

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 3 in report.failed_scenes
    assert 3 in report.prompts, "Failed scene must have a clean placeholder in report.prompts"
    assert report.prompts[3].startswith("Cinematic wide shot, "), "Placeholder must not contain broken text"
    assert llm.generate.call_count == 2


# 4. Repair prompt structure
def test_repair_system_prompt_exists_and_has_key_rules():
    """_REPAIR_SYSTEM_PROMPT must exist and cover the essential repair rules."""
    assert _REPAIR_SYSTEM_PROMPT, "Repair system prompt must not be empty"
    assert "16:9" in _REPAIR_SYSTEM_PROMPT
    assert "BROKEN_PROMPT" in _REPAIR_SYSTEM_PROMPT
    assert "NARRATION" in _REPAIR_SYSTEM_PROMPT
    assert "JSON" in _REPAIR_SYSTEM_PROMPT


# 5. Provider label (factory function)
def test_get_provider_label_returns_provider_and_model():
    """get_provider_label must return 'provider/model' using the settings model field."""
    from unittest.mock import MagicMock as _MM
    from video_core.providers.llm.factory import get_provider_label

    settings = _MM()
    settings.llm_provider = "anthropic"
    settings.anthropic_model = "claude-haiku-4-5-20251001"
    label = get_provider_label(settings)
    assert label == "anthropic/claude-haiku-4-5-20251001"


def test_get_provider_label_gemini():
    """get_provider_label must use gemini_text_model for the gemini provider."""
    from unittest.mock import MagicMock as _MM
    from video_core.providers.llm.factory import get_provider_label

    settings = _MM()
    settings.llm_provider = "gemini"
    settings.gemini_text_model = "gemini-2.5-flash"
    label = get_provider_label(settings)
    assert label == "gemini/gemini-2.5-flash"


def test_get_provider_label_unknown_provider_no_model_field():
    """get_provider_label falls back to just the provider name when no model field is known."""
    from unittest.mock import MagicMock as _MM
    from video_core.providers.llm.factory import get_provider_label

    settings = _MM()
    settings.llm_provider = "unknownprovider"
    label = get_provider_label(settings)
    assert label == "unknownprovider"


# 6. Final export invariant: exported prompt equals the validated prompt
def test_final_exported_prompt_equals_validated_prompt():
    """report.prompts[idx] must equal the clean prompt that passed validation — no silent substitution."""
    vb = _make_visual_bible()
    scene = _make_scene(index=4, narration="The ant builds its path one grain at a time.")
    clean = (
        "Extreme close-up of a hand-painted 2D storybook ant carrying a single grain of sand "
        "along a photorealistic stone surface; each tiny step leaves a faint imprint trail; "
        "warm amber side-lighting, no text. 16:9 aspect ratio."
    )
    llm = _make_llm(_json_response([{"index": 4, "visual_prompt": clean}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert report.prompts[4] == clean, (
        "Exported prompt must exactly equal what passed validation — no post-validation modification"
    )
    assert 4 not in report.failed_scenes
    # No repair should be attempted for a clean prompt
    assert llm.generate.call_count == 1


# ── Regression: mid-sentence splice (lowercase article + capitalised sentence-starter) ──
#
# Four patterns observed in IMAGE_PROMPTS.md that must never reach final export:
#   scene 5:  "a On the desk"          — gap in prior validator (new _MID_SENTENCE_SPLICE_RE)
#   scene 10: "a winding The notebook" — caught by existing _BROKEN_JOIN_RE
#   scene 14: "A The seedling"         — caught by existing _BROKEN_JOIN_RE / _LEADING_ORPHAN_RE
#   scene 17: "A No text is visible"   — caught by existing _LEADING_ORPHAN_RE
# All four are regression-tested here so the full family can never silently regress.


def test_mid_sentence_splice_a_on_flagged():
    """'looking down at a On the desk…' (scene 5, IMAGE_PROMPTS.md) must flag mid_sentence_splice."""
    prompt = (
        "Over-the-shoulder cinematic view from behind an unseen observer looking down "
        "at a On the desk lies a physical blueprint-like arrangement of small connected "
        "stone steps and incremental marks. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=5, character_presence=[])
    assert any(i.check == "mid_sentence_splice" for i in issues), (
        f"Expected mid_sentence_splice for 'a On': {prompt[:80]!r}"
    )


def test_mid_sentence_splice_a_winding_the_caught():
    """'a winding The notebook…' (scene 10) must be flagged — broken_join covers article-article."""
    prompt = (
        "Static contemplative cinematic composition: a winding The notebook pages "
        "are blank or marked only with abstract non-readable lines. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=10, character_presence=[])
    blocking = {i.check for i in issues} & {"broken_join", "mid_sentence_splice"}
    assert blocking, (
        f"Expected a blocking issue for 'a winding The', got checks: "
        f"{[i.check for i in issues]} — prompt: {prompt[:80]!r}"
    )


def test_leading_orphan_a_the_seedling_caught():
    """'A The seedling…' (scene 14) must be flagged — leading_orphan and broken_join cover 'A The'."""
    prompt = (
        "A The seedling's roots visibly deepen through layered soil, making long-term "
        "practice taking root clear rather than showing an instant transformation. "
        "16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=14, character_presence=[])
    blocking = {i.check for i in issues} & {"leading_orphan", "broken_join"}
    assert blocking, (
        f"Expected leading_orphan or broken_join for 'A The', got: {[i.check for i in issues]}"
    )


def test_leading_orphan_a_no_text_caught():
    """'A No text is visible…' (scene 17) must flag leading_orphan — capital A + No."""
    prompt = (
        "A No text is visible; the image communicates long duration, uninterrupted "
        "continuity, and sincere care through the physical construction. "
        "16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=17, character_presence=[])
    assert any(i.check == "leading_orphan" for i in issues), (
        f"Expected leading_orphan for 'A No': {prompt[:80]!r}"
    )


def test_mid_sentence_splice_regex_matches_known_patterns():
    """_MID_SENTENCE_SPLICE_RE must directly match the exact fragment patterns from IMAGE_PROMPTS.md."""
    bad_fragments = [
        "looking down at a On the desk",
        "surrounded by a No visible text",
        "seen through a In the window",
        "placed on a Not the usual surface",
        "framed by a At the far end",
        "described as a Without any text",
    ]
    for text in bad_fragments:
        assert _MID_SENTENCE_SPLICE_RE.search(text), (
            f"_MID_SENTENCE_SPLICE_RE did not match known-bad fragment: {text!r}"
        )


def test_mid_sentence_splice_regex_no_false_positives():
    """_MID_SENTENCE_SPLICE_RE must not fire on valid English noun phrases."""
    valid_phrases = [
        "a New York skyline",
        "the Amazon rainforest",
        "an Oxford graduate",
        "a Buddhist temple",
        "a Himalayan ridge",
        "through an In-depth analysis",   # hyphen guard: In-depth
        "a no-brainer approach",          # lowercase no + hyphen
        "the not-so-subtle method",       # lowercase not + hyphen
        "a narrow path on a ridge",       # lowercase on (preposition, not capitalised)
        "the art on a stone surface",     # lowercase on mid-sentence
        "a small brass lamp at the edge", # lowercase at
    ]
    for phrase in valid_phrases:
        assert not _MID_SENTENCE_SPLICE_RE.search(phrase), (
            f"_MID_SENTENCE_SPLICE_RE false positive on valid phrase: {phrase!r}"
        )


def test_mid_sentence_splice_is_a_blocking_check():
    """mid_sentence_splice must be in _BLOCKING_CHECKS so the scene is sent for repair."""
    from ytfactory.images.prompt_synthesis import _BLOCKING_CHECKS
    assert "mid_sentence_splice" in _BLOCKING_CHECKS


def test_mid_sentence_splice_triggers_repair_and_accepts_clean_result():
    """A prompt with 'a On' splice must be repaired; if repair returns clean prompt, use it."""
    vb = _make_visual_bible()
    scene = _make_scene(index=5, narration="The focus rests on the completed foundation.")
    broken_prompt = (
        "Over-the-shoulder cinematic view looking down at a On the desk lies "
        "a blueprint arrangement. 16:9 aspect ratio."
    )
    repaired_prompt = (
        "Over-the-shoulder cinematic view looking down at the worn wooden desk; "
        "a physical blueprint arrangement of small connected stone steps sits at the center. "
        "16:9 aspect ratio."
    )
    llm = MagicMock()
    llm.generate.side_effect = [
        LLMResponse(
            text=_json_response([{"index": 5, "visual_prompt": broken_prompt}]),
            model="test", prompt_tokens=10, completion_tokens=50, finish_reason="stop",
        ),
        LLMResponse(
            text=_json_response([{"index": 5, "visual_prompt": repaired_prompt}]),
            model="test", prompt_tokens=10, completion_tokens=50, finish_reason="stop",
        ),
    ]

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert llm.generate.call_count == 2, "Repair LLM call must be made for blocking splice"
    assert report.prompts[5] == repaired_prompt, (
        f"Repaired prompt must be used, got: {report.prompts.get(5, '')[:80]!r}"
    )
    assert 5 not in report.failed_scenes


def test_mid_sentence_splice_failed_repair_rejects_scene():
    """If repair also returns a broken prompt, a clean placeholder must be stored in
    report.prompts — the broken text must never reach export."""
    vb = _make_visual_bible()
    scene = _make_scene(index=5, narration="The focus rests on the completed foundation.")
    broken_prompt = (
        "Cinematic view looking down at a On the desk lies a blueprint. 16:9 aspect ratio."
    )
    llm = MagicMock()
    llm.generate.side_effect = [
        LLMResponse(
            text=_json_response([{"index": 5, "visual_prompt": broken_prompt}]),
            model="test", prompt_tokens=10, completion_tokens=50, finish_reason="stop",
        ),
        LLMResponse(
            text=_json_response([{"index": 5, "visual_prompt": broken_prompt}]),
            model="test", prompt_tokens=10, completion_tokens=50, finish_reason="stop",
        ),
    ]

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    assert 5 in report.failed_scenes, "Scene must be in failed_scenes after repair failure"
    assert 5 in report.prompts, "Failed scene must have a clean placeholder in report.prompts"
    assert report.prompts[5].startswith("Cinematic wide shot, "), "Placeholder must not contain broken text"


# ── get_provider_label_for_role: role-aware model resolution ──────────────────


def test_get_provider_label_for_role_uses_role_model():
    """get_provider_label_for_role must prefer the role-specific model field over provider default."""
    from unittest.mock import MagicMock as _MM
    from video_core.providers.llm.factory import get_provider_label_for_role

    settings = _MM()
    settings.llm_provider = "anthropic"
    settings.anthropic_model = "deepseek/deepseek-v4-flash"
    settings.scene_planner_model = "gpt-5.6-luna-pro"
    settings.llm_default_model = ""
    label = get_provider_label_for_role(settings, "scene_planner")
    assert label == "anthropic/gpt-5.6-luna-pro", (
        f"Expected role model to take priority, got: {label!r}"
    )


def test_get_provider_label_for_role_falls_back_to_default_model():
    """get_provider_label_for_role must use llm_default_model when no role-specific model is set."""
    from unittest.mock import MagicMock as _MM
    from video_core.providers.llm.factory import get_provider_label_for_role

    settings = _MM()
    settings.llm_provider = "anthropic"
    settings.anthropic_model = "deepseek/deepseek-v4-flash"
    settings.scene_planner_model = ""
    settings.llm_default_model = "gpt-5.6-luna-pro"
    label = get_provider_label_for_role(settings, "scene_planner")
    assert label == "anthropic/gpt-5.6-luna-pro"


def test_get_provider_label_for_role_falls_back_to_provider_model():
    """get_provider_label_for_role falls back to provider-specific model when no override exists."""
    from unittest.mock import MagicMock as _MM
    from video_core.providers.llm.factory import get_provider_label_for_role

    settings = _MM()
    settings.llm_provider = "anthropic"
    settings.anthropic_model = "deepseek/deepseek-v4-flash"
    settings.scene_planner_model = ""
    settings.llm_default_model = ""
    label = get_provider_label_for_role(settings, "scene_planner")
    assert label == "anthropic/deepseek/deepseek-v4-flash"


# ── Regression: 7 confirmed malformed prompts (the-power-of-relentless-focus) ──
# Each test verifies the SPECIFIC validator that should catch the pattern, so
# future changes to a validator immediately surface which class of malformation
# they risk missing.  Tests are deterministic (no LLM call).

_MALFORMED_PROMPTS: list[tuple[str, str, str]] = [
    # (scene_label, broken_prompt_fragment, expected_check)
    (
        "scene-04 broken_join 'A tight The'",
        "A tight The hand-painted 2D storybook ant is visible among the nearest marks, "
        "still moving forward with ink-outlined legs, 16:9 aspect ratio",
        "broken_join",
    ),
    (
        "scene-05 broken_join 'the The'",
        "Inside the The composition makes the foundation visibly accumulate piece by piece "
        "toward a distant open window, 16:9 aspect ratio",
        "broken_join",
    ),
    (
        "scene-14 broken_join 'A The'",
        "A The calendar, hand, and accumulating pages lead toward a narrow ascending line "
        "formed by the table grain and a distant mountain trail, 16:9 aspect ratio",
        "broken_join",
    ),
    (
        "scene-15 broken_join 'A A'",
        "A A single narrow path of light leads from the gap back into the ongoing sequence, "
        "visually showing return rather than perfection, 16:9 aspect ratio",
        "broken_join",
    ),
    (
        "scene-16 broken_join 'The A' mid-sentence",
        "Close-up of a pair of hands performing one modest craft task with complete attention: "
        "fingers align a small piece precisely and return to correct it rather than rushing. "
        "The A single amber window beam isolates the hands against cool umber shadows, "
        "creating a quiet pool of sincerity and reverence, 16:9 aspect ratio",
        "broken_join",
    ),
]


@pytest.mark.parametrize("label,prompt,expected_check", _MALFORMED_PROMPTS)
def test_validator_catches_confirmed_broken_join(label, prompt, expected_check):
    """validate_synthesis_result must flag each confirmed broken-join pattern."""
    issues = validate_synthesis_result(prompt, scene_index=99, character_presence=[])
    checks_found = [i.check for i in issues]
    assert expected_check in checks_found, (
        f"[{label}]\n"
        f"  Expected validator to flag {expected_check!r}\n"
        f"  Got checks: {checks_found}\n"
        f"  Prompt: {prompt[:120]!r}"
    )


def test_broken_join_regex_matches_article_article_at_start():
    """_BROKEN_JOIN_RE must match article followed immediately by another article."""
    assert _BROKEN_JOIN_RE.search("A The calendar"), "'A The' not matched"
    assert _BROKEN_JOIN_RE.search("A A single"), "'A A' not matched"
    assert _BROKEN_JOIN_RE.search("an An unexpected"), "'an An' not matched"


def test_broken_join_regex_matches_article_optional_word_article():
    """_BROKEN_JOIN_RE must match article + one-word adjective + article."""
    assert _BROKEN_JOIN_RE.search("A tight The hand-painted"), "'A tight The' not matched"
    assert _BROKEN_JOIN_RE.search("Inside the The composition"), "'the The' not matched"


def test_broken_join_regex_matches_mid_sentence():
    """_BROKEN_JOIN_RE must match broken joins that appear mid-sentence (not just at start)."""
    assert _BROKEN_JOIN_RE.search(
        "fingers align a small piece precisely. The A single amber window beam"
    ), "mid-sentence 'The A' not matched"


def test_broken_join_regex_no_false_positive_valid_determiner():
    """_BROKEN_JOIN_RE must not match determiner + normal adjective."""
    # 'The careful craftsman' — 'careful' is an adjective, not another article
    assert not _BROKEN_JOIN_RE.search("The careful craftsman creates"), (
        "false positive: 'The careful' should not match"
    )
    # 'a single' is valid (single is not an article)
    assert not _BROKEN_JOIN_RE.search("a single thread of light"), (
        "false positive: 'a single thread' should not match"
    )


# ── validate_and_repair_cached: unit tests ────────────────────────────────────


def test_validate_and_repair_cached_no_issues_returns_unchanged():
    """validate_and_repair_cached must return (scenes, False) when all prompts are clean."""
    from ytfactory.images.prompt_synthesis import validate_and_repair_cached

    scenes = [
        _make_scene(
            index=1,
            narration="A stone wall rises at dawn.",
            visual_prompt=(
                "Wide establishing shot: rough stone wall rising from alpine earth at dawn, "
                "cinematic directional light, no text, no watermark, 16:9 aspect ratio"
            ),
        )
    ]
    llm = MagicMock()
    updated, repaired = validate_and_repair_cached(scenes, llm)

    assert repaired is False, "repaired should be False when no issues detected"
    assert updated[0]["visual_prompt"] == scenes[0]["visual_prompt"], (
        "visual_prompt must be unchanged when no issues"
    )
    llm.generate.assert_not_called()


def test_validate_and_repair_cached_repairs_broken_join():
    """validate_and_repair_cached must call repair LLM and update visual_prompt."""
    from ytfactory.images.prompt_synthesis import validate_and_repair_cached

    broken_prompt = (
        "A tight The hand-painted 2D storybook ant moves forward across granite, "
        "determined, 16:9 aspect ratio"
    )
    fixed_prompt = (
        "A hand-painted 2D storybook ant moves forward across rough granite, "
        "determined, cinematic directional light, 16:9 aspect ratio"
    )
    scenes = [
        _make_scene(
            index=4,
            narration="Small actions repeated long after the excitement has disappeared.",
            visual_prompt=broken_prompt,
        )
    ]
    llm = _make_llm(_json_response([{"index": 4, "visual_prompt": fixed_prompt}]))

    updated, repaired = validate_and_repair_cached(scenes, llm)

    assert repaired is True, "repaired must be True when a scene was fixed"
    result_vp = updated[0]["visual_prompt"]
    assert result_vp == fixed_prompt, (
        f"visual_prompt must equal the repaired value\n"
        f"  Expected: {fixed_prompt!r}\n"
        f"  Got:      {result_vp!r}"
    )
    # Repair LLM was called exactly once
    assert llm.generate.call_count == 1, (
        f"Expected exactly 1 LLM call, got {llm.generate.call_count}"
    )
    # The repair call received the broken prompt
    repair_call_args = llm.generate.call_args[0][0]
    assert "BROKEN_PROMPT" in repair_call_args, "Repair prompt must include BROKEN_PROMPT"
    assert "broken_join" in repair_call_args, "Repair prompt must include the issue name"


def test_validate_and_repair_cached_rejects_when_repair_still_broken():
    """validate_and_repair_cached must REJECT (clear to '') when repair LLM output is also broken.

    No unvalidated fallback may reach export — rejection clears visual_prompt so nothing
    malformed appears in IMAGE_PROMPTS.md.
    """
    from ytfactory.images.prompt_synthesis import validate_and_repair_cached

    broken_prompt = (
        "A tight The hand-painted ant moves forward, 16:9 aspect ratio"
    )
    still_broken_after_repair = (
        "A The same broken join persists in repaired output, 16:9 aspect ratio"
    )
    narration = "Small persistent actions."
    scenes = [
        _make_scene(
            index=5,
            narration=narration,
            visual_prompt=broken_prompt,
        )
    ]
    llm = _make_llm(_json_response([{"index": 5, "visual_prompt": still_broken_after_repair}]))

    updated, repaired = validate_and_repair_cached(scenes, llm)

    assert repaired is True, "repaired must be True (scene was touched)"
    result_vp = updated[0]["visual_prompt"]
    # still_broken writes a safe placeholder, not empty string
    assert result_vp, "rejected scene must have a non-empty placeholder prompt"
    assert "tight The" not in result_vp, "broken prompt fragment must not survive rejection"


def test_validate_and_repair_cached_skips_brand_card_scenes():
    """validate_and_repair_cached must not attempt to validate brand_card scenes."""
    from ytfactory.images.prompt_synthesis import validate_and_repair_cached

    scenes = [
        {
            "index": 22,
            "scene_type": "brand_card",
            "narration": "End screen",
            "visual_prompt": "",  # intentionally empty — brand cards have no LLM prompt
            "character_presence": [],
        }
    ]
    llm = MagicMock()
    updated, repaired = validate_and_repair_cached(scenes, llm)

    assert repaired is False, "brand_card scenes must not trigger repair"
    llm.generate.assert_not_called()


def test_validate_and_repair_cached_multi_scene_one_llm_call():
    """validate_and_repair_cached must send all broken scenes in ONE LLM call."""
    from ytfactory.images.prompt_synthesis import validate_and_repair_cached

    def _broken(idx: int) -> str:
        return f"A tight The hand-painted scene {idx}, 16:9 aspect ratio"

    def _fixed(idx: int) -> str:
        return f"Hand-painted scene {idx} with cinematic light, 16:9 aspect ratio"

    scenes = [
        _make_scene(index=i, narration=f"Scene {i} narration.", visual_prompt=_broken(i))
        for i in [4, 5, 14]
    ]
    llm = _make_llm(
        _json_response([{"index": i, "visual_prompt": _fixed(i)} for i in [4, 5, 14]])
    )

    updated, repaired = validate_and_repair_cached(scenes, llm)

    assert repaired is True
    assert llm.generate.call_count == 1, (
        f"Must use ONE LLM call for all broken scenes, got {llm.generate.call_count}"
    )
    for scene in updated:
        idx = scene["index"]
        assert scene["visual_prompt"] == _fixed(idx), (
            f"Scene {idx} visual_prompt not updated\n"
            f"  Expected: {_fixed(idx)!r}\n"
            f"  Got:      {scene['visual_prompt']!r}"
        )


# ── Export invariant: scene["visual_prompt"] == exported prompt ────────────────


def test_export_invariant_after_repair(tmp_path):
    """After validate_and_repair_cached, the exported visual_prompt must equal scene['visual_prompt']."""
    from ytfactory.images.prompt_synthesis import validate_and_repair_cached

    broken = "A tight The storybook ant, 16:9 aspect ratio"
    fixed = "A hand-painted storybook ant moves across granite, 16:9 aspect ratio"
    scenes = [_make_scene(index=4, narration="Small persistent effort.", visual_prompt=broken)]
    llm = _make_llm(_json_response([{"index": 4, "visual_prompt": fixed}]))

    updated, _ = validate_and_repair_cached(scenes, llm)

    # Simulate the _assemble_export_prompt path used by _write_prompts_file:
    # for V2 scenes (no structured_prompt), it reads scene["visual_prompt"] directly.
    exported_vp = updated[0]["visual_prompt"]
    stored_vp = updated[0]["visual_prompt"]
    assert exported_vp == stored_vp, (
        "Invariant violated: exported prompt != scene['visual_prompt']\n"
        f"  Exported: {exported_vp!r}\n"
        f"  Stored:   {stored_vp!r}"
    )
    assert exported_vp == fixed, (
        f"Invariant violated: exported prompt is not the repaired value\n"
        f"  Expected: {fixed!r}\n"
        f"  Got:      {exported_vp!r}"
    )


# ── Regression: root-cause corrupt patterns from IMAGE_PROMPTS.md ─────────────
# Root cause: _enforce_style_footer called on V2 synthesis prompts without gating.
# _strip_partial_footer strips "photorealistic", "cel shading", etc. mid-sentence,
# leaving the previous sentence truncated at its dangling article, directly
# followed by the next sentence's opening.  All five patterns below must be
# detected by the existing structural validators.


@pytest.mark.parametrize("bad_prompt,expected_check", [
    # "A tight A tiny…" — article + article broken join
    (
        "A tight cinematic shot of a warrior in a A tiny figure stands below the peak. "
        "16:9 aspect ratio.",
        "broken_join",
    ),
    # "the No single…" — mid-sentence lowercase article + capitalised sentence-starter
    (
        "Focus rests on the foundation where the No single element dominates. "
        "16:9 aspect ratio.",
        "mid_sentence_splice",
    ),
    # "A The visual action…" — capital A + The = broken join
    (
        "A The visual action communicates purpose without any text labels. "
        "16:9 aspect ratio.",
        "broken_join",
    ),
    # "A Their convergence…" — capital A + Their = broken join
    (
        "A Their convergence is marked by a single ink-brushstroke at the centre. "
        "16:9 aspect ratio.",
        "broken_join",
    ),
    # "A tight A tiny" minimal form — ensure pattern hasn't regressed
    (
        "A tight A tiny hand-painted 2D ant moves along the granite surface. "
        "16:9 aspect ratio.",
        "broken_join",
    ),
])
def test_rootcause_corruption_patterns_are_flagged(bad_prompt, expected_check):
    """Assembly corruption patterns produced by _strip_partial_footer must be detected."""
    issues = validate_synthesis_result(bad_prompt, scene_index=1, character_presence=[])
    matching = [i for i in issues if i.check == expected_check]
    assert matching, (
        f"Expected '{expected_check}' for known-corrupt pattern but got: "
        f"{[i.check for i in issues]} — prompt: {bad_prompt[:80]!r}"
    )


def test_valid_prompt_not_flagged_for_corruption():
    """A clean V2 synthesis prompt must produce no structural corruption issues."""
    prompt = (
        "A tiny hand-painted 2D storybook ant with visible ink outlines crawls across "
        "a photorealistic granite boulder at dawn. The ant's legs are smaller than a grain "
        "of rice. Himalayan peaks rise in the photorealistic misty background. Cool "
        "blue-grey light, no text, no watermark. 16:9 aspect ratio."
    )
    issues = validate_synthesis_result(prompt, scene_index=1, character_presence=[])
    structural = [i for i in issues if i.check in {
        "broken_join", "leading_orphan", "trailing_truncation", "mid_sentence_splice", "empty_prompt"
    }]
    assert not structural, (
        f"False-positive structural issue on clean V2 prompt: {structural}"
    )


# ── Scene Prompt QA: validate_scene_prompt_qa ────────────────────────────────


def test_qa_photo_char_error_flagged():
    """Photorealistic treatment on a character noun must produce qa_photo_char_error."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    prompt = (
        "A photorealistic warrior stands at the edge of a stone courtyard, sword raised. "
        "Warm amber light from the right. 16:9 aspect ratio."
    )
    issues = validate_scene_prompt_qa(prompt, 1, narration="A warrior stands guard.")
    assert any(i.check == "qa_photo_char_error" for i in issues), (
        f"Expected qa_photo_char_error for photorealistic warrior; got: {[i.check for i in issues]}"
    )


def test_qa_photo_char_error_excluded_for_artifact():
    """'Photorealistic statue of a warrior' must NOT trigger qa_photo_char_error — not a living subject."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    prompt = (
        "A photorealistic stone statue of a warrior stands in the temple courtyard. "
        "Warm amber light, 16:9 aspect ratio."
    )
    issues = validate_scene_prompt_qa(prompt, 1, narration="Stone warrior idol.")
    assert not any(i.check == "qa_photo_char_error" for i in issues), (
        "False positive qa_photo_char_error on stone statue (non-living artifact)"
    )


def test_qa_cartoon_env_error_flagged():
    """Cartoon/animated treatment on an environment noun must produce qa_cartoon_env_error."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    prompt = (
        "A tiny illustrated ant moves across a cartoon environment with flat-coloured mountains. "
        "16:9 aspect ratio."
    )
    issues = validate_scene_prompt_qa(prompt, 2, narration="The ant crosses the terrain.")
    assert any(i.check == "qa_cartoon_env_error" for i in issues), (
        f"Expected qa_cartoon_env_error for 'cartoon environment'; got: {[i.check for i in issues]}"
    )


def test_qa_illustrated_environment_error_flagged():
    """'illustrated background' must produce qa_cartoon_env_error — environments must be photorealistic."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    prompt = (
        "An illustrated ant stands in an illustrated background of mountain peaks. "
        "16:9 aspect ratio."
    )
    issues = validate_scene_prompt_qa(prompt, 3, narration="The ant views the mountains.")
    assert any(i.check == "qa_cartoon_env_error" for i in issues), (
        f"Expected qa_cartoon_env_error for 'illustrated background'; got: {[i.check for i in issues]}"
    )


def test_qa_hybrid_valid_prompt_no_false_positives():
    """A properly hybrid prompt (illustrated char + photorealistic env) must pass all QA checks."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    prompt = (
        "A tiny illustrated 2D storybook ant with painterly ink outlines and cel-shaded "
        "legs moves steadily across a photorealistic granite boulder. Himalayan peaks "
        "rise in the photorealistic background. Cool dawn light, no text. 16:9 aspect ratio."
    )
    issues = validate_scene_prompt_qa(
        prompt, 1,
        narration="A tiny ant climbs a boulder.",
        character_presence=["ant"],
    )
    qa_errors = [i for i in issues if i.check.endswith("_error")]
    assert not qa_errors, (
        f"False-positive QA errors on valid hybrid prompt: {qa_errors}"
    )


def test_qa_char_presence_warning_when_prompt_excludes_chars():
    """Prompt saying 'no characters' when character_presence is non-empty must warn."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    prompt = (
        "Wide shot of a photorealistic stone courtyard, no characters, "
        "clean environment shot, warm amber light. 16:9 aspect ratio."
    )
    issues = validate_scene_prompt_qa(
        prompt, 4,
        narration="Kai stands in the courtyard.",
        character_presence=["KAI"],
    )
    assert any(i.check == "qa_char_presence_warning" for i in issues), (
        f"Expected qa_char_presence_warning when character_presence=['KAI'] but prompt says "
        f"'no characters'; got: {[i.check for i in issues]}"
    )


def test_qa_char_presence_no_warning_when_chars_absent():
    """When character_presence is empty, 'no characters' prompt must NOT warn."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    prompt = (
        "Wide establishing shot of a photorealistic mountain valley, no characters. "
        "Cool morning light. 16:9 aspect ratio."
    )
    issues = validate_scene_prompt_qa(
        prompt, 5,
        narration="The empty valley at dawn.",
        character_presence=[],
    )
    assert not any(i.check == "qa_char_presence_warning" for i in issues)


def test_qa_compositor_text_error_for_subscribe_button():
    """Prompt requesting a 'subscribe button' must produce qa_compositor_text_error."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    prompt = (
        "Clean negative-space shot of a desk with a subscribe button rendered in the "
        "lower third. Warm amber light, 16:9 aspect ratio."
    )
    issues = validate_scene_prompt_qa(prompt, 21, narration="Subscribe scene.")
    assert any(i.check == "qa_compositor_text_error" for i in issues), (
        f"Expected qa_compositor_text_error for 'subscribe button'; got: {[i.check for i in issues]}"
    )


def test_qa_compositor_clean_space_not_flagged():
    """Leaving 'clean space' for compositor overlays must NOT produce qa_compositor_text_error."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    prompt = (
        "Clean negative-space shot of a natural wooden desk; upper third and right panel "
        "left open with soft diffused light for compositor overlay areas. "
        "No text, no watermark. 16:9 aspect ratio."
    )
    issues = validate_scene_prompt_qa(prompt, 21, narration="End screen compositor space.")
    assert not any(i.check == "qa_compositor_text_error" for i in issues), (
        "False positive qa_compositor_text_error on clean compositor space prompt"
    )


def test_qa_env_continuity_warning_on_abrupt_change():
    """Abrupt environment change without narration transition must produce qa_env_continuity_warning."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    prev_env = "ancient stone courtyard with cobblestones and archways"
    prompt = (
        "Extreme close-up of ocean waves crashing against a rocky shoreline at sunset; "
        "deep blue water, foam, salt spray. 16:9 aspect ratio."
    )
    issues = validate_scene_prompt_qa(
        prompt, 6,
        narration="The pattern continues.",
        character_presence=[],
        prev_environment=prev_env,
    )
    assert any(i.check == "qa_env_continuity_warning" for i in issues), (
        f"Expected qa_env_continuity_warning on abrupt env shift; got: {[i.check for i in issues]}"
    )


def test_qa_env_continuity_no_warning_with_transition_signal():
    """Narration that signals a transition must suppress qa_env_continuity_warning."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    prev_env = "ancient stone courtyard with cobblestones"
    prompt = (
        "Extreme close-up of ocean waves crashing against a rocky shoreline at sunset. "
        "16:9 aspect ratio."
    )
    issues = validate_scene_prompt_qa(
        prompt, 6,
        narration="Now the scene cuts to the ocean shore where the journey began.",
        character_presence=[],
        prev_environment=prev_env,
    )
    assert not any(i.check == "qa_env_continuity_warning" for i in issues), (
        "qa_env_continuity_warning must be suppressed when narration contains transition signal"
    )


def test_qa_issues_added_to_report_validation_issues():
    """validate_scene_prompt_qa issues must appear in SynthesisReport.validation_issues."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    vb = _make_visual_bible()
    scene = _make_scene(
        index=1,
        narration="A photorealistic warrior enters the frame.",
        character_presence=["warrior"],
    )
    # Prompt with photorealistic character — triggers qa_photo_char_error
    bad_prompt = (
        "A photorealistic warrior stands in a stone courtyard. "
        "Warm light from above. 16:9 aspect ratio."
    )
    llm = _make_llm(_json_response([{"index": 1, "visual_prompt": bad_prompt}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    qa_issues = [i for i in report.validation_issues if i.check.startswith("qa_")]
    assert any(i.check == "qa_photo_char_error" for i in qa_issues), (
        f"qa_photo_char_error must appear in report.validation_issues; got: "
        f"{[i.check for i in qa_issues]}"
    )


def test_qa_errors_do_not_trigger_repair():
    """QA errors must be logged but must NOT add the scene to failed_scenes or trigger repair."""
    vb = _make_visual_bible()
    scene = _make_scene(
        index=2,
        narration="A realistic warrior stands before the gates.",
        character_presence=["warrior"],
    )
    # Prompt with photorealistic character violation but no structural corruption
    qa_violating_prompt = (
        "A hyperrealistic warrior in full armour stands before photorealistic stone gates. "
        "Warm amber light, dramatic shadow. 16:9 aspect ratio."
    )
    llm = _make_llm(_json_response([{"index": 2, "visual_prompt": qa_violating_prompt}]))

    report = synthesize_visual_prompts([scene], llm, visual_bible=vb)

    # Scene must NOT be in failed_scenes — QA does not reject
    assert 2 not in report.failed_scenes, (
        "QA error must not add scene to failed_scenes"
    )
    # Exactly ONE LLM call — QA does not trigger repair pass
    assert llm.generate.call_count == 1, (
        f"QA errors must not trigger repair; got {llm.generate.call_count} LLM calls"
    )
    # The violating prompt stays in report.prompts unchanged
    assert report.prompts.get(2) == qa_violating_prompt, (
        "QA error must not replace the prompt — it is a warning/log only"
    )


def test_qa_separate_scenes_do_not_share_env_state():
    """Environment continuity state must be per-scene; prev_env from scene N-1 only."""
    from ytfactory.images.prompt_synthesis import validate_scene_prompt_qa

    # Scene 1: stone courtyard environment
    scene1_env = "ancient stone courtyard"
    # Scene 2: ocean shore — abrupt change from scene 1
    prompt2 = "Sunset over a tropical beach, palm trees, golden waves. 16:9 aspect ratio."
    # Scene 3: ocean shore again — same as scene 2, so NO abrupt change
    prompt3 = "Waves crash on the same beach shore at dusk, warm red light. 16:9 aspect ratio."

    # QA for scene 2: prev_env is scene 1's environment (stone courtyard)
    issues2 = validate_scene_prompt_qa(
        prompt2, 2,
        narration="The setting shifts.",
        prev_environment=scene1_env,
    )
    # QA for scene 3: prev_env is scene 2's environment — both are beach/ocean scenes
    issues3 = validate_scene_prompt_qa(
        prompt3, 3,
        narration="The beach remains.",
        prev_environment="tropical beach ocean shore palm trees",
    )

    # Scene 2 has no narration transition signal → may warn
    # Scene 3 shares environment tokens with prev → must NOT warn
    assert not any(i.check == "qa_env_continuity_warning" for i in issues3), (
        "qa_env_continuity_warning must not fire when environment tokens overlap with prev scene"
    )


# ── _extract_visual_direction unit tests ─────────────────────────────────────


def test_extract_visual_direction_basic():
    """Single [Visual:] tag is extracted; prose remains clean."""
    prose, direction = _extract_visual_direction(
        "Fear grips the village. [Visual: extreme close-up of trembling hands clasping a torch.]"
    )
    assert "extreme close-up of trembling hands clasping a torch" in direction
    assert "[Visual:" not in prose
    assert "Fear grips the village" in prose


def test_extract_visual_direction_multiple_tags():
    """Multiple [Visual:] tags are joined with ' | '."""
    prose, direction = _extract_visual_direction(
        "[Visual: wide aerial shot.] Narration here. [Visual: tight face close-up.]"
    )
    assert "wide aerial shot" in direction
    assert "tight face close-up" in direction
    assert "|" in direction
    assert "[Visual:" not in prose


def test_extract_visual_direction_no_tag():
    """Narration without [Visual:] tags returns empty direction and unchanged prose."""
    narration = "Consistency is the hidden superpower."
    prose, direction = _extract_visual_direction(narration)
    assert direction == ""
    assert prose == narration


def test_extract_visual_direction_case_insensitive():
    """[visual:] lowercase variant is also captured."""
    prose, direction = _extract_visual_direction(
        "Opening scene. [visual: stone courtyard at dawn.]"
    )
    assert "stone courtyard at dawn" in direction
    assert "[visual:" not in prose


def test_extract_visual_direction_scene_block_field_present():
    """VISUAL_DIRECTION field appears in scene block when tag exists."""
    scene = _make_scene(
        narration="The mind grows quieter. [Visual: Empty meditation hall, single candle flame.]"
    )
    block = _build_scene_block(scene, None, None, None)
    assert "VISUAL_DIRECTION: Empty meditation hall, single candle flame" in block
    assert "[Visual:" not in block
    assert "The mind grows quieter" in block


def test_extract_visual_direction_scene_block_absent_when_no_tag():
    """VISUAL_DIRECTION field is absent from scene block when narration has no tag."""
    scene = _make_scene(narration="Consistency is the hidden superpower.")
    block = _build_scene_block(scene, None, None, None)
    assert "VISUAL_DIRECTION:" not in block
    assert "Consistency is the hidden superpower" in block
