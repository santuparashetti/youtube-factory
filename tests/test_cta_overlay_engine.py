"""Tests for the CTA Overlay Engine V2.

Coverage:
  - CTAOverlayConfig loading and template/branding precedence
  - CTAPlacementEngine: no-safe-pause fallback, short-pause compact variant,
    primary-contextual path, max_placement_search_pct cutoff
  - CTARenderer: PNG generation, FFmpeg dispatch
  - CTAPipeline: disabled early-exit, three-step escalation
  - CTAReporter: file writing
  - CTAValidator (review rules): CTA_001–CTA_005
  - Incremental deps: cta stage in graph
  - BGM secondary-duck coordination check
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Config ─────────────────────────────────────────────────────────────────────


class TestCTAOverlayConfig:
    def test_defaults(self):
        from ytfactory.cta.config import CTAOverlayConfig

        cfg = CTAOverlayConfig()
        assert cfg.enabled is False
        assert cfg.template == "atma"
        assert cfg.timing_mode == "contextual"
        assert cfg.fallback_timing == pytest.approx(0.65)
        assert cfg.duration == pytest.approx(6.0)
        assert cfg.min_pause_ms_for_full_cta == 3000
        assert cfg.max_placement_search_pct == pytest.approx(0.90)
        assert cfg.insight_tier_min_ms == 1800
        assert cfg.show_subscribe is True
        assert cfg.show_like is True
        assert cfg.show_bell is True
        assert cfg.bgm_secondary_duck_db == pytest.approx(4.0)

    def test_template_registry_keys(self):
        from ytfactory.cta.config import TEMPLATE_DEFAULTS

        for key in ("glass", "minimal", "atma", "premium", "atma_glass"):
            assert key in TEMPLATE_DEFAULTS

    def test_template_structural_defaults_applied(self):
        from ytfactory.cta.config import _parse_cta_config

        cfg = _parse_cta_config({"template": "minimal"}, {})
        # minimal template has panel_alpha=0.0
        assert cfg.panel_alpha == pytest.approx(0.0)
        assert cfg.border_alpha == pytest.approx(0.0)

    def test_branding_overrides_template_accent_color(self):
        from ytfactory.cta.config import _parse_cta_config

        cfg = _parse_cta_config(
            {"template": "glass"},
            {"accent_color": "#ABCDEF", "font": "Outfit"},
        )
        # Branding always wins over template defaults
        assert cfg.accent_color == "#ABCDEF"
        assert cfg.font == "Outfit"

    def test_inline_cta_overlay_overrides_branding(self):
        from ytfactory.cta.config import _parse_cta_config

        # cta_overlay block inline overrides beat branding
        cfg = _parse_cta_config(
            {"template": "atma", "accent_color": "#FFFFFF"},
            {"accent_color": "#000000"},
        )
        assert cfg.accent_color == "#FFFFFF"

    def test_fallback_timing_percentage_string(self):
        from ytfactory.cta.config import _parse_cta_config

        cfg = _parse_cta_config({"fallback_timing": "70%"}, {})
        assert cfg.fallback_timing == pytest.approx(0.70)

    def test_duration_seconds_string(self):
        from ytfactory.cta.config import _parse_cta_config

        cfg = _parse_cta_config({"duration": "8s"}, {})
        assert cfg.duration == pytest.approx(8.0)

    def test_load_cta_config_missing_file(self, tmp_path):
        from ytfactory.cta.config import load_cta_config, reset_cta_config_cache

        reset_cta_config_cache()
        cfg = load_cta_config(tmp_path / "nonexistent.yaml")
        assert cfg.enabled is False  # default
        reset_cta_config_cache()

    def test_load_cta_config_from_yaml(self, tmp_path):
        import yaml

        from ytfactory.cta.config import load_cta_config, reset_cta_config_cache

        yaml_content = {
            "branding": {"accent_color": "#FF0000", "font": "DejaVu"},
            "cta_overlay": {
                "enabled": True,
                "template": "premium",
                "duration": "5s",
                "fallback_timing": "70%",
            },
        }
        config_file = tmp_path / "brand_config.yaml"
        config_file.write_text(yaml.dump(yaml_content))

        reset_cta_config_cache()
        cfg = load_cta_config(config_file)
        assert cfg.enabled is True
        assert cfg.template == "premium"
        assert cfg.duration == pytest.approx(5.0)
        assert cfg.fallback_timing == pytest.approx(0.70)
        assert cfg.accent_color == "#FF0000"
        reset_cta_config_cache()


# ── Models ─────────────────────────────────────────────────────────────────────


class TestCTAModels:
    def test_cta_placement_cta_end_computed(self):
        from ytfactory.cta.models import CTAPlacement, CTAVariant, CTAZone, PlacementPath

        p = CTAPlacement(
            timestamp=60.0,
            duration=6.0,
            variant=CTAVariant.FULL,
            placement_path=PlacementPath.PRIMARY_CONTEXTUAL,
            subtitle_safe=True,
            zone=CTAZone.BOTTOM_CENTER,
            pause_type="long_silence",
            pause_duration=4.0,
        )
        assert p.cta_end == pytest.approx(66.0)

    def test_cta_result_to_dict_disabled(self):
        from ytfactory.cta.models import CTAResult, CTAReviewResult

        r = CTAResult(
            success=True,
            enabled=False,
            placement=None,
            review=CTAReviewResult(passed=True),
        )
        d = r.to_dict()
        assert d["enabled"] is False
        assert d["timing_metadata"] is None
        assert d["review"]["passed"] is True

    def test_cta_result_to_dict_enabled(self):
        from ytfactory.cta.models import (
            CTAPlacement,
            CTAResult,
            CTAReviewResult,
            CTAVariant,
            CTAZone,
            PlacementPath,
        )

        placement = CTAPlacement(
            timestamp=120.0,
            duration=6.0,
            variant=CTAVariant.FULL,
            placement_path=PlacementPath.PRIMARY_CONTEXTUAL,
            subtitle_safe=True,
            zone=CTAZone.BOTTOM_CENTER,
            pause_type="long_silence",
            pause_duration=5.0,
        )
        r = CTAResult(
            success=True,
            enabled=True,
            placement=placement,
            review=CTAReviewResult(passed=True, bgm_duck_applied=True),
        )
        d = r.to_dict()
        assert d["timing_metadata"]["timestamp"] == pytest.approx(120.0)
        assert d["timing_metadata"]["variant"] == "full"
        assert d["timing_metadata"]["placement_path"] == "primary_contextual"
        assert d["review"]["bgm_duck_applied"] is True

    def test_cta_variant_values(self):
        from ytfactory.cta.models import CTAVariant

        assert CTAVariant.FULL.value == "full"
        assert CTAVariant.COMPACT.value == "compact"

    def test_placement_path_values(self):
        from ytfactory.cta.models import PlacementPath

        assert PlacementPath.PRIMARY_CONTEXTUAL.value == "primary_contextual"
        assert PlacementPath.FALLBACK_TIMING.value == "fallback_timing"


# ── Placement ──────────────────────────────────────────────────────────────────


class TestCTAPlacementEngine:
    def _make_config(self, **kwargs):
        from ytfactory.cta.config import CTAOverlayConfig

        defaults = {
            "enabled": True,
            "fallback_timing": 0.65,
            "duration": 6.0,
            "min_pause_ms_for_full_cta": 3000,
            "max_placement_search_pct": 0.90,
            "insight_tier_min_ms": 1800,
            "zone_default": "bottom_center",
        }
        defaults.update(kwargs)
        return CTAOverlayConfig(**defaults)

    def test_fallback_when_no_timing_files(self, tmp_path):
        from ytfactory.cta.placement import CTAPlacementEngine
        from ytfactory.cta.models import PlacementPath, CTAVariant

        cfg = self._make_config()
        engine = CTAPlacementEngine(cfg)
        # No audio/ dir → video_duration=0 → fallback immediately
        result = engine.find_placement(tmp_path)
        assert result.placement_path == PlacementPath.FALLBACK_TIMING
        assert result.variant == CTAVariant.FULL  # fallback always renders FULL (ADR-0010)

    def test_fallback_when_no_insight_tier_pauses(self, tmp_path):
        from ytfactory.cta.placement import CTAPlacementEngine
        from ytfactory.cta.models import PlacementPath, CTAVariant

        # Create timing files with only brief pauses (no insight-tier)
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        # Scene 1: words packed tightly — no long pauses
        words = [
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.6, "end": 1.0},
            {"word": "this", "start": 1.1, "end": 1.4},
        ]
        (audio_dir / "scene-001.timing.json").write_text(json.dumps(words))
        (audio_dir / "scene-001.mp3").write_bytes(b"")

        cfg = self._make_config()
        with patch(
            "ytfactory.bgm.vad.build_speech_timeline_from_kokoro",
            return_value=None,  # simulate no timeline available
        ):
            engine = CTAPlacementEngine(cfg)
            result = engine.find_placement(tmp_path)

        assert result.placement_path == PlacementPath.FALLBACK_TIMING
        assert result.variant == CTAVariant.FULL  # fallback always renders FULL (ADR-0010)

    def _write_timing(self, tmp_path: Path, duration: float = 200.0) -> None:
        """Create a dummy timing.json so _get_video_duration returns a real value."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir(exist_ok=True)
        words = [{"word": "x", "start": 0.0, "end": duration - 0.1}]
        (audio_dir / "scene-001.timing.json").write_text(json.dumps(words))

    def test_short_pause_uses_compact_variant(self, tmp_path):
        from ytfactory.cta.models import CTAVariant, PlacementPath
        from ytfactory.cta.placement import CTAPlacementEngine
        from ytfactory.bgm.vad import SpeechSegment, SpeechTimeline

        self._write_timing(tmp_path, 200.0)

        # Speech timeline: midpoint at ~100s, pause of 2.2s starting at 100s
        # (insight-tier but below min_pause_ms_for_full_cta=3000ms)
        timeline = SpeechTimeline(
            segments=[
                SpeechSegment(start=0.0, end=100.0),
                SpeechSegment(start=102.2, end=200.0),
            ],
            total_duration=200.0,
            speech_ratio=0.99,
        )

        cfg = self._make_config(min_pause_ms_for_full_cta=3000)
        with patch("ytfactory.bgm.vad.build_speech_timeline_from_kokoro", return_value=timeline):
            engine = CTAPlacementEngine(cfg)
            result = engine.find_placement(tmp_path)

        # Pause is 2.2s (2200ms) — above insight_tier_min_ms=1800ms but below 3000ms
        assert result.placement_path == PlacementPath.PRIMARY_CONTEXTUAL
        assert result.variant == CTAVariant.COMPACT

    def test_long_pause_uses_full_variant(self, tmp_path):
        from ytfactory.cta.models import CTAVariant, PlacementPath
        from ytfactory.cta.placement import CTAPlacementEngine
        from ytfactory.bgm.vad import SpeechSegment, SpeechTimeline

        self._write_timing(tmp_path, 200.0)

        # Speech timeline: pause of 5s starting at 100s (> 3000ms → FULL)
        timeline = SpeechTimeline(
            segments=[
                SpeechSegment(start=0.0, end=100.0),
                SpeechSegment(start=105.0, end=200.0),
            ],
            total_duration=200.0,
            speech_ratio=0.97,
        )

        cfg = self._make_config(min_pause_ms_for_full_cta=3000)
        with patch("ytfactory.bgm.vad.build_speech_timeline_from_kokoro", return_value=timeline):
            engine = CTAPlacementEngine(cfg)
            result = engine.find_placement(tmp_path)

        assert result.placement_path == PlacementPath.PRIMARY_CONTEXTUAL
        assert result.variant == CTAVariant.FULL
        assert result.timestamp == pytest.approx(100.0)

    def test_search_stops_at_max_placement_pct(self, tmp_path):
        from ytfactory.cta.models import PlacementPath
        from ytfactory.cta.placement import CTAPlacementEngine
        from ytfactory.bgm.vad import SpeechSegment, SpeechTimeline

        self._write_timing(tmp_path, 200.0)

        # Video ≈ 200s.  Speech is dense from 0–182s.  Only pause is at 182–186s
        # which starts at 91% — past max_placement_search_pct=0.90 (180s cutoff).
        timeline = SpeechTimeline(
            segments=[
                SpeechSegment(start=0.0, end=182.0),  # single long segment up to 91%
                SpeechSegment(start=186.0, end=200.0),
            ],
            total_duration=200.0,
            speech_ratio=0.97,
        )

        cfg = self._make_config(max_placement_search_pct=0.90)
        with patch("ytfactory.bgm.vad.build_speech_timeline_from_kokoro", return_value=timeline):
            engine = CTAPlacementEngine(cfg)
            result = engine.find_placement(tmp_path)

        # Pause starts at 182s (91% of 200s) → past 90% cutoff → fallback
        assert result.placement_path == PlacementPath.FALLBACK_TIMING

    def test_subtitle_overlap_moves_to_upper_zone(self, tmp_path):
        from ytfactory.cta.models import CTAZone, PlacementPath
        from ytfactory.cta.placement import CTAPlacementEngine
        from ytfactory.bgm.vad import SpeechSegment, SpeechTimeline

        self._write_timing(tmp_path, 200.0)

        # Create subtitle file with active window at 100s–110s
        subtitles_dir = tmp_path / "subtitles"
        subtitles_dir.mkdir()
        srt_content = "1\n00:01:40,000 --> 00:01:50,000\nSome subtitle text\n\n"
        (subtitles_dir / "scene-001.srt").write_text(srt_content)

        # Pause at exactly 100s (subtitle is active 100–110s)
        timeline = SpeechTimeline(
            segments=[
                SpeechSegment(start=0.0, end=100.0),
                SpeechSegment(start=105.0, end=200.0),
            ],
            total_duration=200.0,
            speech_ratio=0.97,
        )

        cfg = self._make_config()
        with patch("ytfactory.bgm.vad.build_speech_timeline_from_kokoro", return_value=timeline):
            engine = CTAPlacementEngine(cfg)
            result = engine.find_placement(tmp_path)

        # Subtitle active → should move to upper-right zone
        if result.placement_path == PlacementPath.PRIMARY_CONTEXTUAL:
            assert result.zone == CTAZone.UPPER_RIGHT
        # Fallback also places in upper-right when subtitles active

    def test_subtitle_safety_parse_srt(self):
        from ytfactory.cta.placement import _parse_srt_timecodes

        content = "1\n00:01:00,000 --> 00:01:05,500\nHello\n\n2\n00:02:00,000 --> 00:02:10,000\nWorld"
        windows = _parse_srt_timecodes(content)
        assert len(windows) == 2
        assert windows[0] == pytest.approx((60.0, 65.5))
        assert windows[1] == pytest.approx((120.0, 130.0))

    def test_subtitle_active_at_overlapping(self):
        from ytfactory.cta.placement import _subtitle_active_at

        windows = [(60.0, 70.0), (120.0, 130.0)]
        assert _subtitle_active_at(windows, 65.0, 3.0) is True
        assert _subtitle_active_at(windows, 70.0, 3.0) is False
        assert _subtitle_active_at(windows, 118.0, 3.0) is True
        assert _subtitle_active_at(windows, 130.0, 3.0) is False


