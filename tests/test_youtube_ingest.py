"""Tests for the YouTube ingestion chain: acquire_audio, transcribe, translate,
routing, and the human_review_base_script gate.

Heavy dependencies (yt-dlp subprocess, whisperx) are mocked throughout, same
pattern as tests/voice/test_aligner.py — these run without network or a GPU.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.youtube_ingest.pipeline import (
    AudioAcquisitionPipeline,
    TranscriptionPipeline,
    TranslationPipeline,
    _load_translation_system_prompt,
)


def _make_response(text: str) -> MagicMock:
    r = MagicMock()
    r.text = text
    return r


# ── AudioAcquisitionPipeline ─────────────────────────────────────────────────


class TestAudioAcquisitionPipeline:
    def test_downloads_when_not_cached(self, tmp_path):
        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with patch("ytfactory.youtube_ingest.pipeline.subprocess.run") as mock_run:
                def _fake_run(cmd, **kwargs):
                    out_template = cmd[cmd.index("-o") + 1]
                    out_path = Path(out_template.replace("%(ext)s", "mp3"))
                    out_path.write_bytes(b"fake audio")
                    return MagicMock(returncode=0)

                mock_run.side_effect = _fake_run
                audio_path = AudioAcquisitionPipeline().run(
                    "proj-1", "https://youtube.com/watch?v=abc"
                )

        assert audio_path.exists()
        source_file = tmp_path / "proj-1" / "ingestion" / "source.json"
        assert json.loads(source_file.read_text())["url"] == "https://youtube.com/watch?v=abc"
        mock_run.assert_called_once()

    def test_skips_download_when_same_url_cached(self, tmp_path):
        ingest_dir = tmp_path / "proj-2" / "ingestion"
        ingest_dir.mkdir(parents=True)
        (ingest_dir / "audio.mp3").write_bytes(b"cached audio")
        (ingest_dir / "source.json").write_text(
            json.dumps({"url": "https://youtube.com/watch?v=same"}), encoding="utf-8"
        )

        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with patch("ytfactory.youtube_ingest.pipeline.subprocess.run") as mock_run:
                AudioAcquisitionPipeline().run("proj-2", "https://youtube.com/watch?v=same")

        mock_run.assert_not_called()

    def test_redownloads_when_url_changed(self, tmp_path):
        ingest_dir = tmp_path / "proj-3" / "ingestion"
        ingest_dir.mkdir(parents=True)
        (ingest_dir / "audio.mp3").write_bytes(b"old audio")
        (ingest_dir / "source.json").write_text(
            json.dumps({"url": "https://youtube.com/watch?v=old"}), encoding="utf-8"
        )

        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with patch("ytfactory.youtube_ingest.pipeline.subprocess.run") as mock_run:
                def _fake_run(cmd, **kwargs):
                    out_template = cmd[cmd.index("-o") + 1]
                    Path(out_template.replace("%(ext)s", "mp3")).write_bytes(b"new audio")
                    return MagicMock(returncode=0)

                mock_run.side_effect = _fake_run
                AudioAcquisitionPipeline().run("proj-3", "https://youtube.com/watch?v=new")

        mock_run.assert_called_once()
        source_file = ingest_dir / "source.json"
        assert json.loads(source_file.read_text())["url"] == "https://youtube.com/watch?v=new"

    def test_fails_cleanly_when_ytdlp_missing(self, tmp_path):
        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with patch(
                "ytfactory.youtube_ingest.pipeline.subprocess.run",
                side_effect=FileNotFoundError(),
            ):
                with pytest.raises(RuntimeError, match="yt-dlp not found"):
                    AudioAcquisitionPipeline().run("proj-4", "https://youtube.com/watch?v=x")

    def test_fails_cleanly_on_ytdlp_error(self, tmp_path):
        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with patch(
                "ytfactory.youtube_ingest.pipeline.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "yt-dlp", stderr="boom"),
            ):
                with pytest.raises(RuntimeError, match="yt-dlp failed"):
                    AudioAcquisitionPipeline().run("proj-5", "https://youtube.com/watch?v=x")


# ── TranscriptionPipeline ────────────────────────────────────────────────────


class TestTranscriptionPipeline:
    def _settings(self):
        s = MagicMock()
        s.youtube_ingest_language = "kn"
        s.whisperx_model = "large-v3"
        s.whisperx_device = "cpu"
        return s

    def test_raises_when_no_audio(self, tmp_path):
        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with pytest.raises(FileNotFoundError):
                TranscriptionPipeline(self._settings()).run("proj-1")

    def test_transcribes_and_caches(self, tmp_path):
        ingest_dir = tmp_path / "proj-2" / "ingestion"
        ingest_dir.mkdir(parents=True)
        (ingest_dir / "audio.mp3").write_bytes(b"audio")

        mock_wx = MagicMock()
        fake_model = MagicMock()
        fake_model.transcribe.return_value = {
            "segments": [{"text": "ಒಂದು ಪಕ್ಷಿ"}, {"text": "ಗೂಡು ಕಟ್ಟಿತು"}]
        }
        mock_wx.load_model.return_value = fake_model
        mock_wx.load_audio.return_value = "fake-audio-array"

        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with patch.dict(sys.modules, {"whisperx": mock_wx}):
                transcript = TranscriptionPipeline(self._settings()).run("proj-2")

        assert "ಒಂದು ಪಕ್ಷಿ" in transcript
        assert "ಗೂಡು ಕಟ್ಟಿತು" in transcript
        mock_wx.load_model.assert_called_once_with(
            "large-v3", "cpu", compute_type="float32", language="kn"
        )
        assert (ingest_dir / "transcript_kn.md").exists()

        # Second call: cached, whisperx never touched again.
        mock_wx.reset_mock()
        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with patch.dict(sys.modules, {"whisperx": mock_wx}):
                cached = TranscriptionPipeline(self._settings()).run("proj-2")
        assert cached == transcript
        mock_wx.load_model.assert_not_called()

    def test_fails_cleanly_when_whisperx_missing(self, tmp_path):
        ingest_dir = tmp_path / "proj-3" / "ingestion"
        ingest_dir.mkdir(parents=True)
        (ingest_dir / "audio.mp3").write_bytes(b"audio")

        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with patch.dict(sys.modules, {"whisperx": None}):
                with pytest.raises(RuntimeError, match="requires the 'whisperx' package"):
                    TranscriptionPipeline(self._settings()).run("proj-3")


# ── TranslationPipeline ──────────────────────────────────────────────────────


class TestTranslationPipeline:
    def test_raises_when_no_transcript(self, tmp_path):
        settings = MagicMock()
        with patch("ytfactory.youtube_ingest.pipeline.get_llm_for_role", return_value=MagicMock()):
            pipeline = TranslationPipeline(settings)
        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with pytest.raises(FileNotFoundError):
                pipeline.run("proj-1")

    def test_translates_uses_discourse_system_prompt_and_writes_both_locations(self, tmp_path):
        ingest_dir = tmp_path / "proj-2" / "ingestion"
        ingest_dir.mkdir(parents=True)
        (ingest_dir / "transcript_kn.md").write_text("ಒಂದು ಪಕ್ಷಿ ಗೂಡು ಕಟ್ಟಿತು", encoding="utf-8")

        mock_llm = MagicMock()
        mock_llm.generate.return_value = _make_response("A bird built a nest.")

        settings = MagicMock()
        with patch("ytfactory.youtube_ingest.pipeline.get_llm_for_role", return_value=mock_llm):
            pipeline = TranslationPipeline(settings)

        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-2")

        assert result == "A bird built a nest."
        assert (ingest_dir / "base_script_en.md").read_text(encoding="utf-8") == result
        assert (tmp_path / "proj-2" / "script" / "script.md").read_text(
            encoding="utf-8"
        ) == result

        call_kwargs = mock_llm.generate.call_args.kwargs
        assert call_kwargs["system_prompt"] == _load_translation_system_prompt()
        assert "ಒಂದು ಪಕ್ಷಿ ಗೂಡು ಕಟ್ಟಿತು" in mock_llm.generate.call_args.args[0]

    def test_cached_translation_skips_llm_call(self, tmp_path):
        ingest_dir = tmp_path / "proj-3" / "ingestion"
        ingest_dir.mkdir(parents=True)
        (ingest_dir / "transcript_kn.md").write_text("transcript", encoding="utf-8")
        (ingest_dir / "base_script_en.md").write_text("Cached base script.", encoding="utf-8")

        mock_llm = MagicMock()
        settings = MagicMock()
        with patch("ytfactory.youtube_ingest.pipeline.get_llm_for_role", return_value=mock_llm):
            pipeline = TranslationPipeline(settings)

        with patch("ytfactory.youtube_ingest.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-3")

        assert result == "Cached base script."
        mock_llm.generate.assert_not_called()
        # Still copied to the canonical script/script.md location even when cached.
        assert (tmp_path / "proj-3" / "script" / "script.md").read_text(
            encoding="utf-8"
        ) == "Cached base script."


class TestTranslationSystemPromptLoader:
    def test_loads_atma_discourse_spec(self):
        prompt = _load_translation_system_prompt()
        assert "BASE SCRIPT" in prompt
        assert "faithful, complete translation" in prompt.lower() or "faithful" in prompt


# ── Graph routing ─────────────────────────────────────────────────────────────


class TestRouteEntry:
    def test_routes_to_acquire_audio_when_source_url_set(self):
        from ytfactory.agents.graph import _route_entry

        assert _route_entry({"source_url": "https://youtube.com/x"}) == "acquire_audio"

    def test_source_url_takes_priority_over_script_md(self):
        from ytfactory.agents.graph import _route_entry

        state = {"source_url": "https://youtube.com/x", "script_md": "already have a script"}
        assert _route_entry(state) == "acquire_audio"

    def test_routes_to_beats_extractor_when_script_md_set(self):
        from ytfactory.agents.graph import _route_entry

        assert _route_entry({"script_md": "some script"}) == "beats_extractor"

    def test_routes_to_beats_extractor_by_default(self):
        from ytfactory.agents.graph import _route_entry

        # Non-URL sources go through beats_extractor before the script refinement path.
        assert _route_entry({}) == "beats_extractor"

    def test_graph_contains_ingestion_nodes(self):
        from ytfactory.agents.graph import build_graph

        nodes = build_graph().nodes.keys()
        for name in ("acquire_audio", "transcribe", "translate", "human_review_base_script"):
            assert name in nodes


# ── Nodes ─────────────────────────────────────────────────────────────────────


class TestIngestNodes:
    def test_acquire_audio_node_delegates(self):
        from ytfactory.agents.nodes.youtube_ingest import acquire_audio_node

        with patch(
            "ytfactory.agents.nodes.youtube_ingest.AudioAcquisitionPipeline"
        ) as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            result = acquire_audio_node(
                {"project_id": "proj-1", "source_url": "https://youtube.com/x"}
            )
        mock_instance.run.assert_called_once_with("proj-1", "https://youtube.com/x")
        assert result == {}

    def test_transcribe_node_delegates(self):
        from ytfactory.agents.nodes.youtube_ingest import transcribe_node

        with patch("ytfactory.agents.nodes.youtube_ingest.Settings"):
            with patch(
                "ytfactory.agents.nodes.youtube_ingest.TranscriptionPipeline"
            ) as mock_cls:
                mock_instance = MagicMock()
                mock_cls.return_value = mock_instance
                result = transcribe_node({"project_id": "proj-1"})
        mock_instance.run.assert_called_once_with("proj-1")
        assert result == {}

    def test_translate_node_returns_script_md(self):
        from ytfactory.agents.nodes.youtube_ingest import translate_node

        with patch("ytfactory.agents.nodes.youtube_ingest.Settings"):
            with patch(
                "ytfactory.agents.nodes.youtube_ingest.TranslationPipeline"
            ) as mock_cls:
                mock_instance = MagicMock()
                mock_instance.run.return_value = "Translated base script."
                mock_cls.return_value = mock_instance
                result = translate_node({"project_id": "proj-1"})
        assert result == {"script_md": "Translated base script."}


class TestHumanReviewBaseScriptNode:
    def test_auto_mode_is_noop(self):
        from ytfactory.agents.nodes.human_review import human_review_base_script_node

        result = human_review_base_script_node({"auto_mode": True, "script_md": "x"})
        assert result == {}

    def test_approve_continues(self):
        from ytfactory.agents.nodes.human_review import human_review_base_script_node

        with patch("ytfactory.agents.nodes.human_review.typer.prompt", return_value="a"):
            result = human_review_base_script_node(
                {"auto_mode": False, "script_md": "A translated base script."}
            )
        assert result == {}

    def test_quit_aborts(self):
        import typer

        from ytfactory.agents.nodes.human_review import human_review_base_script_node

        with patch("ytfactory.agents.nodes.human_review.typer.prompt", return_value="q"):
            with pytest.raises(typer.Abort):
                human_review_base_script_node(
                    {"auto_mode": False, "script_md": "A translated base script."}
                )


# ── run_pipeline() source validation ─────────────────────────────────────────


class TestRunPipelineSourceValidation:
    def test_script_path_and_source_url_mutually_exclusive(self):
        from ytfactory.agents.runner import run_pipeline

        with pytest.raises(ValueError, match="mutually exclusive"):
            run_pipeline(
                "Topic",
                script_path="some/script.md",
                source_url="https://youtube.com/x",
            )
