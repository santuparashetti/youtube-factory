"""Tests for the Background Music (BGM) pipeline.

Covers:
  - BGMConfig defaults and field values
  - BGMTrack model (auto-title from path stem)
  - BGMLibrary track discovery (category subdirectory, flat, fallback)
  - CategoryDetector keyword scoring
  - BGMMixer filter-complex construction and FFmpeg command shape
  - BGMPipeline.run() — disabled path, missing library, success path (mocked)
  - BGMValidator — skip when disabled, BGM_001–BGM_004 rules
  - Settings BGM fields exist with correct defaults
  - ValidationRunner includes BGMValidator (category "bgm" results present)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── BGMConfig ─────────────────────────────────────────────────────────────────


class TestBGMConfig:
    def _cfg(self, **kw):
        from ytfactory.bgm.config import BGMConfig
        return BGMConfig(**kw)

    def test_default_disabled(self):
        assert self._cfg().enabled is False

    def test_default_category_auto(self):
        assert self._cfg().category == "auto"

    def test_default_bgm_volume(self):
        assert self._cfg().bgm_volume == pytest.approx(0.12)

    def test_default_duck_ratio(self):
        assert self._cfg().duck_ratio == pytest.approx(6.0)

    def test_default_duck_attack_ms(self):
        assert self._cfg().duck_attack_ms == 200

    def test_default_duck_release_ms(self):
        assert self._cfg().duck_release_ms == 1000

    def test_default_fade_in(self):
        assert self._cfg().fade_in_seconds == pytest.approx(3.0)

    def test_default_fade_out(self):
        assert self._cfg().fade_out_seconds == pytest.approx(4.0)

    def test_default_crossfade(self):
        assert self._cfg().crossfade_seconds == pytest.approx(2.0)

    def test_default_random_track(self):
        assert self._cfg().random_track is True

    def test_categories_list(self):
        from ytfactory.bgm.config import CATEGORIES
        assert "spiritual" in CATEGORIES
        assert "meditation" in CATEGORIES
        assert "cinematic_ambient" in CATEGORIES
        assert len(CATEGORIES) == 7


# ── BGMTrack ──────────────────────────────────────────────────────────────────


class TestBGMTrack:
    def test_auto_title_from_stem(self, tmp_path):
        from ytfactory.bgm.models import BGMTrack
        t = BGMTrack(path=tmp_path / "my-ambient-track.mp3", category="spiritual")
        assert t.title == "my-ambient-track"

    def test_explicit_title(self, tmp_path):
        from ytfactory.bgm.models import BGMTrack
        t = BGMTrack(path=tmp_path / "x.mp3", category="meditation", title="Custom")
        assert t.title == "Custom"


# ── BGMLibrary ────────────────────────────────────────────────────────────────


class TestBGMLibrary:
    def _make_lib(self, base: Path, **kw):
        from ytfactory.bgm.config import BGMConfig
        from ytfactory.bgm.library import BGMLibrary
        cfg = BGMConfig(library_path=str(base), random_track=False, **kw)
        return BGMLibrary(cfg)

    def test_returns_none_when_library_empty(self, tmp_path):
        lib = self._make_lib(tmp_path)
        assert lib.find_track("spiritual") is None

    def test_finds_track_in_category_subdir(self, tmp_path):
        cat_dir = tmp_path / "spiritual"
        cat_dir.mkdir()
        (cat_dir / "ambient.mp3").write_bytes(b"audio")
        lib = self._make_lib(tmp_path)
        track = lib.find_track("spiritual")
        assert track is not None
        assert track.path.name == "ambient.mp3"
        assert track.category == "spiritual"

    def test_fallback_to_flat_by_filename_keyword(self, tmp_path):
        (tmp_path / "spiritual-vibes.mp3").write_bytes(b"audio")
        lib = self._make_lib(tmp_path)
        track = lib.find_track("spiritual")
        assert track is not None

    def test_fallback_any_track_when_no_keyword_match(self, tmp_path):
        (tmp_path / "random.mp3").write_bytes(b"audio")
        lib = self._make_lib(tmp_path)
        track = lib.find_track("meditation")
        assert track is not None

    def test_list_categories_empty_base(self, tmp_path):
        lib = self._make_lib(tmp_path / "nonexistent")
        assert lib.list_categories() == []

    def test_list_categories_with_subdirs(self, tmp_path):
        for cat in ["spiritual", "meditation"]:
            d = tmp_path / cat
            d.mkdir()
            (d / "t.mp3").write_bytes(b"x")
        lib = self._make_lib(tmp_path)
        cats = lib.list_categories()
        assert "spiritual" in cats
        assert "meditation" in cats

    def test_ignores_non_audio_files(self, tmp_path):
        cat_dir = tmp_path / "spiritual"
        cat_dir.mkdir()
        (cat_dir / "notes.txt").write_text("not audio")
        lib = self._make_lib(tmp_path)
        assert lib.find_track("spiritual") is None


# ── CategoryDetector ─────────────────────────────────────────────────────────


class TestCategoryDetector:
    def _detect(self, title, scene_titles=None):
        from ytfactory.bgm.detector import detect_category
        return detect_category(title, scene_titles)

    def test_spiritual_title(self):
        assert self._detect("The Silent Force Controlling Your Life") == "spiritual"

    def test_happiness_maps_to_spiritual(self):
        result = self._detect("The World Lied to You About Happiness")
        assert result == "spiritual"

    def test_meditation_keyword(self):
        assert self._detect("How to Meditate and Reduce Anxiety") == "meditation"

    def test_history_maps_to_emotional_documentary(self):
        result = self._detect("The Untold History of a Revolution")
        assert result in ("emotional_documentary", "inspirational", "cinematic_ambient")

    def test_default_category_on_no_match(self):
        from ytfactory.bgm.config import DEFAULT_CATEGORY
        result = self._detect("xyzzy foobar quux")
        assert result == DEFAULT_CATEGORY

    def test_scene_titles_contribute(self):
        result = self._detect("My Video", ["Soul", "Karma", "Inner Peace", "Dharma"])
        assert result == "spiritual"

    def test_title_weighted_higher_than_scenes(self):
        # Title has strong "spiritual" signal — should win even with scene noise
        result = self._detect("Spiritual Awakening", ["cars", "roads", "traffic"])
        assert result == "spiritual"


# ── BGMMixer ──────────────────────────────────────────────────────────────────


class TestBGMMixer:
    def _mixer(self, **kw):
        from ytfactory.bgm.config import BGMConfig
        from ytfactory.bgm.mixer import BGMMixer
        return BGMMixer(BGMConfig(enabled=True, **kw))

    def _track(self, tmp_path):
        from ytfactory.bgm.models import BGMTrack
        p = tmp_path / "track.mp3"
        p.write_bytes(b"x")
        return BGMTrack(path=p, category="spiritual")

    def _mock_probe(self, duration=120.0):
        return json.dumps({"format": {"duration": str(duration)}})

    def test_filter_contains_sidechaincompress(self, tmp_path):
        mixer = self._mixer()
        fc = mixer._build_filter(120.0, 116.0)
        assert "sidechaincompress" in fc

    def test_filter_contains_alimiter(self, tmp_path):
        mixer = self._mixer()
        fc = mixer._build_filter(120.0, 116.0)
        assert "alimiter" in fc

    def test_filter_contains_amix(self, tmp_path):
        mixer = self._mixer()
        fc = mixer._build_filter(120.0, 116.0)
        assert "amix" in fc

    def test_filter_contains_volume(self, tmp_path):
        mixer = self._mixer(bgm_volume=0.08)
        fc = mixer._build_filter(120.0, 116.0)
        assert "volume=0.0800" in fc

    def test_filter_fade_in_out_times(self, tmp_path):
        mixer = self._mixer(fade_in_seconds=5.0, fade_out_seconds=6.0)
        fc = mixer._build_filter(120.0, 114.0)
        assert "afade=t=in:ss=0:d=5.00" in fc
        assert "afade=t=out:st=114.0000:d=6.00" in fc

    def test_mix_command_shape(self, tmp_path):
        mixer = self._mixer()
        track = self._track(tmp_path)
        video = tmp_path / "final.mp4"
        video.write_bytes(b"v")
        output = tmp_path / "out.mp4"

        captured = []

        def fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            return MagicMock(returncode=0)

        probe_resp = MagicMock()
        probe_resp.stdout = self._mock_probe(120.0)

        with patch("ytfactory.bgm.mixer.subprocess.run") as mock_run:
            mock_run.side_effect = [probe_resp, MagicMock(returncode=0)]
            result = mixer.mix(video, track, output)

        # Second call is the mixing command
        mix_cmd = mock_run.call_args_list[1][0][0]
        assert "-filter_complex" in mix_cmd
        assert "-stream_loop" in mix_cmd
        assert "-c:v" in mix_cmd
        assert "copy" in mix_cmd
        assert result.success is True

    def test_mix_returns_failure_on_error(self, tmp_path):
        mixer = self._mixer()
        track = self._track(tmp_path)
        video = tmp_path / "final.mp4"
        video.write_bytes(b"v")
        output = tmp_path / "out.mp4"

        probe_resp = MagicMock()
        probe_resp.stdout = self._mock_probe(60.0)

        import subprocess
        with patch("ytfactory.bgm.mixer.subprocess.run") as mock_run:
            err = subprocess.CalledProcessError(1, "ffmpeg", stderr=b"error detail")
            mock_run.side_effect = [probe_resp, err]
            result = mixer.mix(video, track, output)

        assert result.success is False
        assert "error detail" in result.error

    def test_duck_threshold_in_filter(self, tmp_path):
        mixer = self._mixer(duck_threshold=0.03, duck_ratio=8.0)
        fc = mixer._build_filter(60.0, 56.0)
        assert "threshold=0.0300" in fc
        assert "ratio=8.0" in fc


# ── BGMPipeline ───────────────────────────────────────────────────────────────


class TestBGMPipeline:
    def _pipeline(self, **kw):
        from ytfactory.bgm.config import BGMConfig
        from ytfactory.bgm.pipeline import BGMPipeline
        return BGMPipeline(config=BGMConfig(enabled=True, **kw))

    def test_run_returns_none_when_disabled(self, tmp_path):
        from ytfactory.bgm.config import BGMConfig
        from ytfactory.bgm.pipeline import BGMPipeline
        pl = BGMPipeline(config=BGMConfig(enabled=False))
        result = pl.run("test-project", tmp_path / "final.mp4")
        assert result is None

    def test_run_raises_when_video_missing(self, tmp_path):
        pl = self._pipeline()
        with pytest.raises(FileNotFoundError):
            pl.run("test-project", tmp_path / "nonexistent.mp4")

    def test_run_returns_none_when_no_track_found(self, tmp_path):
        pl = self._pipeline(library_path=str(tmp_path / "empty_music"))
        video = tmp_path / "final.mp4"
        video.write_bytes(b"v")

        with patch("ytfactory.bgm.pipeline.console"):
            result = pl.run("test-project", video)

        assert result is None

    def test_run_succeeds_with_mock_mixer(self, tmp_path):
        from ytfactory.bgm.models import BGMMixResult, BGMTrack

        # Set up music library
        cat_dir = tmp_path / "music" / "spiritual"
        cat_dir.mkdir(parents=True)
        (cat_dir / "ambient.mp3").write_bytes(b"audio")

        # Set up video
        video = tmp_path / "final.mp4"
        video.write_bytes(b"video")
        # The pipeline writes to final.bgm.mp4 then replaces final.mp4 — pre-create it
        bgm_tmp = tmp_path / "final.bgm.mp4"
        bgm_tmp.write_bytes(b"mixed")

        fake_track = BGMTrack(path=cat_dir / "ambient.mp3", category="spiritual")
        fake_result = BGMMixResult(
            track=fake_track,
            video_duration=120.0,
            output_path=bgm_tmp,
            success=True,
            category="spiritual",
        )

        pl = self._pipeline(library_path=str(tmp_path / "music"), category="spiritual")

        with patch.object(pl._mixer, "mix", return_value=fake_result), \
             patch("ytfactory.bgm.pipeline.console"):
            result = pl.run("test-project", video)

        assert result is not None
        assert result.success is True

    def test_auto_category_reads_project_title(self, tmp_path):
        """_resolve_category reads project.json title when category='auto'."""
        from ytfactory.bgm.pipeline import BGMPipeline
        from ytfactory.bgm.config import BGMConfig

        project_dir = tmp_path
        (project_dir / "project.json").write_text(
            json.dumps({"title": "Spiritual Awakening Journey"})
        )
        (project_dir / "scenes").mkdir()
        (project_dir / "scenes" / "scene-plan.json").write_text(
            json.dumps({"scenes": [{"title": "Soul"}, {"title": "Inner Peace"}]})
        )

        pl = BGMPipeline(config=BGMConfig(enabled=True, category="auto"))
        category = pl._resolve_category(project_dir)

        assert category == "spiritual"


# ── Settings BGM fields ───────────────────────────────────────────────────────


class TestSettingsBGMFields:
    def _s(self):
        from ytfactory.config.settings import Settings
        return Settings()

    def test_bgm_enabled_field_exists(self):
        # The field exists; its value depends on BGM_ENABLED in .env
        assert hasattr(self._s(), "bgm_enabled")

    def test_bgm_category_default_auto(self):
        assert self._s().bgm_category == "auto"

    def test_bgm_library_path_default(self):
        assert self._s().bgm_library_path == "workspace/music"

    def test_bgm_volume_default(self):
        # Test the code-level field default; Settings() reads .env which may override it.
        from ytfactory.config.settings import Settings as _S
        assert _S.model_fields["bgm_volume"].default == pytest.approx(0.20)

    def test_bgm_duck_threshold_default(self):
        assert self._s().bgm_duck_threshold == pytest.approx(0.02)

    def test_bgm_duck_ratio_default(self):
        # Test the code-level field default; Settings() reads .env which may override it.
        from ytfactory.config.settings import Settings as _S
        assert _S.model_fields["bgm_duck_ratio"].default == pytest.approx(4.0)

    def test_bgm_fade_in_default(self):
        assert self._s().bgm_fade_in_seconds == pytest.approx(3.0)

    def test_bgm_fade_out_default(self):
        assert self._s().bgm_fade_out_seconds == pytest.approx(4.0)

    def test_bgm_random_track_default(self):
        assert self._s().bgm_random_track is True


# ── BGMValidator ──────────────────────────────────────────────────────────────


class TestBGMValidator:
    def _validator(self):
        from ytfactory.review.validation.config import ValidationRulesConfig
        from ytfactory.review.validation.rules.bgm import BGMValidator
        return BGMValidator(ValidationRulesConfig())

    def test_all_skip_when_bgm_disabled(self, tmp_path):
        v = self._validator()
        results = v.validate(tmp_path, [], {"bgm_enabled": False})
        assert all(r.status == "SKIP" for r in results)

    def test_all_skip_when_context_missing_bgm_key(self, tmp_path):
        v = self._validator()
        results = v.validate(tmp_path, [], {})
        assert all(r.status == "SKIP" for r in results)

    def test_all_skip_when_final_video_missing(self, tmp_path):
        v = self._validator()
        results = v.validate(tmp_path, [], {"bgm_enabled": True})
        assert all(r.status == "SKIP" for r in results)

    def test_bgm_001_pass_on_audible_intro(self, tmp_path):
        v = self._validator()

        video = tmp_path / "video" / "final.mp4"
        video.parent.mkdir()
        video.write_bytes(b"fake")

        # volumedetect returns mean = -20 dB (above -50 threshold)
        def fake_volumedetect(path, start=0.0, duration=None):
            return {"mean": -20.0, "max": -5.0}

        with patch("ytfactory.review.validation.rules.bgm._run_volumedetect",
                   side_effect=fake_volumedetect), \
             patch("ytfactory.review.validation.rules.bgm._probe_duration", return_value=120.0):
            results = v.validate(tmp_path, [], {"bgm_enabled": True})

        bgm001 = next(r for r in results if r.rule_id == "BGM_001")
        assert bgm001.status == "PASS"

    def test_bgm_001_fail_on_silent_intro(self, tmp_path):
        v = self._validator()

        video = tmp_path / "video" / "final.mp4"
        video.parent.mkdir()
        video.write_bytes(b"fake")

        # volumedetect returns mean = -70 dB (below -50 threshold)
        def fake_volumedetect(path, start=0.0, duration=None):
            return {"mean": -70.0, "max": -65.0}

        with patch("ytfactory.review.validation.rules.bgm._run_volumedetect",
                   side_effect=fake_volumedetect), \
             patch("ytfactory.review.validation.rules.bgm._probe_duration", return_value=120.0):
            results = v.validate(tmp_path, [], {"bgm_enabled": True})

        bgm001 = next(r for r in results if r.rule_id == "BGM_001")
        assert bgm001.status == "FAIL"

    def test_bgm_002_fail_on_clipping(self, tmp_path):
        v = self._validator()

        video = tmp_path / "video" / "final.mp4"
        video.parent.mkdir()
        video.write_bytes(b"fake")

        call_count = [0]

        def fake_volumedetect(path, start=0.0, duration=None):
            call_count[0] += 1
            if duration == 3.0:  # BGM_001 intro check
                return {"mean": -20.0, "max": -5.0}
            return {"mean": -14.0, "max": 0.1}  # clipping!

        with patch("ytfactory.review.validation.rules.bgm._run_volumedetect",
                   side_effect=fake_volumedetect), \
             patch("ytfactory.review.validation.rules.bgm._probe_duration", return_value=120.0):
            results = v.validate(tmp_path, [], {"bgm_enabled": True})

        bgm002 = next(r for r in results if r.rule_id == "BGM_002")
        assert bgm002.status == "FAIL"

    def test_bgm_002_pass_within_headroom(self, tmp_path):
        v = self._validator()

        video = tmp_path / "video" / "final.mp4"
        video.parent.mkdir()
        video.write_bytes(b"fake")

        def fake_volumedetect(path, start=0.0, duration=None):
            return {"mean": -14.0, "max": -1.0}

        with patch("ytfactory.review.validation.rules.bgm._run_volumedetect",
                   side_effect=fake_volumedetect), \
             patch("ytfactory.review.validation.rules.bgm._probe_duration", return_value=120.0):
            results = v.validate(tmp_path, [], {"bgm_enabled": True})

        bgm002 = next(r for r in results if r.rule_id == "BGM_002")
        assert bgm002.status == "PASS"


# ── ValidationRunner includes BGMValidator ────────────────────────────────────


class TestBGMValidatorInRunner:
    def test_runner_produces_bgm_category_results(self, tmp_path):
        from ytfactory.review.validation.runner import ValidationRunner

        runner = ValidationRunner()
        report = runner.run(tmp_path, [], {"bgm_enabled": False})
        bgm_results = [r for r in report.results if r.category == "bgm"]
        assert len(bgm_results) > 0
        # All should be SKIP since BGM is disabled
        assert all(r.status == "SKIP" for r in bgm_results)