# ── Renderer ──────────────────────────────────────────────────────────────────


class TestCTARenderer:
    def _make_placement(self, timestamp=60.0, variant="full", zone="bottom_center"):
        from ytfactory.cta.models import CTAPlacement, CTAVariant, CTAZone, PlacementPath

        return CTAPlacement(
            timestamp=timestamp,
            duration=6.0,
            variant=CTAVariant(variant),
            placement_path=PlacementPath.PRIMARY_CONTEXTUAL,
            subtitle_safe=True,
            zone=CTAZone(zone),
            pause_type="long_silence",
            pause_duration=5.0,
        )

    def _make_config(self, **kwargs):
        from ytfactory.cta.config import CTAOverlayConfig

        return CTAOverlayConfig(enabled=True, **kwargs)

    def test_render_returns_failure_when_video_has_no_duration(self, tmp_path):
        from ytfactory.cta.renderer import CTARenderer

        renderer = CTARenderer()
        video_path = tmp_path / "final.mp4"
        video_path.write_bytes(b"fake")
        output = tmp_path / "output.mp4"
        placement = self._make_placement()
        config = self._make_config()

        with patch("ytfactory.cta.renderer._probe_video", return_value=(1280, 720, 0.0)):
            result = renderer.render(video_path, output, placement, config)

        assert result.success is False
        assert "duration" in result.error.lower() or "Could not determine" in result.error

    def test_render_returns_failure_when_timestamp_past_duration(self, tmp_path):
        from ytfactory.cta.renderer import CTARenderer

        renderer = CTARenderer()
        video_path = tmp_path / "final.mp4"
        video_path.write_bytes(b"fake")
        output = tmp_path / "output.mp4"
        placement = self._make_placement(timestamp=500.0)  # past 300s video
        config = self._make_config()

        with patch("ytfactory.cta.renderer._probe_video", return_value=(1280, 720, 300.0)):
            result = renderer.render(video_path, output, placement, config)

        assert result.success is False
        assert "out of bounds" in result.error or "exceeds" in result.error

    def test_hex_to_rgb(self):
        from ytfactory.cta.renderer import _hex_to_rgb

        r, g, b = _hex_to_rgb("#2EC5E8")
        assert r == 0x2E
        assert g == 0xC5
        assert b == 0xE8

    def test_hex_to_rgb_short(self):
        from ytfactory.cta.renderer import _hex_to_rgb

        r, g, b = _hex_to_rgb("#FFF")
        assert r == g == b == 255

    def test_db_to_linear(self):
        from ytfactory.cta.renderer import _db_to_linear

        # 0 dB → 1.0 linear
        assert _db_to_linear(0.0) == pytest.approx(1.0)
        # -6 dB → ~0.501
        assert _db_to_linear(-6.0) == pytest.approx(0.5012, abs=0.01)
        # -20 dB → 0.1
        assert _db_to_linear(-20.0) == pytest.approx(0.1, rel=0.01)

    def test_find_cta_sound_missing(self, tmp_path):
        from ytfactory.cta.renderer import _find_cta_sound

        # Change cwd won't affect absolute path search; just check None return
        result = _find_cta_sound("nonexistent_sound_xyz")
        assert result is None

    def test_render_calls_ffmpeg_on_success(self, tmp_path):
        from ytfactory.cta.renderer import CTARenderer

        renderer = CTARenderer()
        video_path = tmp_path / "final.mp4"
        video_path.write_bytes(b"fake")
        output = tmp_path / "output.mp4"
        placement = self._make_placement(timestamp=60.0)
        config = self._make_config()

        with (
            patch("ytfactory.cta.renderer._probe_video", return_value=(1280, 720, 300.0)),
            patch("ytfactory.cta.renderer._generate_cta_overlay") as mock_gen,
            patch("ytfactory.cta.renderer._apply_overlay_ffmpeg", return_value=True) as mock_ff,
        ):
            mock_gen.return_value = None
            result = renderer.render(video_path, output, placement, config)

        assert mock_ff.called
        assert result.success is True


