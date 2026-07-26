"""Tests for overlay compositing: docs/overlay-compositing-spec.md.

Covers OverlayCompositor.select_category() (mood/motion_type -> category
mapping) and _apply_overlays() (the actual ffmpeg wiring onto the continuous
single-stream render — grain always last, mood overlays time-gated per scene).
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch


from ytfactory.video.overlay import OVERLAY_MAX_OPACITIES, OverlayCompositor
from ytfactory.video.pipeline import _apply_overlays

_MANIFEST = {
    "smoke": [{"file": "Smoke/Soft rolling smoke.mp4", "blend_mode": "screen", "opacity": 0.25}],
    "particles": [
        {"file": "Particles/Golden bokeh particles.mp4", "blend_mode": "screen", "opacity": 0.30},
        {"file": "Particles/Warm ember - rising particles.mp4", "blend_mode": "screen", "opacity": 0.25},
    ],
    "god_rays": [{"file": "God-rays/God-ray with visible dust in beam.mp4", "blend_mode": "screen", "opacity": 0.35}],
    "rain": [{"file": "Rain/Sparse falling light streaks.mp4", "blend_mode": "screen", "opacity": 0.20}],
    "grain": [{"file": "Grain/Film grain texture.mp4", "blend_mode": "grainmerge", "opacity": 0.07}],
}


def _compositor(manifest: dict | None = None, skip: bool = False) -> OverlayCompositor:
    c = OverlayCompositor(manifest_path=None, skip=skip)
    c.manifest = dict(manifest) if manifest is not None else dict(_MANIFEST)
    return c


# ── select_category ────────────────────────────────────────────────────────────


class TestSelectCategory:
    def test_motion_type_maps_directly(self):
        c = _compositor()
        category, motion_type = c.select_category({"motion_type": "particles"})
        assert category == "particles"
        assert motion_type == "particles"

    def test_motion_alias_fog_maps_to_smoke(self):
        c = _compositor()
        category, _ = c.select_category({"motion_type": "fog"})
        assert category == "smoke"

    def test_motion_alias_dust_maps_to_smoke(self):
        c = _compositor()
        category, _ = c.select_category({"motion_type": "dust"})
        assert category == "smoke"

    def test_rain_mood_only_applies_for_tagged_moods(self):
        c = _compositor()
        scene = {"motion_type": "rain", "visual_metadata": {"mood": "grief"}}
        category, _ = c.select_category(scene)
        assert category == "rain"

    def test_rain_not_applied_for_untagged_mood(self):
        c = _compositor()
        scene = {"motion_type": "zoom", "visual_metadata": {"mood": "peaceful"}}
        category, _ = c.select_category(scene)
        assert category is None

    def test_no_motion_type_returns_none(self):
        c = _compositor()
        category, _ = c.select_category({})
        assert category is None

    def test_unmatched_motion_type_returns_none(self):
        c = _compositor()
        category, _ = c.select_category({"motion_type": "zoom"})
        assert category is None

    def test_grain_never_selected_by_select_category(self):
        """Grain is global/always-applied, not scene-conditional — it must
        never come back from select_category (that would make it skippable
        per-scene, contradicting the spec)."""
        c = _compositor()
        for motion_type in ("particles", "smoke", "god_rays", "rain", "fog", "dust", "zoom", None):
            category, _ = c.select_category({"motion_type": motion_type} if motion_type else {})
            assert category != "grain"

    def test_skip_disables_manifest_loading(self):
        c = OverlayCompositor(manifest_path="assets/overlays/overlay_manifest.json", skip=True)
        assert c.manifest == {}


# ── select_category — visual_prompt keyword trigger (Task 2.11 Fix 1) ────────────
# Scoped to rain/particles/smoke/fog only; god_rays and everything else stay
# motion_type/mood-only. fog aliases to the "smoke" manifest category, same as
# motion_type="fog" already does (see test_motion_alias_fog_maps_to_smoke).


class TestVisualKeywordTrigger:
    def test_rain_triggered_by_visual_keyword(self):
        c = _compositor()
        scene = {
            "motion_type": "static",
            "visual_metadata": {"mood": "hopeful"},
            "visual_prompt": "a sunflower standing in a downpour",
        }
        category, _ = c.select_category(scene)
        assert category == "rain"

    def test_particles_triggered_by_visual_keyword(self):
        c = _compositor()
        scene = {
            "motion_type": "static",
            "visual_metadata": {"mood": "peaceful"},
            "visual_prompt": "dust motes floating in shaft of morning light",
        }
        category, _ = c.select_category(scene)
        assert category == "particles"

    def test_smoke_triggered_by_visual_keyword(self):
        c = _compositor()
        scene = {
            "motion_type": "static",
            "visual_metadata": {"mood": "reflective"},
            "visual_prompt": "incense smoke rising slowly in a quiet room",
        }
        category, _ = c.select_category(scene)
        assert category == "smoke"

    def test_fog_keyword_aliases_to_smoke_category(self):
        c = _compositor()
        scene = {
            "motion_type": "static",
            "visual_metadata": {"mood": "mysterious"},
            "visual_prompt": "a misty valley at dawn",
        }
        category, _ = c.select_category(scene)
        assert category == "smoke"

    def test_god_rays_not_triggered_by_visual_keyword(self):
        c = _compositor()
        # "shafts of light" matches no rain/particles/smoke/fog keyword, and
        # god_rays itself is never covered by the keyword check.
        result = c._category_from_visual_prompt("shafts of light filtering through columns")
        assert result is None

    def test_primary_motion_type_wins_over_keyword(self):
        c = _compositor()
        scene = {
            "motion_type": "particles",  # primary match
            "visual_metadata": {"mood": "hopeful"},
            "visual_prompt": "heavy rain falling",  # keyword would say rain
        }
        category, _ = c.select_category(scene)
        assert category == "particles"

    def test_no_keyword_match_returns_none(self):
        c = _compositor()
        scene = {
            "motion_type": "static",
            "visual_metadata": {"mood": "hopeful"},
            "visual_prompt": "a sunflower in golden hour light",
        }
        category, _ = c.select_category(scene)
        assert category is None

    def test_keyword_check_requires_category_present_in_manifest(self):
        c = _compositor(manifest={"rain": []})  # empty clip list
        scene = {"motion_type": "static", "visual_prompt": "heavy rain falling"}
        category, _ = c.select_category(scene)
        assert category is None


# ── _should_apply_grain (Task 2.9) ────────────────────────────────────────────
# Real schema: era/mood/visual_style live under scene["visual_metadata"], not
# as flat scene fields — the task doc's own pseudocode used flat fields.


class TestShouldApplyGrain:
    def test_grain_fires_for_historical_era(self):
        c = _compositor()
        scenes = [{"visual_metadata": {"era": "HISTORICAL", "mood": "determined", "visual_style": "DOCUMENTARY"}}]
        assert c._should_apply_grain(scenes) is True

    def test_grain_fires_for_reverent_mood(self):
        c = _compositor()
        scenes = [{"visual_metadata": {"era": "MODERN", "mood": "reverent", "visual_style": "REALISTIC"}}]
        assert c._should_apply_grain(scenes) is True

    def test_grain_fires_for_cinematic_style(self):
        c = _compositor()
        scenes = [{"visual_metadata": {"era": "MODERN", "mood": "hopeful", "visual_style": "CINEMATIC"}}]
        assert c._should_apply_grain(scenes) is True

    def test_grain_skipped_for_all_modern_realistic(self):
        c = _compositor()
        scenes = [
            {"visual_metadata": {"era": "MODERN", "mood": "hopeful", "visual_style": "REALISTIC"}},
            {"visual_metadata": {"era": "MODERN", "mood": "determined", "visual_style": "REALISTIC"}},
        ]
        assert c._should_apply_grain(scenes) is False

    def test_grain_skipped_for_brand_card_only(self):
        c = _compositor()
        scenes = [{"visual_metadata": {}, "scene_type": "brand_card"}]
        assert c._should_apply_grain(scenes) is False

    def test_grain_skipped_for_no_visual_metadata(self):
        c = _compositor()
        assert c._should_apply_grain([{"index": 1}]) is False

    def test_grain_fires_for_transitional_era(self):
        c = _compositor()
        scenes = [{"visual_metadata": {"era": "TRANSITIONAL", "mood": "hopeful", "visual_style": "REALISTIC"}}]
        assert c._should_apply_grain(scenes) is True

    def test_grain_handles_pydantic_style_visual_metadata(self):
        """visual_metadata may be a VisualMetadata object (with .value enums),
        not a plain dict, before it's serialized to scene-plan.json."""
        c = _compositor()

        class _Enum:
            def __init__(self, value):
                self.value = value

        class _VM:
            era = _Enum("HISTORICAL")
            mood = _Enum("determined")
            visual_style = _Enum("DOCUMENTARY")

        assert c._should_apply_grain([{"visual_metadata": _VM()}]) is True

    def test_grain_fires_at_40_percent(self):
        """Task 2.11 Fix 3 — 40% majority rule, not 'any scene matches'."""
        c = _compositor()
        historical = [
            {"scene_type": "content", "visual_metadata": {
                "era": "HISTORICAL", "mood": "reverent", "visual_style": "CINEMATIC"}}
        ] * 12
        modern = [
            {"scene_type": "content", "visual_metadata": {
                "era": "MODERN", "mood": "hopeful", "visual_style": "REALISTIC"}}
        ] * 17
        assert c._should_apply_grain(historical + modern) is True

    def test_grain_skipped_below_40_percent(self):
        c = _compositor()
        historical = [
            {"scene_type": "content", "visual_metadata": {
                "era": "HISTORICAL", "mood": "reverent", "visual_style": "CINEMATIC"}}
        ] * 5
        modern = [
            {"scene_type": "content", "visual_metadata": {
                "era": "MODERN", "mood": "hopeful", "visual_style": "REALISTIC"}}
        ] * 24
        assert c._should_apply_grain(historical + modern) is False

    def test_grain_threshold_excludes_brand_card_from_denominator(self):
        """A single matching content scene plus brand cards should still hit
        100% of *content* scenes, not be diluted by the brand cards."""
        c = _compositor()
        scenes = [
            {"scene_type": "brand_card", "visual_metadata": {}},
            {"scene_type": "content", "visual_metadata": {
                "era": "HISTORICAL", "mood": "hopeful", "visual_style": "REALISTIC"}},
            {"scene_type": "brand_card", "visual_metadata": {}},
        ]
        assert c._should_apply_grain(scenes) is True


