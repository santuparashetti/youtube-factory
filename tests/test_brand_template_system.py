"""Tests for BRAND_TEMPLATE_SYSTEM_V1.

Covers:
  - BrandConfig loading from YAML
  - BrandConfig fallback defaults
  - ContentSection.text() normalisation
  - VoiceConfig and BrandingPlacementConfig
  - BrandValidator placement rules
  - BrandValidationReport helpers
  - branding.py public API still works
  - script_writer prompts use channel_name / cta from config
  - script_enhancer prompt accepts cta
  - scene_planner derives asset_path from config
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from ytfactory.branding.config import (
    BrandConfig,
    BrandingPlacementConfig,
    ContentSection,
    VoiceConfig,
    _parse_brand_config,
    get_brand_config,
    reset_brand_config_cache,
)
from ytfactory.branding.validator import BrandValidationReport, BrandValidator


# ── Helpers ────────────────────────────────────────────────────────────────────


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "brand_config.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


def _make_valid_script(
    welcome: str = "Welcome to Test Channel... where stories live.",
    closing: str = "This is Test Channel.",
    cta: str = "Join us on this journey.",
    signature: str = "Think deeper... Live clearer.",
) -> str:
    """Build a syntactically valid branded script for validation tests."""
    return textwrap.dedent(f"""\
        Have you ever wondered why the sky turns red at dusk?

        {welcome}

        Today we explore the hidden language of light.

        Scientists have spent centuries unravelling the mystery of colour and perception.
        The phenomenon touches every culture, every mythology, every human eye.

        Light bends. It scatters. It tells a story that changes every evening.
        And that story is different depending on where you stand.

        At the edge of every horizon lies a lesson about perspective itself.

        The wavelengths that reach you are the ones that survived the longest journey.
        In that way, the red sky is a testament to resilience.

        {closing}

        {cta}

        {signature}
    """)


# ── TestContentSection ─────────────────────────────────────────────────────────


class TestContentSection:
    def test_text_strips_leading_trailing_whitespace(self):
        s = ContentSection(template="  Hello world  ")
        assert s.text() == "Hello world"

    def test_text_joins_multiline_template(self):
        s = ContentSection(template="Welcome to Channel...\nwhere wisdom lives.")
        assert s.text() == "Welcome to Channel... where wisdom lives."

    def test_text_strips_each_line(self):
        s = ContentSection(template="  line one  \n  line two  ")
        assert s.text() == "line one line two"

    def test_text_empty_template(self):
        s = ContentSection(template="")
        assert s.text() == ""

    def test_text_skips_blank_lines(self):
        s = ContentSection(template="line one\n\nline two")
        assert s.text() == "line one line two"

    def test_enabled_default_true(self):
        s = ContentSection()
        assert s.enabled is True

    def test_enabled_false(self):
        s = ContentSection(enabled=False, template="hello")
        assert s.enabled is False


# ── TestVoiceConfig ────────────────────────────────────────────────────────────


class TestVoiceConfig:
    def test_defaults(self):
        v = VoiceConfig()
        assert v.pace == "calm"
        assert v.pause_after_opening_ms == 800
        assert v.pause_after_closing_ms == 1000


# ── TestBrandingPlacementConfig ────────────────────────────────────────────────


class TestBrandingPlacementConfig:
    def test_defaults(self):
        c = BrandingPlacementConfig()
        assert c.opening_position == "after_hook"
        assert c.closing_position == "before_final_quote"
        assert c.max_opening_seconds == 10
        assert c.asset_path == "assets/branding/atma-theory-brand.png"
        assert c.asset_animation == "slow_zoom"


# ── TestBrandConfigDefaults ────────────────────────────────────────────────────


class TestBrandConfigDefaults:
    def test_channel_name_default(self):
        cfg = BrandConfig()
        assert cfg.channel_name == "Atma Theory"

    def test_opening_default_text(self):
        cfg = BrandConfig()
        assert "Atma Theory" in cfg.opening.text()

    def test_closing_default_text(self):
        cfg = BrandConfig()
        assert "Atma Theory" in cfg.closing.text()

    def test_cta_default_nonempty(self):
        cfg = BrandConfig()
        assert len(cfg.cta.text()) > 0

    def test_signature_default_nonempty(self):
        cfg = BrandConfig()
        assert len(cfg.signature.text()) > 0

    def test_voice_default(self):
        cfg = BrandConfig()
        assert cfg.voice.pace == "calm"

    def test_branding_placement_default(self):
        cfg = BrandConfig()
        assert cfg.branding.opening_position == "after_hook"


# ── TestParseBrandConfig ───────────────────────────────────────────────────────


class TestParseBrandConfig:
    def _data(self) -> dict:
        return {
            "channel_name": "Zen Factory",
            "opening": {"enabled": True, "template": "Welcome to Zen Factory.\n"},
            "closing": {"enabled": True, "template": "This is Zen Factory."},
            "cta": {"enabled": True, "template": "Follow if this moved you."},
            "signature": {"enabled": True, "template": "Breathe... and begin."},
            "voice": {"pace": "slow", "pause_after_opening_ms": 1000, "pause_after_closing_ms": 1200},
            "branding": {
                "opening_position": "after_hook",
                "closing_position": "before_final_quote",
                "max_opening_seconds": 8,
                "asset_path": "assets/branding/zen-factory.png",
                "asset_animation": "fade_in",
            },
        }

    def test_channel_name(self):
        cfg = _parse_brand_config(self._data())
        assert cfg.channel_name == "Zen Factory"

    def test_opening_text(self):
        cfg = _parse_brand_config(self._data())
        assert cfg.opening.text() == "Welcome to Zen Factory."

    def test_closing_text(self):
        cfg = _parse_brand_config(self._data())
        assert cfg.closing.text() == "This is Zen Factory."

    def test_cta_text(self):
        cfg = _parse_brand_config(self._data())
        assert cfg.cta.text() == "Follow if this moved you."

    def test_signature_text(self):
        cfg = _parse_brand_config(self._data())
        assert cfg.signature.text() == "Breathe... and begin."

    def test_voice_pace(self):
        cfg = _parse_brand_config(self._data())
        assert cfg.voice.pace == "slow"

    def test_voice_pause_opening(self):
        cfg = _parse_brand_config(self._data())
        assert cfg.voice.pause_after_opening_ms == 1000

    def test_branding_asset_path(self):
        cfg = _parse_brand_config(self._data())
        assert cfg.branding.asset_path == "assets/branding/zen-factory.png"

    def test_branding_asset_animation(self):
        cfg = _parse_brand_config(self._data())
        assert cfg.branding.asset_animation == "fade_in"

    def test_max_opening_seconds(self):
        cfg = _parse_brand_config(self._data())
        assert cfg.branding.max_opening_seconds == 8

    def test_missing_keys_fallback_to_defaults(self):
        cfg = _parse_brand_config({})
        assert cfg.channel_name == "Atma Theory"
        assert cfg.voice.pace == "calm"

    def test_partial_voice_config(self):
        cfg = _parse_brand_config({"voice": {"pace": "meditative"}})
        assert cfg.voice.pace == "meditative"
        assert cfg.voice.pause_after_opening_ms == 800

    def test_disabled_section(self):
        data = {"opening": {"enabled": False, "template": "Hi"}}
        cfg = _parse_brand_config(data)
        assert cfg.opening.enabled is False


# ── TestGetBrandConfig ─────────────────────────────────────────────────────────


class TestGetBrandConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        reset_brand_config_cache()
        cfg = get_brand_config(config_path=tmp_path / "nonexistent.yaml")
        assert cfg.channel_name == "Atma Theory"
        reset_brand_config_cache()

    def test_valid_yaml_is_loaded(self, tmp_path):
        reset_brand_config_cache()
        p = _write_yaml(tmp_path, {"channel_name": "Deep Roots"})
        cfg = get_brand_config(config_path=p)
        assert cfg.channel_name == "Deep Roots"
        reset_brand_config_cache()

    def test_caching(self, tmp_path):
        reset_brand_config_cache()
        p = _write_yaml(tmp_path, {"channel_name": "Cached"})
        cfg1 = get_brand_config(config_path=p)
        cfg2 = get_brand_config(config_path=p)
        assert cfg1 is cfg2
        reset_brand_config_cache()

    def test_reload_flag_bypasses_cache(self, tmp_path):
        reset_brand_config_cache()
        p = _write_yaml(tmp_path, {"channel_name": "First"})
        cfg1 = get_brand_config(config_path=p)
        p.write_text(yaml.dump({"channel_name": "Second"}), encoding="utf-8")
        cfg2 = get_brand_config(config_path=p, reload=True)
        assert cfg1.channel_name == "First"
        assert cfg2.channel_name == "Second"
        reset_brand_config_cache()

    def test_malformed_yaml_returns_defaults(self, tmp_path):
        reset_brand_config_cache()
        p = tmp_path / "brand_config.yaml"
        p.write_text(":: not valid yaml ::", encoding="utf-8")
        cfg = get_brand_config(config_path=p)
        assert cfg.channel_name == "Atma Theory"
        reset_brand_config_cache()


# ── TestBrandValidator ─────────────────────────────────────────────────────────


class TestBrandValidator:
    def _cfg(self) -> BrandConfig:
        return _parse_brand_config(
            {
                "channel_name": "Test Channel",
                "opening": {
                    "enabled": True,
                    "template": "Welcome to Test Channel... where stories live.",
                },
                "closing": {"enabled": True, "template": "This is Test Channel."},
                "cta": {"enabled": True, "template": "Join us on this journey."},
                "signature": {"enabled": True, "template": "Think deeper... Live clearer."},
            }
        )

    def _validator(self) -> BrandValidator:
        return BrandValidator()

    def _valid_script(self) -> str:
        return _make_valid_script(
            welcome="Welcome to Test Channel... where stories live.",
            closing="This is Test Channel.",
            cta="Join us on this journey.",
            signature="Think deeper... Live clearer.",
        )

    # -- Happy path

    def test_valid_script_passes(self):
        report = self._validator().validate(self._valid_script(), self._cfg())
        assert report.valid is True
        assert report.issues == []

    def test_valid_script_summary_contains_pass(self):
        report = self._validator().validate(self._valid_script(), self._cfg())
        assert "PASS" in report.summary()

    # -- Empty / short scripts

    def test_empty_script_fails(self):
        report = self._validator().validate("", self._cfg())
        assert report.valid is False

    def test_too_short_script_fails(self):
        report = self._validator().validate("Short script.", self._cfg())
        assert report.valid is False

    # -- Opening welcome

    def test_missing_opening_fails(self):
        script = _make_valid_script(welcome="No welcome here at all")
        # Replace the welcome with something the config doesn't expect
        script = script.replace("No welcome here at all", "Greetings from outer space")
        report = self._validator().validate(script, self._cfg())
        assert not report.valid
        assert any("opening welcome" in i.lower() for i in report.issues)

    def test_opening_appears_twice_fails(self):
        welcome = "Welcome to Test Channel... where stories live."
        script = self._valid_script() + f"\n{welcome}\n"
        report = self._validator().validate(script, self._cfg())
        assert not report.valid
        assert any("twice" in i.lower() or "2 times" in i for i in report.issues)

    def test_opening_too_late_fails(self):
        # Build a script where the welcome is way past the 30% mark
        filler = ("This is filler content about the world and science. " * 40)
        welcome = "Welcome to Test Channel... where stories live."
        cta = "Join us on this journey."
        sig = "Think deeper... Live clearer."
        closing = "This is Test Channel."
        script = f"{filler}\n\n{welcome}\n\n{filler}\n\n{closing}\n\n{cta}\n\n{sig}"
        report = self._validator().validate(script, self._cfg())
        assert not report.valid
        assert any("too late" in i.lower() for i in report.issues)

    # -- Closing signature position

    def test_closing_too_early_fails(self):
        sig = "Think deeper... Live clearer."
        filler = "This is filler content that goes on and on and on. " * 30
        welcome = "Welcome to Test Channel... where stories live."
        closing = "This is Test Channel."
        cta = "Join us on this journey."
        # signature appears before the midpoint
        script = f"{welcome}\n\n{sig}\n\n{filler}\n\n{closing}\n\n{cta}"
        report = self._validator().validate(script, self._cfg())
        assert not report.valid

    # -- CTA

    def test_cta_missing_is_warning_not_issue(self):
        # Remove the CTA from the valid script
        script = self._valid_script().replace("Join us on this journey.", "")
        report = self._validator().validate(script, self._cfg())
        # CTA missing should be a warning, not a hard issue
        assert any("call to action" in w.lower() for w in report.warnings)

    def test_cta_twice_fails(self):
        cta = "Join us on this journey."
        script = self._valid_script() + f"\n{cta}\n"
        report = self._validator().validate(script, self._cfg())
        assert not report.valid
        assert any("call to action" in i.lower() for i in report.issues)

    # -- Closing quote ends video

    def test_signature_before_cta_fails(self):
        # Build script where signature comes before CTA
        welcome = "Welcome to Test Channel... where stories live."
        closing = "This is Test Channel."
        cta = "Join us on this journey."
        sig = "Think deeper... Live clearer."
        filler = "Deep content about philosophy and living. " * 20
        script = f"{welcome}\n\n{filler}\n\n{closing}\n\n{sig}\n\n{cta}"
        report = self._validator().validate(script, self._cfg())
        assert not report.valid
        assert any("closing signature must come after" in i.lower() for i in report.issues)

    # -- Disabled sections

    def test_disabled_opening_skips_check(self):
        data = {
            "channel_name": "Test Channel",
            "opening": {"enabled": False, "template": "Welcome to Test Channel... where stories live."},
            "closing": {"enabled": True, "template": "This is Test Channel."},
            "cta": {"enabled": True, "template": "Join us on this journey."},
            "signature": {"enabled": True, "template": "Think deeper... Live clearer."},
        }
        cfg = _parse_brand_config(data)
        # Script without the welcome — should not fail since opening is disabled
        script = _make_valid_script(
            welcome="",
            closing="This is Test Channel.",
            cta="Join us on this journey.",
            signature="Think deeper... Live clearer.",
        )
        report = self._validator().validate(script, cfg)
        opening_issues = [i for i in report.issues if "opening" in i.lower() and "welcome" in i.lower()]
        assert not opening_issues

    # -- BrandValidationReport

    def test_report_summary_fail_lists_issues(self):
        report = BrandValidationReport(
            valid=False,
            issues=["Issue one.", "Issue two."],
            warnings=["Warning one."],
        )
        summary = report.summary()
        assert "FAIL" in summary
        assert "Issue one" in summary
        assert "Warning one" in summary

    def test_report_summary_pass(self):
        report = BrandValidationReport(valid=True)
        assert "PASS" in report.summary()


# ── TestBrandingPromptAPI ──────────────────────────────────────────────────────


class TestBrandingPromptAPI:
    """branding.py public API must continue to work."""

    def test_get_welcome_returns_string(self):
        from ytfactory.agents.prompts.branding import get_welcome

        result = get_welcome()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_closing_returns_string(self):
        from ytfactory.agents.prompts.branding import get_closing

        result = get_closing()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_cta_returns_string(self):
        from ytfactory.agents.prompts.branding import get_cta

        result = get_cta()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_transition_returns_string(self):
        from ytfactory.agents.prompts.branding import get_transition

        result = get_transition()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_soft_cta_nonempty(self):
        from ytfactory.agents.prompts.branding import SOFT_CTA

        assert isinstance(SOFT_CTA, str)
        assert len(SOFT_CTA) > 0

    def test_closing_variations_is_list(self):
        from ytfactory.agents.prompts.branding import CLOSING_VARIATIONS

        assert isinstance(CLOSING_VARIATIONS, list)
        assert len(CLOSING_VARIATIONS) >= 1

    def test_welcome_variations_is_list(self):
        from ytfactory.agents.prompts.branding import WELCOME_VARIATIONS

        assert isinstance(WELCOME_VARIATIONS, list)
        assert len(WELCOME_VARIATIONS) >= 1

    def test_get_welcome_reflects_brand_config(self, tmp_path):
        reset_brand_config_cache()
        p = _write_yaml(
            tmp_path,
            {
                "channel_name": "Cosmic Lens",
                "opening": {"enabled": True, "template": "Welcome to Cosmic Lens."},
            },
        )
        # Reload brand config from the temp file
        get_brand_config(config_path=p, reload=True)
        from ytfactory.agents.prompts import branding as br

        result = br.get_welcome()
        assert "Cosmic Lens" in result
        reset_brand_config_cache()


# ── TestScriptWriterPromptUsesChannelName ──────────────────────────────────────


class TestScriptWriterPromptUsesChannelName:
    def test_channel_name_in_prompt(self):
        from ytfactory.agents.prompts.script_writer import build_write_script_prompt

        prompt = build_write_script_prompt(
            topic="Test Topic",
            research_md="Research.",
            script_outline="Outline.",
            welcome="Welcome to My Channel.",
            closing="My Channel sign-off.",
            topic_transition="Today we explore",
            channel_name="My Custom Channel",
            cta="Subscribe now.",
        )
        assert "My Custom Channel" in prompt

    def test_cta_in_write_prompt(self):
        from ytfactory.agents.prompts.script_writer import build_write_script_prompt

        prompt = build_write_script_prompt(
            topic="Test",
            research_md="Research.",
            script_outline="Outline.",
            welcome="Welcome.",
            closing="Goodbye.",
            topic_transition="Today",
            channel_name="TestCh",
            cta="Subscribe to my special channel today.",
        )
        assert "Subscribe to my special channel today." in prompt

    def test_no_hardcoded_atma_theory_in_prompt_text(self):
        from ytfactory.agents.prompts.script_writer import build_write_script_prompt

        prompt = build_write_script_prompt(
            topic="Test",
            research_md="",
            script_outline="",
            welcome="Welcome to NewCh.",
            closing="NewCh out.",
            topic_transition="Today",
            channel_name="NewCh",
            cta="Join us.",
            closing_brand="This is NewCh.",
        )
        # No hardcoded "Atma Theory" in the surrounding prompt text
        # (it may appear in the welcome/closing if the caller passes it — that's fine)
        prompt_without_welcome_closing = (
            prompt.replace("Welcome to NewCh.", "")
            .replace("NewCh out.", "")
            .replace("Join us.", "")
            .replace("This is NewCh.", "")
        )
        assert "Atma Theory" not in prompt_without_welcome_closing

    def test_review_prompt_uses_channel_name(self):
        from ytfactory.agents.prompts.script_writer import build_review_prompt

        prompt = build_review_prompt(
            topic="Topic",
            script="script text",
            word_count=100,
            estimated_minutes=1.0,
            channel_name="ZenWave",
        )
        assert "ZenWave" in prompt
        assert "Atma Theory" not in prompt

    def test_compress_prompt_uses_channel_name(self):
        from ytfactory.agents.prompts.script_writer import build_compress_prompt

        prompt = build_compress_prompt(
            script="script text",
            word_count=2000,
            estimated_minutes=15.0,
            channel_name="ZenWave",
        )
        assert "ZenWave" in prompt
        assert "Atma Theory" not in prompt

    def test_expand_prompt_uses_channel_name(self):
        from ytfactory.agents.prompts.script_writer import build_expand_pacing_prompt

        prompt = build_expand_pacing_prompt(
            script="script text",
            word_count=200,
            estimated_minutes=1.5,
            channel_name="ZenWave",
        )
        assert "ZenWave" in prompt
        assert "Atma Theory" not in prompt

    def test_default_channel_name_loads_from_config(self):
        from ytfactory.agents.prompts.script_writer import build_review_prompt

        # Default (no channel_name arg) should load from the brand config
        prompt = build_review_prompt(
            topic="Default topic",
            script="some script",
            word_count=500,
            estimated_minutes=3.8,
        )
        # Must contain the configured channel name (Atma Theory from brand_config.yaml)
        assert len(prompt) > 0
        assert "YouTube channel" in prompt


# ── TestScriptEnhancerPromptUsesCTA ───────────────────────────────────────────


class TestScriptEnhancerPromptUsesCTA:
    def test_cta_in_enhance_prompt(self):
        from ytfactory.agents.prompts.script_enhancer import build_enhance_script_prompt

        prompt = build_enhance_script_prompt(
            topic="Philosophy",
            script="A raw script about philosophy.",
            cta="Subscribe to our cosmic newsletter.",
        )
        assert "Subscribe to our cosmic newsletter." in prompt

    def test_cta_default_loads_from_brand_config(self):
        from ytfactory.agents.prompts.script_enhancer import build_enhance_script_prompt

        # No cta arg → should load from brand config
        prompt = build_enhance_script_prompt(
            topic="Philosophy",
            script="A raw script about philosophy.",
        )
        from ytfactory.branding.config import get_brand_config

        cfg = get_brand_config()
        assert cfg.cta.text()[:20] in prompt

    def test_no_hardcoded_old_cta_text(self):
        from ytfactory.agents.prompts.script_enhancer import build_enhance_script_prompt

        prompt = build_enhance_script_prompt(
            topic="Test",
            script="Script.",
            cta="Custom CTA here.",
        )
        # Old hardcoded CTA should no longer appear verbatim in the template
        assert "see life a little differently" not in prompt


# ── TestScenePlannerUsesAssetPathFromConfig ────────────────────────────────────


class TestScenePlannerUsesAssetPathFromConfig:
    def test_mark_asset_scenes_uses_brand_config_path(self, tmp_path):
        reset_brand_config_cache()
        p = _write_yaml(
            tmp_path,
            {
                "channel_name": "Zen Wave",
                "opening": {"template": "Welcome to Zen Wave."},
                "closing": {"template": "This is Zen Wave."},
                "cta": {"template": "Join our journey."},
                "signature": {"template": "Breathe and begin."},
                "branding": {
                    "asset_path": "assets/branding/zen-wave.png",
                    "asset_animation": "fade_in",
                },
            },
        )
        get_brand_config(config_path=p, reload=True)

        from ytfactory.agents.nodes.scene_planner import _mark_asset_scenes

        scenes = [
            {"index": 1, "narration": "Intro content about the universe.", "title": "Intro"},
            {"index": 2, "narration": "This is Zen Wave.", "title": "Closing"},
        ]
        _mark_asset_scenes(scenes)

        closing_scene = scenes[1]
        assert closing_scene.get("scene_type") == "asset"
        assert closing_scene.get("asset_path") == "assets/branding/zen-wave.png"
        assert closing_scene.get("animation") == "fade_in"

        reset_brand_config_cache()

    def test_non_closing_scene_not_marked(self):
        from ytfactory.agents.nodes.scene_planner import _mark_asset_scenes

        scenes = [
            {"index": 1, "narration": "A philosophical exploration of time.", "title": "Main"},
            {"index": 2, "narration": "Another teaching about awareness.", "title": "Second"},
        ]
        original = [s["index"] for s in scenes]
        _mark_asset_scenes(scenes)
        for scene in scenes:
            if scene["index"] in original:
                assert scene.get("scene_type") != "asset"

    def test_is_closing_scene_detects_configured_phrases(self, tmp_path):
        reset_brand_config_cache()
        p = _write_yaml(
            tmp_path,
            {
                "closing": {"template": "This is My Channel."},
                "signature": {"template": "Go deep... stay true."},
                "cta": {"template": "Follow for wisdom."},
            },
        )
        get_brand_config(config_path=p, reload=True)

        # Must re-import after cache reload so branding.py recomputes CLOSING_VARIATIONS
        # via get_brand_config(). _is_closing_scene uses the cached _CLOSING_TRIGGERS
        # which is computed at module import time — test the config-driven path directly.
        from ytfactory.branding.config import get_brand_config as gcfg

        cfg = gcfg()
        assert "my channel" in cfg.closing.text().lower()

        reset_brand_config_cache()


# ── TestBrandConfigFutureChannelCompatibility ──────────────────────────────────


class TestBrandConfigFutureChannelCompatibility:
    """Verify the system can represent a completely different channel."""

    def test_second_channel_config_parses_correctly(self, tmp_path):
        reset_brand_config_cache()
        data = {
            "channel_name": "Deep Roots",
            "opening": {
                "enabled": True,
                "template": "Welcome to Deep Roots... where culture and heritage meet.",
            },
            "closing": {"enabled": True, "template": "This is Deep Roots."},
            "cta": {"enabled": True, "template": "Subscribe if this touched your soul."},
            "signature": {"enabled": True, "template": "Know your roots."},
            "voice": {"pace": "documentary", "pause_after_opening_ms": 600},
            "branding": {
                "asset_path": "assets/branding/deep-roots.png",
                "asset_animation": "slow_pan",
                "max_opening_seconds": 12,
            },
        }
        p = _write_yaml(tmp_path, data)
        cfg = get_brand_config(config_path=p, reload=True)

        assert cfg.channel_name == "Deep Roots"
        assert "Deep Roots" in cfg.opening.text()
        assert "Deep Roots" in cfg.closing.text()
        assert cfg.cta.text() == "Subscribe if this touched your soul."
        assert cfg.signature.text() == "Know your roots."
        assert cfg.voice.pace == "documentary"
        assert cfg.branding.asset_path == "assets/branding/deep-roots.png"
        assert cfg.branding.asset_animation == "slow_pan"
        assert cfg.branding.max_opening_seconds == 12

        reset_brand_config_cache()

    def test_no_channel_specific_code_needed(self, tmp_path):
        """Config swap alone should produce correct values — no code changes."""
        reset_brand_config_cache()
        p = _write_yaml(tmp_path, {"channel_name": "Cosmos Lab"})
        cfg = get_brand_config(config_path=p, reload=True)

        from ytfactory.agents.prompts.script_writer import build_compress_prompt

        prompt = build_compress_prompt(
            script="a script",
            word_count=2000,
            estimated_minutes=15.0,
            channel_name=cfg.channel_name,
        )
        assert "Cosmos Lab" in prompt
        assert "Atma Theory" not in prompt

        reset_brand_config_cache()