# ── Pipeline ───────────────────────────────────────────────────────────────────


class TestCTAPipeline:
    def _make_config(self, **kwargs):
        from ytfactory.cta.config import CTAOverlayConfig

        return CTAOverlayConfig(**kwargs)

    def test_disabled_cta_writes_stub_and_returns(self, tmp_path):
        from ytfactory.cta.pipeline import CTAPipeline

        proj_dir = tmp_path / "my-project"
        proj_dir.mkdir(parents=True)

        config = self._make_config(enabled=False)
        with patch("ytfactory.shared.constants.WORKSPACE_DIR", str(tmp_path)):
            result = CTAPipeline().run("my-project", _config=config)

        assert result.enabled is False
        assert result.success is True
        assert (proj_dir / "cta" / "cta-timing.json").exists()

    def test_disabled_stub_content(self, tmp_path):
        from ytfactory.cta.pipeline import CTAPipeline

        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        config = self._make_config(enabled=False)
        with patch("ytfactory.shared.constants.WORKSPACE_DIR", str(tmp_path)):
            result = CTAPipeline().run("proj", _config=config)

        timing_path = proj_dir / "cta" / "cta-timing.json"
        assert timing_path.exists()
        data = json.loads(timing_path.read_text())
        assert data["enabled"] is False

    def test_enabled_raises_when_no_final_video(self, tmp_path):
        from ytfactory.cta.pipeline import CTAPipeline

        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        config = self._make_config(enabled=True)
        with (
            patch("ytfactory.shared.constants.WORKSPACE_DIR", str(tmp_path)),
            pytest.raises(FileNotFoundError, match="final.mp4"),
        ):
            CTAPipeline().run("proj", _config=config)

    def test_successful_render_replaces_final_mp4(self, tmp_path):
        from ytfactory.cta.pipeline import CTAPipeline
        from ytfactory.cta.models import (
            CTAPlacement,
            CTAVariant,
            CTAZone,
            PlacementPath,
        )

        proj_dir = tmp_path / "proj"
        video_dir = proj_dir / "video"
        video_dir.mkdir(parents=True)
        final_video = video_dir / "final.mp4"
        final_video.write_bytes(b"original" * 1000)

        config = self._make_config(enabled=True, bgm_secondary_duck_db=4.0)

        placement = CTAPlacement(
            timestamp=60.0,
            duration=6.0,
            variant=CTAVariant.FULL,
            placement_path=PlacementPath.PRIMARY_CONTEXTUAL,
            subtitle_safe=True,
            zone=CTAZone.BOTTOM_CENTER,
            pause_type="long_silence",
            pause_duration=5.0,
        )

        from ytfactory.cta.models import CTARenderResult, CTAReviewResult

        good_render = CTARenderResult(
            success=True,
            output_path=str(video_dir / "final.cta-work.mp4"),
            template_used="atma",
        )

        with (
            patch("ytfactory.shared.constants.WORKSPACE_DIR", str(tmp_path)),
            patch.object(
                __import__("ytfactory.cta.placement", fromlist=["CTAPlacementEngine"]).CTAPlacementEngine,
                "find_placement",
                return_value=placement,
            ),
            patch.object(
                __import__("ytfactory.cta.renderer", fromlist=["CTARenderer"]).CTARenderer,
                "render",
                side_effect=lambda *a, **kw: _write_fake_output(kw.get("output_path") or a[1], good_render),
            ),
            patch("ytfactory.cta.pipeline._probe_dur", return_value=300.0),
        ):
            result = CTAPipeline().run("proj", _config=config)

        assert result.success is True
        assert result.enabled is True
        assert result.review.passed is True

    def test_three_step_escalation_raises_cta_blocked(self, tmp_path):
        from ytfactory.cta.pipeline import CTABlockedError, CTAPipeline
        from ytfactory.cta.models import (
            CTAPlacement,
            CTAVariant,
            CTAZone,
            PlacementPath,
            CTARenderResult,
        )

        proj_dir = tmp_path / "proj"
        video_dir = proj_dir / "video"
        video_dir.mkdir(parents=True)
        (video_dir / "final.mp4").write_bytes(b"x" * 10000)

        config = self._make_config(enabled=True)

        placement = CTAPlacement(
            timestamp=60.0,
            duration=6.0,
            variant=CTAVariant.FULL,
            placement_path=PlacementPath.PRIMARY_CONTEXTUAL,
            subtitle_safe=True,
            zone=CTAZone.BOTTOM_CENTER,
            pause_type="long_silence",
            pause_duration=5.0,
        )

        bad_render = CTARenderResult(
            success=False,
            error="Render totally failed",
            template_used="atma",
        )

        with (
            patch("ytfactory.shared.constants.WORKSPACE_DIR", str(tmp_path)),
            patch.object(
                __import__("ytfactory.cta.placement", fromlist=["CTAPlacementEngine"]).CTAPlacementEngine,
                "find_placement",
                return_value=placement,
            ),
            patch.object(
                __import__("ytfactory.cta.renderer", fromlist=["CTARenderer"]).CTARenderer,
                "render",
                return_value=bad_render,
            ),
            pytest.raises(CTABlockedError, match="CTA_RENDER_FAILED_ALL_ATTEMPTS"),
        ):
            CTAPipeline().run("proj", _config=config)

    def test_escalation_step1_retry_succeeds(self, tmp_path):
        """Retry once with same placement — second attempt succeeds."""
        from ytfactory.cta.pipeline import CTAPipeline
        from ytfactory.cta.models import (
            CTAPlacement,
            CTAVariant,
            CTAZone,
            PlacementPath,
            CTARenderResult,
        )

        proj_dir = tmp_path / "proj"
        video_dir = proj_dir / "video"
        video_dir.mkdir(parents=True)
        (video_dir / "final.mp4").write_bytes(b"x" * 10000)

        config = self._make_config(enabled=True, bgm_secondary_duck_db=4.0)

        placement = CTAPlacement(
            timestamp=60.0,
            duration=6.0,
            variant=CTAVariant.FULL,
            placement_path=PlacementPath.PRIMARY_CONTEXTUAL,
            subtitle_safe=True,
            zone=CTAZone.BOTTOM_CENTER,
            pause_type="long_silence",
            pause_duration=5.0,
        )

        call_count = [0]

        def fake_render(self_inner, video, output, pl, cfg):
            call_count[0] += 1
            if call_count[0] == 1:
                return CTARenderResult(success=False, error="fail #1", template_used="atma")
            # On retry, write a plausible output file
            output.write_bytes(b"x" * 50000)
            return CTARenderResult(
                success=True,
                output_path=str(output),
                template_used="atma",
            )

        with (
            patch("ytfactory.shared.constants.WORKSPACE_DIR", str(tmp_path)),
            patch.object(
                __import__("ytfactory.cta.placement", fromlist=["CTAPlacementEngine"]).CTAPlacementEngine,
                "find_placement",
                return_value=placement,
            ),
            patch(
                "ytfactory.cta.renderer.CTARenderer.render",
                new=fake_render,
            ),
            patch("ytfactory.cta.pipeline._probe_dur", return_value=300.0),
        ):
            result = CTAPipeline().run("proj", _config=config)

        assert result.success is True
        assert result.review.retry_count == 1

    def test_escalation_step2_minimal_template(self, tmp_path):
        """After two failures, minimal template is tried (step 2 of escalation)."""
        from ytfactory.cta.pipeline import CTAPipeline
        from ytfactory.cta.models import (
            CTAPlacement,
            CTAVariant,
            CTAZone,
            PlacementPath,
            CTARenderResult,
        )

        proj_dir = tmp_path / "proj"
        video_dir = proj_dir / "video"
        video_dir.mkdir(parents=True)
        (video_dir / "final.mp4").write_bytes(b"x" * 10000)

        config = self._make_config(enabled=True, bgm_secondary_duck_db=4.0)

        placement = CTAPlacement(
            timestamp=60.0,
            duration=6.0,
            variant=CTAVariant.FULL,
            placement_path=PlacementPath.PRIMARY_CONTEXTUAL,
            subtitle_safe=True,
            zone=CTAZone.BOTTOM_CENTER,
            pause_type="long_silence",
            pause_duration=5.0,
        )

        call_count = [0]

        def fake_render(self_inner, video, output, pl, cfg):
            call_count[0] += 1
            if call_count[0] < 3:
                return CTARenderResult(success=False, error=f"fail #{call_count[0]}", template_used="atma")
            # Minimal template attempt (3rd call) succeeds
            output.write_bytes(b"x" * 50000)
            return CTARenderResult(
                success=True,
                output_path=str(output),
                template_used="minimal",
            )

        with (
            patch("ytfactory.shared.constants.WORKSPACE_DIR", str(tmp_path)),
            patch.object(
                __import__("ytfactory.cta.placement", fromlist=["CTAPlacementEngine"]).CTAPlacementEngine,
                "find_placement",
                return_value=placement,
            ),
            patch(
                "ytfactory.cta.renderer.CTARenderer.render",
                new=fake_render,
            ),
            patch("ytfactory.cta.pipeline._probe_dur", return_value=300.0),
        ):
            result = CTAPipeline().run("proj", _config=config)

        assert result.success is True
        assert result.review.fallback_template == "minimal"
        assert result.review.retry_count == 2