# ── _apply_overlays ────────────────────────────────────────────────────────────


def _settings(**overrides) -> MagicMock:
    s = MagicMock()
    s.skip_overlays = False
    s.overlay_manifest_path = "assets/overlays/overlay_manifest.json"
    s.overlay_assets_dir = "assets/overlays"
    s.overlay_grain_enabled = True
    s.video_width = 1280
    s.video_height = 720
    s.video_fps = 30
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


class TestApplyOverlays:
    def test_skip_overlays_renames_without_ffmpeg(self, tmp_path):
        tmp = tmp_path / "in.mp4"
        tmp.write_bytes(b"x")
        out = tmp_path / "out.mp4"
        settings = _settings(skip_overlays=True)

        with patch("ytfactory.video.pipeline.subprocess.run") as mock_run:
            _apply_overlays(tmp, out, settings, [], [], 0.0)

        mock_run.assert_not_called()
        assert out.is_file()
        assert not tmp.exists()

    def test_no_matching_scenes_and_no_grain_renames_without_ffmpeg(self, tmp_path):
        tmp = tmp_path / "in.mp4"
        tmp.write_bytes(b"x")
        out = tmp_path / "out.mp4"
        settings = _settings()
        fake_manifest = {"particles": [{"file": "x.mp4", "blend_mode": "screen", "opacity": 0.3}]}

        with patch.object(OverlayCompositor, "_load_manifest", lambda self: setattr(self, "manifest", fake_manifest)), \
             patch("ytfactory.video.pipeline.subprocess.run") as mock_run:
            _apply_overlays(tmp, out, settings, [{"motion_type": "zoom"}], [5.0], 0.0)

        mock_run.assert_not_called()
        assert out.is_file()

    def test_mood_overlay_builds_time_gated_blend(self, tmp_path, monkeypatch):
        tmp = tmp_path / "in.mp4"
        tmp.write_bytes(b"x")
        out = tmp_path / "out.mp4"
        settings = _settings()

        overlays_root = tmp_path / "assets" / "overlays" / "Particles"
        overlays_root.mkdir(parents=True)
        clip_file = overlays_root / "Golden bokeh particles.mp4"
        clip_file.write_bytes(b"x")
        monkeypatch.chdir(tmp_path)

        fake_manifest = {
            "particles": [{"file": "Particles/Golden bokeh particles.mp4", "blend_mode": "screen", "opacity": 0.3}],
        }

        captured_cmd = {}

        def _fake_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            out.write_bytes(b"x")
            return MagicMock(returncode=0)

        with patch.object(OverlayCompositor, "_load_manifest", lambda self: setattr(self, "manifest", fake_manifest)), \
             patch("ytfactory.video.pipeline.subprocess.run", side_effect=_fake_run):
            scenes = [{"index": 1, "motion_type": "particles"}]
            durations = [8.0]
            _apply_overlays(tmp, out, settings, scenes, durations, intro_seconds=0.0)

        cmd = captured_cmd["cmd"]
        assert str(clip_file) in cmd
        filter_idx = cmd.index("-filter_complex") + 1
        filter_str = cmd[filter_idx]
        # Task 2.11 Fix 2 — opacity clamped to the particles max (0.10) even
        # though the manifest clip specifies 0.3.
        assert "colorchannelmixer=aa=0.100" in filter_str
        assert "blend=all_mode=screen:enable='between(t,0.0000,8.0000)'" in filter_str

    def test_grain_always_appended_last_with_overlay_blend(self, tmp_path, monkeypatch):
        tmp = tmp_path / "in.mp4"
        tmp.write_bytes(b"x")
        out = tmp_path / "out.mp4"
        settings = _settings()

        grain_dir = tmp_path / "assets" / "overlays" / "Grain"
        grain_dir.mkdir(parents=True)
        grain_file = grain_dir / "Film grain texture.mp4"
        grain_file.write_bytes(b"x")
        monkeypatch.chdir(tmp_path)

        fake_manifest = {"grain": [{"file": "Grain/Film grain texture.mp4", "blend_mode": "grainmerge", "opacity": 0.07}]}
        captured_cmd = {}

        def _fake_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            out.write_bytes(b"x")
            return MagicMock(returncode=0)

        with patch.object(OverlayCompositor, "_load_manifest", lambda self: setattr(self, "manifest", fake_manifest)), \
             patch("ytfactory.video.pipeline.subprocess.run", side_effect=_fake_run):
            # No mood match (motion_type=zoom) but era=HISTORICAL warrants grain.
            scenes = [{"index": 1, "motion_type": "zoom", "visual_metadata": {"era": "HISTORICAL"}}]
            _apply_overlays(tmp, out, settings, scenes, [5.0], intro_seconds=0.0)

        filter_str = captured_cmd["cmd"][captured_cmd["cmd"].index("-filter_complex") + 1]
        # Task 2.11 Fix 2 — overlay blend forced regardless of the manifest's
        # "grainmerge" value (grainmerge darkens mid-tones); opacity clamped
        # to the grain max (0.03) even though the manifest clip specifies 0.07.
        assert "blend=all_mode=overlay" in filter_str
        assert "grainmerge" not in filter_str
        assert "colorchannelmixer=aa=0.030" in filter_str
        # Grain has no time gate — applies for the whole video.
        assert "overlay:enable" not in filter_str

    def test_ffmpeg_failure_falls_back_to_rename(self, tmp_path, monkeypatch):
        tmp = tmp_path / "in.mp4"
        tmp.write_bytes(b"x")
        out = tmp_path / "out.mp4"
        settings = _settings()

        grain_dir = tmp_path / "assets" / "overlays" / "Grain"
        grain_dir.mkdir(parents=True)
        (grain_dir / "g.mp4").write_bytes(b"x")
        monkeypatch.chdir(tmp_path)

        fake_manifest = {"grain": [{"file": "Grain/g.mp4", "blend_mode": "grainmerge", "opacity": 0.07}]}

        def _fake_run(cmd, **kwargs):
            raise subprocess.CalledProcessError(1, cmd, stderr=b"ffmpeg exploded")

        with patch.object(OverlayCompositor, "_load_manifest", lambda self: setattr(self, "manifest", fake_manifest)), \
             patch("ytfactory.video.pipeline.subprocess.run", side_effect=_fake_run):
            _apply_overlays(tmp, out, settings, [{"index": 1, "motion_type": "zoom"}], [5.0], 0.0)

        assert out.is_file()
        assert not tmp.exists()

    def test_missing_clip_file_skips_stage_gracefully(self, tmp_path, monkeypatch):
        tmp = tmp_path / "in.mp4"
        tmp.write_bytes(b"x")
        out = tmp_path / "out.mp4"
        settings = _settings()
        monkeypatch.chdir(tmp_path)

        fake_manifest = {"particles": [{"file": "does/not/exist.mp4", "blend_mode": "screen", "opacity": 0.3}]}

        with patch.object(OverlayCompositor, "_load_manifest", lambda self: setattr(self, "manifest", fake_manifest)), \
             patch("ytfactory.video.pipeline.subprocess.run") as mock_run:
            _apply_overlays(tmp, out, settings, [{"index": 1, "motion_type": "particles"}], [5.0], 0.0)

        mock_run.assert_not_called()
        assert out.is_file()


