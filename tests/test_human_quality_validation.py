"""Tests for HUMAN_QUALITY_AND_SUBJECT_VALIDATION_V1.

Covers:
  - human_detector.py — detection, quality markers, subject dominance, sharpness
  - HumanValidator   — HUM_001, HUM_002, HUM_003
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ytfactory.images.human_detector import (
    _HUMAN_QUALITY_PHRASE,
    _SUBJECT_DOMINANCE_PHRASE,
    _WIDE_SHOT_TYPES,
    add_human_quality_reinforcement,
    apply_subject_dominance_rule,
    build_specialist_context,
    compute_sharpness,
    detect_critical_subject,
    detect_human_presence,
    has_human_quality_reinforcement,
)
from ytfactory.review.validation.config import ValidationRulesConfig
from ytfactory.review.validation.rules.human import HumanValidator, _DEFAULT_SHARPNESS_THRESHOLD


# ---------------------------------------------------------------------------
# TestHumanDetection
# ---------------------------------------------------------------------------


class TestHumanDetection:
    def test_detects_man(self):
        prompt = "A lean man in a grey linen shirt stands at the edge of a cliff"
        assert detect_human_presence(prompt) is True

    def test_detects_woman(self):
        prompt = "A woman in a sari walks through a narrow market alley"
        assert detect_human_presence(prompt) is True

    def test_detects_monk(self):
        prompt = "Monk sitting beneath an ancient banyan tree, dawn light filtering through"
        assert detect_human_presence(prompt) is True

    def test_detects_portrait_substring(self):
        prompt = "Environmental portrait, subject embedded in decaying colonial architecture"
        assert detect_human_presence(prompt) is True

    def test_detects_face_substring(self):
        prompt = "Close-up face half in shadow, warm lamp glow from the left"
        assert detect_human_presence(prompt) is True

    def test_detects_crowd(self):
        prompt = "Crowd gathered at the riverbank, paper lanterns drifting skyward"
        assert detect_human_presence(prompt) is True

    def test_detects_elder(self):
        prompt = "An elder traces the cracks in a stone wall at the village gate"
        assert detect_human_presence(prompt) is True

    def test_detects_scholar(self):
        prompt = "Scholar bent over a manuscript, single candle illuminating the page"
        assert detect_human_presence(prompt) is True

    def test_no_false_positive_for_landscape(self):
        prompt = (
            "Glacier-fed alpine lake, surface unbroken at pre-dawn, distant peaks "
            "rising into clouds, photorealistic, documentary, no text, no watermark"
        )
        assert detect_human_presence(prompt) is False

    def test_no_false_positive_for_object_scene(self):
        prompt = (
            "Worn stone steps disappear into morning mist, iron gate ajar, "
            "ivy claiming the walls, cinematic, no text, no watermark"
        )
        assert detect_human_presence(prompt) is False

    def test_no_false_positive_for_nature_scene(self):
        prompt = (
            "Mangrove roots emerging from still water, golden hour light, "
            "aerial high angle, photorealistic, no text, no watermark"
        )
        assert detect_human_presence(prompt) is False

    def test_case_insensitive(self):
        assert detect_human_presence("MONK sitting in a temple") is True
        assert detect_human_presence("old MAN by the river") is True


# ---------------------------------------------------------------------------
# TestHumanQualityMarkers
# ---------------------------------------------------------------------------


class TestHumanQualityMarkers:
    # The exact phrase appended by add_human_quality_reinforcement()
    _FULL_MARKERS = (
        "highly detailed human face, natural facial expression, realistic eyes, "
        "authentic skin texture, natural posture, seamless integration with the environment, "
        "documentary-quality realism"
    )

    def test_true_when_all_markers_present(self):
        prompt = f"An elder, {self._FULL_MARKERS}, photorealistic"
        assert has_human_quality_reinforcement(prompt) is True

    def test_true_with_exactly_two_markers(self):
        prompt = "A man with natural facial expression and realistic eyes, wide shot"
        assert has_human_quality_reinforcement(prompt) is True

    def test_false_when_only_one_marker(self):
        # "natural facial expression" is 1 marker (not 2 — no substring overlap in revised set)
        prompt = "A woman with natural facial expression standing in a field"
        assert has_human_quality_reinforcement(prompt) is False

    def test_false_when_no_markers(self):
        prompt = "A warrior in silhouette against a stormy sky, photorealistic"
        assert has_human_quality_reinforcement(prompt) is False

    def test_case_insensitive_marker_detection(self):
        prompt = "NATURAL FACIAL EXPRESSION and REALISTIC EYES captured in the frame"
        assert has_human_quality_reinforcement(prompt) is True


# ---------------------------------------------------------------------------
# TestAddHumanQualityReinforcement
# ---------------------------------------------------------------------------


class TestAddHumanQualityReinforcement:
    def test_appends_phrase_when_missing(self):
        prompt = "An elder monk seated beneath an ancient banyan tree, photorealistic"
        result = add_human_quality_reinforcement(prompt)
        assert result.endswith(_HUMAN_QUALITY_PHRASE)
        assert "highly detailed human face" in result
        assert "documentary-quality realism" in result

    def test_does_not_double_append_when_already_reinforced(self):
        prompt = (
            "An elder, highly detailed human face, natural facial expression, realistic eyes, "
            "authentic skin texture, natural posture, seamless integration with the environment, "
            "documentary-quality realism, photorealistic"
        )
        result = add_human_quality_reinforcement(prompt)
        assert result == prompt

    def test_original_prompt_preserved(self):
        original = "Lean man in grey linen, photorealistic, no text, no watermark"
        result = add_human_quality_reinforcement(original)
        assert result.startswith(original)

    def test_returns_unchanged_when_already_has_two_markers(self):
        prompt = "A monk, realistic eyes and natural facial expression, wide shot"
        result = add_human_quality_reinforcement(prompt)
        assert result == prompt


# ---------------------------------------------------------------------------
# TestSubjectDominanceRule
# ---------------------------------------------------------------------------


class TestSubjectDominanceRule:
    def test_adds_dominance_for_wide_shot(self):
        prompt = "A farmer walks along an irrigation canal, photorealistic"
        result = apply_subject_dominance_rule(prompt, "wide shot")
        assert "subject remains visually prominent" in result

    def test_adds_dominance_for_establishing_shot(self):
        prompt = "A warrior stands before the fort gate, cinematic"
        result = apply_subject_dominance_rule(prompt, "establishing shot")
        assert "subject remains visually prominent" in result

    def test_adds_dominance_for_drone_shot(self):
        prompt = "A scholar reading in the courtyard, aerial perspective"
        result = apply_subject_dominance_rule(prompt, "drone")
        assert "subject remains visually prominent" in result

    def test_adds_dominance_for_wide_cinematic(self):
        prompt = "A lone woman on a salt flat, vast empty expanse"
        result = apply_subject_dominance_rule(prompt, "wide cinematic")
        assert "subject remains visually prominent" in result

    def test_adds_dominance_for_high_angle(self):
        prompt = "A man crossing a stone bridge, looking down into the gorge"
        result = apply_subject_dominance_rule(prompt, "high angle")
        assert "subject remains visually prominent" in result

    def test_no_dominance_for_medium_shot(self):
        prompt = "A philosopher at a writing desk, close-up on hands"
        result = apply_subject_dominance_rule(prompt, "medium shot")
        assert "subject remains visually prominent" not in result

    def test_no_dominance_for_close_up(self):
        prompt = "An elderly woman's profile, warm golden light"
        result = apply_subject_dominance_rule(prompt, "close-up")
        assert "subject remains visually prominent" not in result

    def test_no_dominance_when_no_human(self):
        prompt = "Vast salt flat stretching to the horizon, drone shot, golden hour"
        result = apply_subject_dominance_rule(prompt, "wide shot")
        assert "subject remains visually prominent" not in result

    def test_no_dominance_when_hint_already_present(self):
        hint = _SUBJECT_DOMINANCE_PHRASE.lstrip(", ")
        prompt = f"An elder, {hint}, wide shot"
        result = apply_subject_dominance_rule(prompt, "wide shot")
        assert result.count("subject remains visually prominent") == 1

    def test_original_prompt_unchanged_for_non_wide_shot(self):
        prompt = "A monk's hands on prayer beads, photorealistic"
        result = apply_subject_dominance_rule(prompt, "static")
        assert result == prompt

    @pytest.mark.parametrize("shot_type", sorted(_WIDE_SHOT_TYPES))
    def test_all_wide_shot_types_trigger_dominance(self, shot_type):
        prompt = "A person stands in the environment, photorealistic"
        result = apply_subject_dominance_rule(prompt, shot_type)
        assert "subject remains visually prominent" in result


# ---------------------------------------------------------------------------
# TestComputeSharpness
# ---------------------------------------------------------------------------


class TestComputeSharpness:
    def test_returns_zero_for_missing_file(self):
        assert compute_sharpness(Path("/nonexistent/image.png")) == 0.0

    def test_returns_float_for_valid_image(self, tmp_path):
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not available")

        img_path = tmp_path / "test.png"
        img = Image.new("RGB", (256, 256), color=(128, 64, 32))
        img.save(img_path)
        score = compute_sharpness(img_path)
        assert isinstance(score, float)
        assert score >= 0.0

    def test_sharp_image_scores_higher_than_blurry(self, tmp_path):
        try:
            from PIL import Image, ImageFilter
        except ImportError:
            pytest.skip("Pillow not available")

        # Create a high-contrast image (sharp edges)
        sharp_path = tmp_path / "sharp.png"
        img = Image.new("RGB", (256, 256), color=(0, 0, 0))
        pixels = img.load()
        for x in range(256):
            for y in range(256):
                pixels[x, y] = (255, 255, 255) if (x // 8 + y // 8) % 2 == 0 else (0, 0, 0)
        img.save(sharp_path)

        # Create a uniform image (no edges = blurry equivalent)
        blurry_path = tmp_path / "blurry.png"
        Image.new("RGB", (256, 256), color=(128, 128, 128)).save(blurry_path)

        assert compute_sharpness(sharp_path) > compute_sharpness(blurry_path)

    def test_returns_zero_for_corrupt_data(self, tmp_path):
        bad_path = tmp_path / "corrupt.png"
        bad_path.write_bytes(b"not a valid image")
        assert compute_sharpness(bad_path) == 0.0


# ---------------------------------------------------------------------------
# TestHumanValidator
# ---------------------------------------------------------------------------


def _make_validator(rules: dict | None = None) -> HumanValidator:
    cfg = ValidationRulesConfig(rules=rules or {})
    return HumanValidator(cfg)


def _scene(
    index: int,
    prompt: str,
    shot_type: str = "medium shot",
    scene_type: str = "generated_image",
) -> dict:
    return {
        "index": index,
        "scene_type": scene_type,
        "visual_prompt": prompt,
        "shot_type": shot_type,
        "narration": "Some narration.",
    }


class TestHumanValidatorHUM001:
    def test_pass_when_markers_present(self):
        scene = _scene(
            1,
            (
                "An elder monk, highly detailed human face, natural facial expression, "
                "realistic eyes, authentic skin texture, natural posture, photorealistic"
            ),
        )
        v = _make_validator()
        results = v.validate(Path("/fake"), [scene], {})
        hum001 = [r for r in results if r.rule_id == "HUM_001"]
        assert len(hum001) == 1
        assert hum001[0].status == "PASS"

    def test_fail_when_markers_missing(self):
        scene = _scene(1, "A lean man in a grey linen shirt, photorealistic, no text")
        v = _make_validator()
        results = v.validate(Path("/fake"), [scene], {})
        hum001 = [r for r in results if r.rule_id == "HUM_001"]
        assert len(hum001) == 1
        assert hum001[0].status == "FAIL"
        assert hum001[0].severity == "high"

    def test_skip_when_no_generated_scenes(self):
        v = _make_validator()
        results = v.validate(Path("/fake"), [], {})
        hum001 = [r for r in results if r.rule_id == "HUM_001"]
        assert all(r.status == "SKIP" for r in hum001)

    def test_no_result_for_non_human_scene(self):
        scene = _scene(1, "Vast salt flat at sunset, drone shot, golden light, photorealistic")
        v = _make_validator()
        results = v.validate(Path("/fake"), [scene], {})
        hum001 = [r for r in results if r.rule_id == "HUM_001"]
        assert len(hum001) == 0

    def test_no_result_for_asset_scene(self):
        scene = _scene(1, "A man in a wide open field", scene_type="asset")
        v = _make_validator()
        results = v.validate(Path("/fake"), [scene], {})
        # Asset scenes are not in `generated`; HUM_001 is SKIP (not FAIL/WARN)
        hum001 = [r for r in results if r.rule_id == "HUM_001"]
        assert all(r.status == "SKIP" for r in hum001)


class TestHumanValidatorHUM002:
    _QUALITY_MARKERS = _HUMAN_QUALITY_PHRASE.lstrip(", ")

    def _prompt_with_markers(self, extra: str = "") -> str:
        return f"A farmer at the edge of a vast plain, {self._QUALITY_MARKERS}{extra}"

    def test_warn_wide_shot_no_dominance(self):
        scene = _scene(1, self._prompt_with_markers(), shot_type="wide shot")
        v = _make_validator()
        results = v.validate(Path("/fake"), [scene], {})
        hum002 = [r for r in results if r.rule_id == "HUM_002"]
        assert len(hum002) == 1
        assert hum002[0].status == "WARNING"

    def test_pass_wide_shot_with_dominance(self):
        dominance = _SUBJECT_DOMINANCE_PHRASE.lstrip(", ")
        scene = _scene(
            1,
            self._prompt_with_markers(f", {dominance}"),
            shot_type="wide shot",
        )
        v = _make_validator()
        results = v.validate(Path("/fake"), [scene], {})
        hum002 = [r for r in results if r.rule_id == "HUM_002"]
        assert len(hum002) == 1
        assert hum002[0].status == "PASS"

    def test_skip_for_medium_shot(self):
        scene = _scene(1, self._prompt_with_markers(), shot_type="medium shot")
        v = _make_validator()
        results = v.validate(Path("/fake"), [scene], {})
        hum002 = [r for r in results if r.rule_id == "HUM_002"]
        assert len(hum002) == 1
        assert hum002[0].status == "SKIP"

    @pytest.mark.parametrize("shot_type", sorted(_WIDE_SHOT_TYPES))
    def test_warn_for_all_wide_shot_types_without_dominance(self, shot_type):
        scene = _scene(1, self._prompt_with_markers(), shot_type=shot_type)
        v = _make_validator()
        results = v.validate(Path("/fake"), [scene], {})
        hum002 = [r for r in results if r.rule_id == "HUM_002"]
        assert hum002[0].status == "WARNING", f"Expected WARNING for shot_type={shot_type!r}"


class TestHumanValidatorHUM003:
    _PROMPT = (
        "An elder, highly detailed human face, natural facial expression, realistic eyes, "
        "authentic skin texture, natural posture, seamless integration with the environment, "
        "documentary-quality realism, photorealistic"
    )

    def test_skip_when_image_missing(self, tmp_path):
        scene = _scene(1, self._PROMPT)
        v = _make_validator()
        results = v.validate(tmp_path, [scene], {})
        hum003 = [r for r in results if r.rule_id == "HUM_003"]
        assert len(hum003) == 1
        assert hum003[0].status == "SKIP"

    def test_pass_for_sharp_image(self, tmp_path):
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not available")

        img_dir = tmp_path / "images"
        img_dir.mkdir()
        img_path = img_dir / "scene-001.png"

        # High-contrast checkerboard pattern → high sharpness score
        img = Image.new("L", (512, 512), color=0)
        pixels = img.load()
        for x in range(512):
            for y in range(512):
                pixels[x, y] = 255 if (x // 4 + y // 4) % 2 == 0 else 0
        img.save(img_path)

        scene = _scene(1, self._PROMPT)
        from ytfactory.review.validation.config import RuleConfig

        v = _make_validator({"HUM_003": RuleConfig(threshold=0.5)})
        results = v.validate(tmp_path, [scene], {})
        hum003 = [r for r in results if r.rule_id == "HUM_003"]
        assert len(hum003) == 1
        assert hum003[0].status == "PASS"

    def test_fail_for_blurry_image(self, tmp_path):
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not available")

        img_dir = tmp_path / "images"
        img_dir.mkdir()
        img_path = img_dir / "scene-001.png"

        # Uniform image → sharpness ≈ 0
        Image.new("L", (512, 512), color=128).save(img_path)

        scene = _scene(1, self._PROMPT)
        # Set threshold high so the uniform image always fails
        from ytfactory.review.validation.config import RuleConfig

        v = _make_validator({"HUM_003": RuleConfig(threshold=50.0)})
        results = v.validate(tmp_path, [scene], {})
        hum003 = [r for r in results if r.rule_id == "HUM_003"]
        assert len(hum003) == 1
        assert hum003[0].status == "FAIL"
        assert hum003[0].severity == "high"

    def test_no_result_for_non_human_scene(self, tmp_path):
        prompt = "Mountain lake at pre-dawn, surface unbroken, photorealistic, no text"
        scene = _scene(1, prompt)
        v = _make_validator()
        results = v.validate(tmp_path, [scene], {})
        hum003 = [r for r in results if r.rule_id == "HUM_003"]
        assert len(hum003) == 0


class TestHumanValidatorMultiScene:
    _MARKERS = (
        "highly detailed human face, natural facial expression, realistic eyes, "
        "authentic skin texture, natural posture, seamless integration with the environment, "
        "documentary-quality realism"
    )

    def test_only_human_scenes_are_validated(self):
        scenes = [
            _scene(1, f"A monk in the courtyard, {self._MARKERS}, photorealistic"),
            _scene(2, "An empty courtyard, stone paving, golden afternoon light, cinematic"),
            _scene(3, f"A warrior at the gate, {self._MARKERS}, no text, no watermark"),
        ]
        v = _make_validator()
        results = v.validate(Path("/fake"), scenes, {})
        hum001 = [r for r in results if r.rule_id == "HUM_001"]
        # Only scenes 1 and 3 are human scenes → 2 HUM_001 results
        assert len(hum001) == 2
        assert all(r.status == "PASS" for r in hum001)

    def test_disabled_rule_produces_no_results(self):
        from ytfactory.review.validation.config import RuleConfig

        scene = _scene(1, "A man in a field, photorealistic")
        v = _make_validator({"HUM_001": RuleConfig(enabled=False)})
        results = v.validate(Path("/fake"), [scene], {})
        hum001 = [r for r in results if r.rule_id == "HUM_001"]
        assert len(hum001) == 0


# ---------------------------------------------------------------------------
# TestDetectCriticalSubject (ADR-0013)
# ---------------------------------------------------------------------------


class TestDetectCriticalSubject:
    def test_hand_keyword_returns_hand(self):
        assert detect_critical_subject("close-up of an outstretched hand") == "hand"

    def test_fingers_keyword_returns_hand(self):
        assert detect_critical_subject("five fingers reaching toward the light") == "hand"

    def test_face_keyword_returns_face(self):
        assert detect_critical_subject("close-up portrait of a wise elder's face") == "face"

    def test_eye_keyword_returns_eye(self):
        assert detect_critical_subject("extreme close-up of an eye, reflective iris") == "eye"

    def test_gesture_keyword_returns_gesture(self):
        assert detect_critical_subject("a pointing gesture toward the horizon") == "gesture"

    def test_body_keyword_returns_body(self):
        assert detect_critical_subject("full body silhouette against twilight") == "body"

    def test_no_critical_subject_returns_none(self):
        assert detect_critical_subject("a vast mountain range at dawn, cinematic") is None

    def test_hand_wins_over_gesture_priority(self):
        # "hand" is higher priority than "gesture" in the _CRITICAL_SUBJECT_KEYWORDS order
        result = detect_critical_subject("a clasped hand gesture outstretched")
        assert result == "hand"

    def test_case_insensitive(self):
        assert detect_critical_subject("HANDS reaching toward dawn") == "hand"

    def test_no_false_positive_on_word_boundary(self):
        # "handsome" must not match "hand"
        assert detect_critical_subject("a handsome warrior on horseback") is None


# ---------------------------------------------------------------------------
# TestBuildSpecialistContext (ADR-0013)
# ---------------------------------------------------------------------------


class TestBuildSpecialistContext:
    def test_hand_context_contains_checklist(self):
        ctx = build_specialist_context("hand")
        assert "five fingers" in ctx
        assert "fused fingers" in ctx
        assert "wrist" in ctx
        assert "thumb" in ctx

    def test_face_context_contains_checklist(self):
        ctx = build_specialist_context("face")
        assert "symmetry" in ctx or "symmetric" in ctx.lower()
        assert "eyes" in ctx

    def test_eye_context_contains_checklist(self):
        ctx = build_specialist_context("eye")
        assert "iris" in ctx
        assert "pupil" in ctx

    def test_body_context_not_empty(self):
        assert build_specialist_context("body") != ""

    def test_gesture_context_not_empty(self):
        assert build_specialist_context("gesture") != ""

    def test_unknown_subject_returns_empty(self):
        assert build_specialist_context("unknown_subject") == ""