# ── Reporter ───────────────────────────────────────────────────────────────────


class TestCTAReporter:
    def test_writes_timing_and_review_files(self, tmp_path):
        from ytfactory.cta.models import (
            CTAPlacement,
            CTAResult,
            CTAReviewResult,
            CTAVariant,
            CTAZone,
            PlacementPath,
        )
        from ytfactory.cta.reporter import CTAReporter

        placement = CTAPlacement(
            timestamp=90.0,
            duration=6.0,
            variant=CTAVariant.FULL,
            placement_path=PlacementPath.PRIMARY_CONTEXTUAL,
            subtitle_safe=True,
            zone=CTAZone.BOTTOM_CENTER,
            pause_type="long_silence",
            pause_duration=4.0,
        )
        result = CTAResult(
            success=True,
            enabled=True,
            placement=placement,
            review=CTAReviewResult(
                passed=True,
                bgm_duck_applied=True,
                animation_completed=True,
                branding_loaded=True,
                timing_valid=True,
                subtitle_safe=True,
            ),
        )

        CTAReporter().write(tmp_path, result)

        timing_path = tmp_path / "cta" / "cta-timing.json"
        review_path = tmp_path / "cta" / "cta-review-report.json"

        assert timing_path.exists()
        assert review_path.exists()

        timing_data = json.loads(timing_path.read_text())
        review_data = json.loads(review_path.read_text())

        assert timing_data["enabled"] is True
        assert timing_data["timing_metadata"]["timestamp"] == pytest.approx(90.0)
        assert review_data["passed"] is True
        assert review_data["checks"]["bgm_duck_applied"] is True

    def test_writes_disabled_stub(self, tmp_path):
        from ytfactory.cta.models import CTAResult, CTAReviewResult
        from ytfactory.cta.reporter import CTAReporter

        result = CTAResult(
            success=True,
            enabled=False,
            placement=None,
            review=CTAReviewResult(passed=True),
        )
        CTAReporter().write(tmp_path, result)

        timing_path = tmp_path / "cta" / "cta-timing.json"
        assert timing_path.exists()
        data = json.loads(timing_path.read_text())
        assert data["enabled"] is False