class TestOverlayOpacityAndBrightness:
    """Task 2.11 Fix 2 — overlays must never darken or overpower the video."""

    def test_real_manifest_opacities_within_max(self):
        """The real overlay_manifest.json ships opacities under the max —
        catches manifest edits that drift back above the cap."""
        c = OverlayCompositor(manifest_path="assets/overlays/overlay_manifest.json")
        assert c.manifest, "expected the real manifest to load"
        for category, clips in c.manifest.items():
            max_opacity = OVERLAY_MAX_OPACITIES.get(category, 0.12)
            for clip in clips:
                assert clip["opacity"] <= max_opacity, (
                    f"{category} clip {clip['file']} opacity {clip['opacity']} "
                    f"exceeds max {max_opacity}"
                )

    def test_real_manifest_grain_uses_overlay_blend(self):
        c = OverlayCompositor(manifest_path="assets/overlays/overlay_manifest.json")
        assert c.manifest["grain"][0]["blend_mode"] == "overlay"

    def test_mood_overlay_blend_forced_to_screen_regardless_of_manifest(
        self, tmp_path, monkeypatch
    ):
        """Even if a manifest clip specifies a different blend mode, the
        rendered mood-overlay stage must use screen (never darkens)."""
        tmp = tmp_path / "in.mp4"
        tmp.write_bytes(b"x")
        out = tmp_path / "out.mp4"
        settings = _settings()

        overlays_root = tmp_path / "assets" / "overlays" / "Rain"
        overlays_root.mkdir(parents=True)
        clip_file = overlays_root / "rain.mp4"
        clip_file.write_bytes(b"x")
        monkeypatch.chdir(tmp_path)

        fake_manifest = {
            "rain": [{"file": "Rain/rain.mp4", "blend_mode": "normal", "opacity": 0.5}],
        }
        captured_cmd = {}

        def _fake_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            out.write_bytes(b"x")
            return MagicMock(returncode=0)

        with patch.object(OverlayCompositor, "_load_manifest", lambda self: setattr(self, "manifest", fake_manifest)), \
             patch("ytfactory.video.pipeline.subprocess.run", side_effect=_fake_run):
            scenes = [{"index": 1, "motion_type": "rain"}]
            _apply_overlays(tmp, out, settings, scenes, [5.0], intro_seconds=0.0)

        filter_str = captured_cmd["cmd"][captured_cmd["cmd"].index("-filter_complex") + 1]
        assert "blend=all_mode=screen" in filter_str
        assert "colorchannelmixer=aa=0.120" in filter_str  # clamped to rain max


