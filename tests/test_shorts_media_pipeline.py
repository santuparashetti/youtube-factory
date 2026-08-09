"""Tests for ShortsMediaPipeline (Phase 1B)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.config.settings import Settings
from ytfactory.shorts.media_pipeline import (
    ShortsMediaPipeline,
    ShortsMediaResult,
    _check_images_ready,
    _make_shorts_settings,
)
from ytfactory.shorts.models import (
    OpportunityExtractionResult,
    ShortsScene,
    ShortsScenePlan,
    ShortOpportunity,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_scene(index: int, narration: str = "Test narration.") -> ShortsScene:
    return ShortsScene(
        index=index,
        section="hook",
        narration=narration,
        visual_prompt="A bright sunrise.",
        duration_seconds=5.0,
        shot_type="wide",
    )


def _make_scene_plan(num_scenes: int = 2, short_id: str = "short-001") -> ShortsScenePlan:
    return ShortsScenePlan(
        short_id=short_id,
        parent_video_id="proj-test",
        target_duration_seconds=30.0,
        total_estimated_duration=30.0,
        scene_count=num_scenes,
        scenes=[_make_scene(i) for i in range(1, num_scenes + 1)],
        visual_hook_description="A dramatic opening.",
    )


def _make_opportunity() -> ShortOpportunity:
    return ShortOpportunity(
        opportunity_id="opp-1",
        angle="paradox",
        surprising_idea="Test idea",
        emotional_tension="High",
        curiosity_potential="Strong",
        connection_to_long_video="Direct",
        unresolved_question="Why?",
        estimated_hook_strength=0.9,
    )


def _make_extraction(num_selected: int = 2) -> OpportunityExtractionResult:
    opp = _make_opportunity()
    return OpportunityExtractionResult(
        parent_video_id="proj-test",
        parent_video_title="Test Video",
        parent_core_thesis="Test thesis",
        opportunities=[opp] * num_selected,
        selected=[f"opp-{i}" for i in range(1, num_selected + 1)],
        extraction_rationale="Great potential.",
    )


def _base_settings() -> Settings:
    return Settings(
        shorts_video_width=1080,
        shorts_video_height=1920,
        shorts_video_fps=30,
        shorts_subtitle_play_res_x=1080,
        shorts_subtitle_play_res_y=1920,
        shorts_bgm_enabled=False,
        bgm_enabled=False,
    )


# ── Test: images not ready ────────────────────────────────────────────────────


def test_media_pipeline_skips_if_images_not_ready(tmp_path):
    plan = _make_scene_plan()

    with (
        patch("ytfactory.shorts.media_pipeline.WORKSPACE_DIR", str(tmp_path)),
        patch.object(
            ShortsMediaPipeline, "_repo",
            create=True,
        ),
    ):
        pipeline = ShortsMediaPipeline(_base_settings())
        pipeline._repo = MagicMock()
        pipeline._repo.load_scene_plan.return_value = plan
        pipeline._repo.load_opportunities.return_value = _make_extraction()
        pipeline._projects = MagicMock()

        # images dir intentionally not populated
        (tmp_path / "proj-test" / "shorts" / "short-001").mkdir(parents=True)

        result = pipeline.run("proj-test", "short-001", force=False)

    assert result.images_ready is False
    assert result.tts_completed is False
    assert result.render_completed is False


def test_media_pipeline_reports_missing_images_clearly(tmp_path):
    plan = _make_scene_plan(num_scenes=3)

    with patch("ytfactory.shorts.media_pipeline.WORKSPACE_DIR", str(tmp_path)):
        pipeline = ShortsMediaPipeline(_base_settings())
        pipeline._repo = MagicMock()
        pipeline._repo.load_scene_plan.return_value = plan
        pipeline._projects = MagicMock()

        short_dir = tmp_path / "proj-test" / "shorts" / "short-001"
        short_dir.mkdir(parents=True)

        # Only supply scene-001.png; scenes 2 and 3 are missing
        images_dir = short_dir / "images"
        images_dir.mkdir()
        (images_dir / "scene-001.png").touch()

        result = pipeline.run("proj-test", "short-001", force=False)

    assert result.images_ready is False
    assert "scene-002.png" in result.missing_images
    assert "scene-003.png" in result.missing_images


# ── Test: TTS ─────────────────────────────────────────────────────────────────


def test_media_pipeline_runs_tts_per_scene(tmp_path):
    plan = _make_scene_plan(num_scenes=2)
    short_dir = tmp_path / "proj-test" / "shorts" / "short-001"
    _seed_images(short_dir, plan)

    mock_provider = MagicMock()
    mock_provider.generate_with_boundaries.return_value = (MagicMock(), [])

    with (
        patch("ytfactory.shorts.media_pipeline.WORKSPACE_DIR", str(tmp_path)),
        patch("ytfactory.shorts.media_pipeline.get_tts_provider", return_value=mock_provider),
        patch("ytfactory.shorts.media_pipeline._pacer") as mock_pacer,
        patch("ytfactory.shorts.media_pipeline._run_subtitles_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._run_render_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._shorts_assemble_continuous", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._run_bgm_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._probe_video_duration", return_value=30.0),
    ):
        mock_pacer.generate.return_value = (MagicMock(), [])
        pipeline = ShortsMediaPipeline(_base_settings())
        pipeline._repo = MagicMock()
        pipeline._repo.load_scene_plan.return_value = plan
        pipeline._projects = MagicMock()

        result = pipeline.run("proj-test", "short-001", force=True)

    assert result.images_ready is True
    assert result.tts_completed is True


def test_media_pipeline_writes_audio_to_short_dir(tmp_path):
    plan = _make_scene_plan(num_scenes=1)
    short_dir = tmp_path / "proj-test" / "shorts" / "short-001"
    _seed_images(short_dir, plan)

    mock_provider = MagicMock()

    def fake_pacer_generate(narration, output_path, **kwargs):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"audio")
        return (MagicMock(), [{"word": "test", "start": 0.0, "end": 1.0}])

    with (
        patch("ytfactory.shorts.media_pipeline.WORKSPACE_DIR", str(tmp_path)),
        patch("ytfactory.shorts.media_pipeline.get_tts_provider", return_value=mock_provider),
        patch("ytfactory.shorts.media_pipeline._pacer") as mock_pacer,
        patch("ytfactory.shorts.media_pipeline._run_subtitles_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._run_render_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._shorts_assemble_continuous", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._run_bgm_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._probe_video_duration", return_value=5.0),
    ):
        mock_pacer.generate.side_effect = fake_pacer_generate
        pipeline = ShortsMediaPipeline(_base_settings())
        pipeline._repo = MagicMock()
        pipeline._repo.load_scene_plan.return_value = plan
        pipeline._projects = MagicMock()

        pipeline.run("proj-test", "short-001", force=True)

    assert (short_dir / "audio" / "scene-001.mp3").is_file()


# ── Test: subtitles ───────────────────────────────────────────────────────────


def test_media_pipeline_writes_subtitles_to_short_dir(tmp_path):
    plan = _make_scene_plan(num_scenes=1)
    short_dir = tmp_path / "proj-test" / "shorts" / "short-001"
    _seed_images(short_dir, plan)

    # Pre-create audio so subtitle stage finds it
    audio_dir = short_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "scene-001.mp3").write_bytes(b"audio")
    (audio_dir / "scene-001.timing.json").write_text(
        json.dumps([{"word": "test", "start": 0.0, "end": 1.0}]), encoding="utf-8"
    )

    mock_engine = MagicMock()
    mock_cue = MagicMock()
    mock_engine.build_cues.return_value = ([mock_cue], MagicMock())
    mock_engine.ass_writer.write.return_value = "[Script Info]\n"
    mock_engine.srt_writer.write.return_value = "1\n00:00:00,000 --> 00:00:01,000\nTest\n"

    with (
        patch("ytfactory.shorts.media_pipeline.WORKSPACE_DIR", str(tmp_path)),
        patch("ytfactory.shorts.media_pipeline._run_tts_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline.SubtitleEngine") as mock_sub_cls,
        patch("ytfactory.shorts.media_pipeline._run_render_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._shorts_assemble_continuous", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._run_bgm_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._probe_video_duration", return_value=5.0),
    ):
        mock_sub_cls.from_settings.return_value = mock_engine
        pipeline = ShortsMediaPipeline(_base_settings())
        pipeline._repo = MagicMock()
        pipeline._repo.load_scene_plan.return_value = plan
        pipeline._projects = MagicMock()

        result = pipeline.run("proj-test", "short-001", force=True)

    assert result.subtitles_completed is True


# ── Test: resolution ──────────────────────────────────────────────────────────


def test_media_pipeline_uses_1080x1920_settings(tmp_path):
    """_make_shorts_settings must produce 1080×1920 from base settings."""
    base = _base_settings()
    shorts = _make_shorts_settings(base)
    assert shorts.video_width == 1080
    assert shorts.video_height == 1920


def test_media_pipeline_uses_9_16_dar_not_16_9(tmp_path):
    """The continuous assembly FFmpeg command must contain setdar=9/16."""
    plan = _make_scene_plan(num_scenes=1)
    short_dir = tmp_path / "proj-test" / "shorts" / "short-001"
    video_dir = short_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "scene-001.mp4").write_bytes(b"video")

    captured_cmds: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list):
            captured_cmds.append(list(cmd))
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = b""
        return result

    base = _base_settings()
    shorts_settings = _make_shorts_settings(base)

    with patch("ytfactory.shorts.media_pipeline.subprocess.run", side_effect=fake_run):
        from ytfactory.shorts.media_pipeline import _shorts_assemble_continuous
        _shorts_assemble_continuous(short_dir, plan, shorts_settings, force=True)

    full_cmd = " ".join(arg for cmd in captured_cmds for arg in cmd)
    assert "setdar=9/16" in full_cmd
    assert "setdar=16/9" not in full_cmd


def test_media_pipeline_uses_correct_play_res_for_subtitles(tmp_path):
    """Patched settings must have play_res_x/y = 1080/1920."""
    base = _base_settings()
    shorts = _make_shorts_settings(base)
    assert shorts.subtitle_ass_play_res_x == 1080
    assert shorts.subtitle_ass_play_res_y == 1920


# ── Test: BGM ─────────────────────────────────────────────────────────────────


def test_media_pipeline_calls_bgm_mixer_with_final_work_mp4(tmp_path):
    """BGMMixer.mix must be called with the final.work.mp4 path."""
    short_dir = tmp_path / "proj-test" / "shorts" / "short-001"
    video_dir = short_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    work_mp4 = video_dir / "final.work.mp4"
    work_mp4.write_bytes(b"video")

    settings = Settings(
        shorts_video_width=1080,
        shorts_video_height=1920,
        shorts_video_fps=30,
        shorts_subtitle_play_res_x=1080,
        shorts_subtitle_play_res_y=1920,
        shorts_bgm_enabled=True,
        bgm_enabled=True,
        bgm_category="spiritual",
    )
    shorts_settings = _make_shorts_settings(settings)

    mock_track = MagicMock()
    mock_mix_result = MagicMock()
    mock_mix_result.success = True

    with (
        patch("ytfactory.shorts.media_pipeline.BGMLibrary") as mock_lib_cls,
        patch("ytfactory.shorts.media_pipeline.BGMMixer") as mock_mixer_cls,
    ):
        mock_lib = MagicMock()
        mock_lib.find_track.return_value = mock_track
        mock_lib_cls.return_value = mock_lib

        mock_mixer = MagicMock()
        mock_mixer.mix.return_value = mock_mix_result
        mock_mixer_cls.return_value = mock_mixer

        from ytfactory.shorts.media_pipeline import _run_bgm_for_short
        ok, errors = _run_bgm_for_short(short_dir, shorts_settings, force=True)

    assert ok is True
    assert errors == []
    call_kwargs = mock_mixer.mix.call_args
    assert call_kwargs is not None
    actual_path = call_kwargs.kwargs.get("video_path") or call_kwargs.args[0]
    assert Path(actual_path) == work_mp4


# ── Test: idempotency ─────────────────────────────────────────────────────────


def test_media_pipeline_idempotent_skips_existing_audio(tmp_path):
    """If audio files already exist and force=False, TTS provider is not called."""
    plan = _make_scene_plan(num_scenes=1)
    short_dir = tmp_path / "proj-test" / "shorts" / "short-001"
    audio_dir = short_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "scene-001.mp3").write_bytes(b"existing audio")
    (audio_dir / "scene-001.timing.json").write_text("[]", encoding="utf-8")

    mock_provider = MagicMock()

    settings = Settings(
        shorts_video_width=1080,
        shorts_video_height=1920,
        shorts_video_fps=30,
        shorts_subtitle_play_res_x=1080,
        shorts_subtitle_play_res_y=1920,
        shorts_bgm_enabled=False,
        bgm_enabled=False,
        tts_skip_existing=True,
        tts_pacing_enabled=False,
    )

    with (
        patch("ytfactory.shorts.media_pipeline.WORKSPACE_DIR", str(tmp_path)),
        patch("ytfactory.shorts.media_pipeline.get_tts_provider", return_value=mock_provider),
    ):
        from ytfactory.shorts.media_pipeline import _run_tts_for_short
        ok, errors = _run_tts_for_short(short_dir, plan, settings, force=False)

    assert ok is True
    assert errors == []
    mock_provider.generate_with_boundaries.assert_not_called()


def test_media_pipeline_idempotent_skips_existing_video(tmp_path):
    """If per-scene MP4 exists and force=False, renderer is not called."""
    plan = _make_scene_plan(num_scenes=1)
    short_dir = tmp_path / "proj-test" / "shorts" / "short-001"
    video_dir = short_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "scene-001.mp4").write_bytes(b"existing video")

    mock_renderer = MagicMock()
    settings = _base_settings()
    shorts_settings = _make_shorts_settings(settings)

    with patch("ytfactory.shorts.media_pipeline.ShortsFFmpegRenderer", return_value=mock_renderer):
        from ytfactory.shorts.media_pipeline import _run_render_for_short
        ok, errors = _run_render_for_short(short_dir, plan, shorts_settings, force=False)

    assert ok is True
    assert errors == []
    mock_renderer.render.assert_not_called()


def test_media_pipeline_force_regenerates_all_stages(tmp_path):
    """With force=True, TTS provider is called even if files already exist."""
    plan = _make_scene_plan(num_scenes=1)
    short_dir = tmp_path / "proj-test" / "shorts" / "short-001"
    audio_dir = short_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "scene-001.mp3").write_bytes(b"existing audio")
    (audio_dir / "scene-001.timing.json").write_text("[]", encoding="utf-8")

    mock_provider = MagicMock()
    mock_provider.generate_with_boundaries.return_value = (MagicMock(), [])

    settings = Settings(
        shorts_video_width=1080,
        shorts_video_height=1920,
        shorts_video_fps=30,
        shorts_subtitle_play_res_x=1080,
        shorts_subtitle_play_res_y=1920,
        shorts_bgm_enabled=False,
        bgm_enabled=False,
        tts_skip_existing=True,
        tts_pacing_enabled=False,
    )

    with (
        patch("ytfactory.shorts.media_pipeline.WORKSPACE_DIR", str(tmp_path)),
        patch("ytfactory.shorts.media_pipeline.get_tts_provider", return_value=mock_provider),
    ):
        from ytfactory.shorts.media_pipeline import _run_tts_for_short
        ok, errors = _run_tts_for_short(short_dir, plan, settings, force=True)

    assert ok is True
    mock_provider.generate_with_boundaries.assert_called_once()


# ── Test: multi-short isolation ───────────────────────────────────────────────


def test_media_pipeline_continues_short_002_if_short_001_not_ready(tmp_path):
    """If short-001 has no images, short-002 still runs."""
    plan_001 = _make_scene_plan(num_scenes=1, short_id="short-001")
    plan_002 = _make_scene_plan(num_scenes=1, short_id="short-002")

    extraction = _make_extraction(num_selected=2)

    short_002_dir = tmp_path / "proj-test" / "shorts" / "short-002"
    _seed_images(short_002_dir, plan_002)

    def load_plan(project_id, short_id):
        if short_id == "short-001":
            return plan_001
        return plan_002

    with (
        patch("ytfactory.shorts.media_pipeline.WORKSPACE_DIR", str(tmp_path)),
        patch("ytfactory.shorts.media_pipeline._run_tts_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._run_subtitles_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._run_render_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._shorts_assemble_continuous", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._run_bgm_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._probe_video_duration", return_value=30.0),
    ):
        pipeline = ShortsMediaPipeline(_base_settings())
        pipeline._repo = MagicMock()
        pipeline._repo.load_opportunities.return_value = extraction
        pipeline._repo.load_scene_plan.side_effect = load_plan
        pipeline._projects = MagicMock()

        results = pipeline.run_all("proj-test", force=False)

    assert len(results) == 2
    result_001 = next(r for r in results if r.short_id == "short-001")
    result_002 = next(r for r in results if r.short_id == "short-002")
    assert result_001.images_ready is False
    assert result_002.images_ready is True


def test_media_pipeline_short_id_filter_runs_only_specified_short(tmp_path):
    """short_id_filter='short-002' should skip short-001."""
    extraction = _make_extraction(num_selected=2)
    plan_002 = _make_scene_plan(num_scenes=1, short_id="short-002")
    short_002_dir = tmp_path / "proj-test" / "shorts" / "short-002"
    _seed_images(short_002_dir, plan_002)

    with (
        patch("ytfactory.shorts.media_pipeline.WORKSPACE_DIR", str(tmp_path)),
        patch("ytfactory.shorts.media_pipeline._run_tts_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._run_subtitles_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._run_render_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._shorts_assemble_continuous", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._run_bgm_for_short", return_value=(True, [])),
        patch("ytfactory.shorts.media_pipeline._probe_video_duration", return_value=30.0),
    ):
        pipeline = ShortsMediaPipeline(_base_settings())
        pipeline._repo = MagicMock()
        pipeline._repo.load_opportunities.return_value = extraction
        pipeline._repo.load_scene_plan.return_value = plan_002
        pipeline._projects = MagicMock()

        results = pipeline.run_all("proj-test", short_id_filter="short-002", force=False)

    assert len(results) == 1
    assert results[0].short_id == "short-002"


# ── Test: ShortsFFmpegRenderer ────────────────────────────────────────────────


def test_shorts_ffmpeg_renderer_uses_correct_resolution(tmp_path):
    """render() must pass scale=1080:1920 in the -vf argument."""
    from ytfactory.shorts.ffmpeg import ShortsFFmpegRenderer

    settings = _make_shorts_settings(_base_settings())
    renderer = ShortsFFmpegRenderer(settings)

    assert renderer.settings.video_width == 1080
    assert renderer.settings.video_height == 1920

    image = tmp_path / "scene-001.png"
    audio = tmp_path / "scene-001.mp3"
    subtitle = tmp_path / "scene-001.ass"
    output = tmp_path / "scene-001.mp4"
    for p in (image, audio):
        p.write_bytes(b"data")
    subtitle.write_text("[Script Info]", encoding="utf-8")

    captured_vf: list[str] = []

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list):
            # Extract the argument that follows -vf
            for i, token in enumerate(cmd):
                if token == "-vf" and i + 1 < len(cmd):
                    captured_vf.append(cmd[i + 1])
        r = MagicMock()
        r.returncode = 0
        r.stdout = b""
        r.stderr = b""
        return r

    with patch("ytfactory.shorts.ffmpeg.subprocess.run", side_effect=fake_run):
        renderer.render(
            image=image,
            audio=audio,
            subtitle=subtitle,
            output=output,
            duration_hint=5.0,
        )

    assert captured_vf, "renderer did not call subprocess.run with a -vf argument"
    vf = captured_vf[0]
    # scale=1080:1920 must appear somewhere in the filter chain
    assert "1080" in vf and "1920" in vf, f"Expected 1080x1920 scale in vf, got: {vf}"


def test_shorts_ffmpeg_renderer_sets_dar_9_16(tmp_path):
    """render() must include setdar=9/16 (not setdar=16/9) in the -vf chain."""
    from ytfactory.shorts.ffmpeg import ShortsFFmpegRenderer

    settings = _make_shorts_settings(_base_settings())
    renderer = ShortsFFmpegRenderer(settings)

    image = tmp_path / "scene-001.png"
    audio = tmp_path / "scene-001.mp3"
    subtitle = tmp_path / "scene-001.ass"
    output = tmp_path / "scene-001.mp4"
    for p in (image, audio):
        p.write_bytes(b"data")
    subtitle.write_text("[Script Info]", encoding="utf-8")

    captured_vf: list[str] = []

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, list):
            for i, token in enumerate(cmd):
                if token == "-vf" and i + 1 < len(cmd):
                    captured_vf.append(cmd[i + 1])
        r = MagicMock()
        r.returncode = 0
        r.stdout = b""
        r.stderr = b""
        return r

    with patch("ytfactory.shorts.ffmpeg.subprocess.run", side_effect=fake_run):
        renderer.render(
            image=image,
            audio=audio,
            subtitle=subtitle,
            output=output,
            duration_hint=5.0,
        )

    assert captured_vf, "renderer did not call subprocess.run with a -vf argument"
    vf = captured_vf[0]
    assert "setdar=9/16" in vf, f"Expected setdar=9/16 in vf, got: {vf}"
    assert "setdar=16/9" not in vf, f"Found setdar=16/9 in vf: {vf}"


# ── Private helper ────────────────────────────────────────────────────────────


def _seed_images(short_dir: Path, plan: ShortsScenePlan) -> None:
    """Create dummy PNG files for all scenes in *plan* under *short_dir*/images/."""
    images_dir = short_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for scene in plan.scenes:
        (images_dir / f"scene-{scene.index:03d}.png").write_bytes(b"png")