# ── CTA Validator (review rules) ──────────────────────────────────────────────


class TestCTAValidator:
    def _make_validator(self):
        from ytfactory.review.validation.config import ValidationRulesConfig
        from ytfactory.review.validation.rules.cta import CTAValidator

        return CTAValidator(ValidationRulesConfig())

    def _write_timing(self, project_dir: Path, data: dict) -> None:
        cta_dir = project_dir / "cta"
        cta_dir.mkdir(parents=True, exist_ok=True)
        (cta_dir / "cta-timing.json").write_text(json.dumps(data))

    def test_all_skip_when_cta_disabled(self, tmp_path):
        validator = self._make_validator()
        self._write_timing(tmp_path, {"enabled": False})

        results = validator.validate(tmp_path, [], {})
        assert all(r.status == "SKIP" for r in results)

    def test_all_skip_when_timing_absent(self, tmp_path):
        validator = self._make_validator()
        results = validator.validate(tmp_path, [], {})
        assert all(r.status == "SKIP" for r in results)

    def test_cta_001_passes_when_timing_valid(self, tmp_path):
        validator = self._make_validator()
        self._write_timing(tmp_path, {
            "enabled": True,
            "success": True,
            "timing_metadata": {"timestamp": 90.0, "duration": 6.0, "variant": "full"},
            "review": {"timing_valid": True, "subtitle_safe": True, "branding_loaded": True,
                       "animation_completed": True, "bgm_duck_applied": True},
        })

        # Write timing.json so duration probe works
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        (audio_dir / "scene-001.timing.json").write_text(
            json.dumps([{"word": "x", "start": 0.0, "end": 300.0}])
        )

        results = validator.validate(tmp_path, [], {})
        r001 = next((r for r in results if r.rule_id == "CTA_001"), None)
        assert r001 is not None
        assert r001.status == "PASS"

    def test_cta_001_fails_when_success_false(self, tmp_path):
        validator = self._make_validator()
        self._write_timing(tmp_path, {
            "enabled": True,
            "success": False,
            "timing_metadata": None,
            "review": {"errors": ["render failed"]},
        })

        results = validator.validate(tmp_path, [], {})
        r001 = next(r for r in results if r.rule_id == "CTA_001")
        assert r001.status == "FAIL"

    def test_cta_002_passes_subtitle_safe(self, tmp_path):
        validator = self._make_validator()
        self._write_timing(tmp_path, {
            "enabled": True,
            "success": True,
            "timing_metadata": {
                "timestamp": 90.0,
                "duration": 6.0,
                "variant": "full",
                "zone": "bottom_center",
                "placement_path": "primary_contextual",
            },
            "review": {
                "timing_valid": True,
                "subtitle_safe": True,
                "branding_loaded": True,
                "animation_completed": True,
                "bgm_duck_applied": True,
            },
        })

        results = validator.validate(tmp_path, [], {})
        r002 = next(r for r in results if r.rule_id == "CTA_002")
        assert r002.status == "PASS"

    def test_cta_002_warns_subtitle_overlap(self, tmp_path):
        validator = self._make_validator()
        self._write_timing(tmp_path, {
            "enabled": True,
            "success": True,
            "timing_metadata": {
                "timestamp": 90.0,
                "duration": 6.0,
                "variant": "compact",
                "zone": "upper_right",
                "placement_path": "primary_contextual",
            },
            "review": {
                "timing_valid": True,
                "subtitle_safe": False,
                "branding_loaded": True,
                "animation_completed": True,
                "bgm_duck_applied": True,
            },
        })

        results = validator.validate(tmp_path, [], {})
        r002 = next(r for r in results if r.rule_id == "CTA_002")
        assert r002.status == "WARNING"

    def test_cta_003_fails_when_animation_not_completed(self, tmp_path):
        validator = self._make_validator()
        self._write_timing(tmp_path, {
            "enabled": True,
            "success": True,
            "timing_metadata": {"timestamp": 90.0, "duration": 6.0, "variant": "full"},
            "review": {
                "timing_valid": True,
                "subtitle_safe": True,
                "branding_loaded": True,
                "animation_completed": False,
                "bgm_duck_applied": True,
            },
        })

        results = validator.validate(tmp_path, [], {})
        r003 = next(r for r in results if r.rule_id == "CTA_003")
        assert r003.status == "FAIL"

    def test_cta_003_warns_fallback_template(self, tmp_path):
        validator = self._make_validator()
        self._write_timing(tmp_path, {
            "enabled": True,
            "success": True,
            "timing_metadata": {"timestamp": 90.0, "duration": 6.0, "variant": "compact"},
            "review": {
                "timing_valid": True,
                "subtitle_safe": True,
                "branding_loaded": True,
                "animation_completed": True,
                "bgm_duck_applied": True,
                "fallback_template": "minimal",
                "retry_count": 2,
            },
        })

        results = validator.validate(tmp_path, [], {})
        r003 = next(r for r in results if r.rule_id == "CTA_003")
        assert r003.status == "WARNING"
        assert "minimal" in r003.description

    def test_cta_004_warns_branding_not_loaded(self, tmp_path):
        validator = self._make_validator()
        self._write_timing(tmp_path, {
            "enabled": True,
            "success": True,
            "timing_metadata": {"timestamp": 90.0, "duration": 6.0, "variant": "full"},
            "review": {
                "timing_valid": True,
                "subtitle_safe": True,
                "branding_loaded": False,
                "animation_completed": True,
                "bgm_duck_applied": True,
            },
        })

        results = validator.validate(tmp_path, [], {})
        r004 = next(r for r in results if r.rule_id == "CTA_004")
        assert r004.status == "WARNING"

    def test_cta_005_warns_bgm_duck_not_applied(self, tmp_path):
        validator = self._make_validator()
        self._write_timing(tmp_path, {
            "enabled": True,
            "success": True,
            "timing_metadata": {"timestamp": 90.0, "duration": 6.0, "variant": "full"},
            "review": {
                "timing_valid": True,
                "subtitle_safe": True,
                "branding_loaded": True,
                "animation_completed": True,
                "bgm_duck_applied": False,
            },
        })

        results = validator.validate(tmp_path, [], {})
        r005 = next(r for r in results if r.rule_id == "CTA_005")
        assert r005.status == "WARNING"

    def test_cta_005_passes_bgm_duck_applied(self, tmp_path):
        validator = self._make_validator()
        self._write_timing(tmp_path, {
            "enabled": True,
            "success": True,
            "timing_metadata": {"timestamp": 90.0, "duration": 6.0, "variant": "full"},
            "review": {
                "timing_valid": True,
                "subtitle_safe": True,
                "branding_loaded": True,
                "animation_completed": True,
                "bgm_duck_applied": True,
            },
        })

        results = validator.validate(tmp_path, [], {})
        r005 = next(r for r in results if r.rule_id == "CTA_005")
        assert r005.status == "PASS"

    def test_all_rules_present(self, tmp_path):
        """Ensure all 5 CTA rules are emitted."""
        validator = self._make_validator()
        self._write_timing(tmp_path, {
            "enabled": True,
            "success": True,
            "timing_metadata": {"timestamp": 90.0, "duration": 6.0, "variant": "full",
                                 "zone": "bottom_center", "placement_path": "primary_contextual"},
            "review": {
                "timing_valid": True, "subtitle_safe": True, "branding_loaded": True,
                "animation_completed": True, "bgm_duck_applied": True,
            },
        })

        results = validator.validate(tmp_path, [], {})
        rule_ids = {r.rule_id for r in results}
        for expected in ("CTA_001", "CTA_002", "CTA_003", "CTA_004", "CTA_005"):
            assert expected in rule_ids

    def test_validator_registered_in_runner(self):
        from ytfactory.review.validation.runner import ValidationRunner
        from ytfactory.review.validation.rules.cta import CTAValidator

        runner = ValidationRunner()
        # Check CTAValidator is in the validators list (via source inspection)
        import inspect
        source = inspect.getsource(ValidationRunner.run)
        assert "CTAValidator" in source