class TestGrainConditional:
    """Task 2.9 — grain must not apply unconditionally."""

    def test_grain_disabled_by_setting(self, tmp_path, monkeypatch):
        tmp = tmp_path / "in.mp4"
        tmp.write_bytes(b"x")
        out = tmp_path / "out.mp4"
        monkeypatch.chdir(tmp_path)
        settings = _settings(overlay_grain_enabled=False)
        fake_manifest = {"grain": [{"file": "Grain/g.mp4", "blend_mode": "grainmerge", "opacity": 0.07}]}
        scenes = [{"visual_metadata": {"era": "HISTORICAL"}}]  # would otherwise fire

        with patch.object(OverlayCompositor, "_load_manifest", lambda self: setattr(self, "manifest", fake_manifest)), \
             patch("ytfactory.video.pipeline.subprocess.run") as mock_run:
            _apply_overlays(tmp, out, settings, scenes, [5.0], 0.0)

        mock_run.assert_not_called()
        assert out.is_file()

    def test_grain_skipped_for_realistic_modern_video(self, tmp_path, monkeypatch):
        tmp = tmp_path / "in.mp4"
        tmp.write_bytes(b"x")
        out = tmp_path / "out.mp4"
        monkeypatch.chdir(tmp_path)
        settings = _settings()
        fake_manifest = {"grain": [{"file": "Grain/g.mp4", "blend_mode": "grainmerge", "opacity": 0.07}]}
        scenes = [{"visual_metadata": {"era": "MODERN", "mood": "hopeful", "visual_style": "REALISTIC"}}]

        with patch.object(OverlayCompositor, "_load_manifest", lambda self: setattr(self, "manifest", fake_manifest)), \
             patch("ytfactory.video.pipeline.subprocess.run") as mock_run:
            _apply_overlays(tmp, out, settings, scenes, [5.0], 0.0)

        mock_run.assert_not_called()
        assert out.is_file()

    def test_grain_log_line_emitted_when_applied(self, tmp_path, monkeypatch):
        tmp = tmp_path / "in.mp4"
        tmp.write_bytes(b"x")
        out = tmp_path / "out.mp4"
        grain_dir = tmp_path / "assets" / "overlays" / "Grain"
        grain_dir.mkdir(parents=True)
        (grain_dir / "g.mp4").write_bytes(b"x")
        monkeypatch.chdir(tmp_path)
        settings = _settings()
        fake_manifest = {"grain": [{"file": "Grain/g.mp4", "blend_mode": "grainmerge", "opacity": 0.07}]}
        scenes = [{"visual_metadata": {"era": "HISTORICAL"}}]

        def _fake_run(cmd, **kwargs):
            out.write_bytes(b"x")
            return MagicMock(returncode=0)

        with patch.object(OverlayCompositor, "_load_manifest", lambda self: setattr(self, "manifest", fake_manifest)), \
             patch("ytfactory.video.pipeline.subprocess.run", side_effect=_fake_run), \
             patch("ytfactory.video.pipeline.logger") as mock_logger:
            _apply_overlays(tmp, out, settings, scenes, [5.0], 0.0)

        messages = [c.args[0] for c in mock_logger.info.call_args_list]
        assert any("applying grain" in m for m in messages)

    def test_grain_log_line_emitted_when_skipped(self, tmp_path, monkeypatch):
        tmp = tmp_path / "in.mp4"
        tmp.write_bytes(b"x")
        out = tmp_path / "out.mp4"
        monkeypatch.chdir(tmp_path)
        settings = _settings()
        fake_manifest = {"grain": [{"file": "Grain/g.mp4", "blend_mode": "grainmerge", "opacity": 0.07}]}
        scenes = [{"visual_metadata": {"era": "MODERN", "visual_style": "REALISTIC", "mood": "hopeful"}}]

        with patch.object(OverlayCompositor, "_load_manifest", lambda self: setattr(self, "manifest", fake_manifest)), \
             patch("ytfactory.video.pipeline.subprocess.run") as mock_run, \
             patch("ytfactory.video.pipeline.logger") as mock_logger:
            _apply_overlays(tmp, out, settings, scenes, [5.0], 0.0)

        mock_run.assert_not_called()
        messages = [c.args[0] for c in mock_logger.info.call_args_list]
        assert any("grain skipped" in m for m in messages)