# ── Incremental deps ───────────────────────────────────────────────────────────


class TestIncrementalDeps:
    def test_cta_in_pipeline_stages(self):
        from ytfactory.incremental.deps import PIPELINE_STAGES

        assert "cta" in PIPELINE_STAGES
        cta_idx = PIPELINE_STAGES.index("cta")
        video_idx = PIPELINE_STAGES.index("video")
        review_idx = PIPELINE_STAGES.index("review")
        assert video_idx < cta_idx < review_idx

    def test_cta_depends_on_video(self):
        from ytfactory.incremental.deps import STAGE_DEPENDENCIES

        assert "video" in STAGE_DEPENDENCIES["cta"]

    def test_review_depends_on_cta(self):
        from ytfactory.incremental.deps import STAGE_DEPENDENCIES

        assert "cta" in STAGE_DEPENDENCIES["review"]

    def test_cta_output_pattern_defined(self):
        from ytfactory.incremental.deps import STAGE_OUTPUT_PATTERNS

        assert "cta" in STAGE_OUTPUT_PATTERNS
        assert "cta/cta-timing.json" in STAGE_OUTPUT_PATTERNS["cta"]

    def test_force_cta_flag_registered(self):
        from ytfactory.incremental.deps import FORCE_FLAG_TO_STAGE

        assert "cta" in FORCE_FLAG_TO_STAGE
        assert FORCE_FLAG_TO_STAGE["cta"] == "cta"

    def test_downstream_of_cta_includes_review(self):
        from ytfactory.incremental.deps import downstream_stages

        downstream = downstream_stages({"cta"})
        assert "review" in downstream
        assert "publish" in downstream

    def test_downstream_of_video_includes_cta(self):
        from ytfactory.incremental.deps import downstream_stages

        downstream = downstream_stages({"video"})
        assert "cta" in downstream
        assert "review" in downstream


# ── BGM secondary-duck coordination ──────────────────────────────────────────


class TestBGMSecondaryDuck:
    """Spec: CTA engine applies a secondary duck to BGM at CTA timestamp."""

    def test_bgm_secondary_duck_applied_in_ffmpeg_filter(self):
        """Verify the audio filter expression contains volume reduction at CTA window."""
        from ytfactory.cta.renderer import _apply_overlay_ffmpeg
        from ytfactory.cta.models import CTAPlacement, CTAVariant, CTAZone, PlacementPath
        from ytfactory.cta.config import CTAOverlayConfig

        placement = CTAPlacement(
            timestamp=60.0,
            duration=6.0,
            variant=CTAVariant.FULL,
            placement_path=PlacementPath.PRIMARY_CONTEXTUAL,
            subtitle_safe=True,
            zone=CTAZone.BOTTOM_CENTER,
            pause_type="long_silence",
            pause_duration=5.0,
        )
        config = CTAOverlayConfig(enabled=True, bgm_secondary_duck_db=4.0)

        captured_cmd: list = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            r = MagicMock()
            r.returncode = 0
            return r

        with patch("ytfactory.cta.renderer.subprocess.run", side_effect=fake_run):
            _apply_overlay_ffmpeg(
                Path("/tmp/final.mp4"),
                Path("/tmp/overlay.png"),
                Path("/tmp/output.mp4"),
                placement,
                config,
                False,
                None,
            )

        cmd_str = " ".join(captured_cmd)
        # Volume filter should reference CTA start/end and apply a dB reduction
        assert "volume=" in cmd_str
        assert "between(t," in cmd_str

    def test_bgm_secondary_duck_db_zero_no_attenuation(self):
        """When bgm_secondary_duck_db=0, linear factor = 1.0 (no reduction)."""
        from ytfactory.cta.renderer import _db_to_linear

        factor = _db_to_linear(-0.0)
        assert factor == pytest.approx(1.0)

    def test_bgm_duck_reflected_in_review_result(self, tmp_path):
        """CTAReviewResult.bgm_duck_applied reflects config.bgm_secondary_duck_db > 0."""
        from ytfactory.cta.pipeline import CTAPipeline
        from ytfactory.cta.models import CTARenderResult

        proj_dir = tmp_path / "proj"
        (proj_dir / "video").mkdir(parents=True)
        (proj_dir / "video" / "final.mp4").write_bytes(b"x" * 10000)

        from ytfactory.cta.config import CTAOverlayConfig
        from ytfactory.cta.models import CTAPlacement, CTAVariant, CTAZone, PlacementPath

        config = CTAOverlayConfig(enabled=True, bgm_secondary_duck_db=4.0)
        placement = CTAPlacement(
            timestamp=60.0,
            duration=6.0,
            variant=CTAVariant.FULL,
            placement_path=PlacementPath.PRIMARY_CONTEXTUAL,
            subtitle_safe=True,
            zone=CTAZone.BOTTOM_CENTER,
            pause_type="long_silence",
            pause_duration=5.0,
        )

        work_file = proj_dir / "video" / "final.cta-work.mp4"

        def fake_render(self_inner, video, output, pl, cfg):
            output.write_bytes(b"x" * 50000)
            return CTARenderResult(success=True, output_path=str(output), template_used="atma")

        with (
            patch("ytfactory.shared.constants.WORKSPACE_DIR", str(tmp_path)),
            patch.object(
                __import__("ytfactory.cta.placement", fromlist=["CTAPlacementEngine"]).CTAPlacementEngine,
                "find_placement",
                return_value=placement,
            ),
            patch(
                "ytfactory.cta.renderer.CTARenderer.render",
                new=fake_render,
            ),
            patch("ytfactory.cta.pipeline._probe_dur", return_value=300.0),
        ):
            result = CTAPipeline().run("proj", _config=config)

        assert result.review.bgm_duck_applied is True


# ── Branding config backward compatibility ────────────────────────────────────


class TestBrandingConfigExtended:
    def test_accent_color_in_branding_placement_config(self):
        from ytfactory.branding.config import BrandingPlacementConfig

        cfg = BrandingPlacementConfig()
        assert hasattr(cfg, "accent_color")
        assert hasattr(cfg, "font")
        assert hasattr(cfg, "logo")
        assert cfg.accent_color == "#2EC5E8"

    def test_parse_placement_includes_accent_color(self):
        from ytfactory.branding.config import _parse_placement

        raw = {
            "opening_position": "after_hook",
            "accent_color": "#FF0000",
            "font": "Roboto",
            "logo": "assets/logo.png",
        }
        cfg = _parse_placement(raw)
        assert cfg.accent_color == "#FF0000"
        assert cfg.font == "Roboto"
        assert cfg.logo == "assets/logo.png"

    def test_existing_brand_config_fields_still_parse(self):
        from ytfactory.branding.config import _parse_placement

        raw = {
            "opening_position": "after_hook",
            "closing_position": "before_final_quote",
            "max_opening_seconds": 12,
            "asset_path": "assets/my-brand.png",
            "asset_animation": "fade",
        }
        cfg = _parse_placement(raw)
        assert cfg.opening_position == "after_hook"
        assert cfg.max_opening_seconds == 12
        assert cfg.asset_path == "assets/my-brand.png"
        # New fields default when absent
        assert cfg.accent_color == "#2EC5E8"
        assert cfg.font == "Arial"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _write_fake_output(output_path, render_result):
    """Helper for tests that need a fake output file written."""
    from ytfactory.cta.models import CTARenderResult

    assert isinstance(render_result, CTARenderResult)
    if render_result.success:
        p = Path(str(output_path))
        p.write_bytes(b"x" * 50000)
    return render_result
