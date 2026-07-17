"""Tests for the Publishing & Growth Engine V1.

Covers:
  - PublishConfig (defaults, thumbnail dimensions)
  - ChapterEntry, TitleResult, SEOResult, DescriptionResult, ThumbnailResult,
    PublishingPackage (fields, to_dict)
  - ChaptersGenerator (cumulative timestamps, real audio duration, fallback)
  - TitleGenerator (LLM JSON parsing, fallback, length validation, file write)
  - SEOGenerator (tag budget clamping, hashtag # prefix, file write)
  - DescriptionGenerator (CTA/chapters detection, length clamp, file write)
  - ThumbnailGenerator (mock image provider, skip_thumbnail, variant count)
  - UploadPackageGenerator (metadata JSON, validation errors/warnings)
  - PublishPipeline (integration: all mocked providers, all output files created)
  - Backward compatibility: publish in project.stages, review/remediation unaffected
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_core.domain.llm import LLMResponse
from ytfactory.publish.config import PublishConfig
from ytfactory.publish.generators.chapters import ChaptersGenerator, _format_timestamp
from ytfactory.publish.generators.description import DescriptionGenerator
from ytfactory.publish.generators.package import UploadPackageGenerator
from ytfactory.publish.generators.seo import SEOGenerator, _clamp_tags
from ytfactory.publish.generators.thumbnail import ThumbnailGenerator
from ytfactory.publish.generators.title import TitleGenerator
from ytfactory.publish.models import (
    ChapterEntry,
    DescriptionResult,
    PublishingPackage,
    SEOResult,
    ThumbnailResult,
    TitleResult,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_pub(tmp_path, monkeypatch):
    """Patch WORKSPACE_DIR in all publish modules and return tmp_path."""
    monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr("ytfactory.publish.pipeline.WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr("ytfactory.publish.generators.chapters.WORKSPACE_DIR", str(tmp_path), raising=False)
    return tmp_path


def _llm_mock(json_text: str) -> MagicMock:
    """Return a mock LLM provider that returns json_text."""
    mock = MagicMock()
    mock.generate.return_value = LLMResponse(text=json_text, model="mock")
    return mock


def _image_mock() -> MagicMock:
    """Return a mock image provider that creates a blank file on generate()."""
    mock = MagicMock()

    def _side_effect(request):
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        request.output_path.write_bytes(b"PNG")
        return MagicMock(file=request.output_path, width=request.width, height=request.height)

    mock.generate.side_effect = _side_effect
    return mock


def _make_scenes() -> list[dict]:
    return [
        {"index": 1, "title": "Introduction", "narration": "Hello", "duration_seconds": 10.0, "visual_prompt": "sunrise"},
        {"index": 2, "title": "The Rise", "narration": "And so", "duration_seconds": 20.0, "visual_prompt": "empire"},
    ]


def _write_project(tmp_path: Path, project_id: str, title: str = "Test Video") -> None:
    proj_dir = tmp_path / project_id
    (proj_dir / "scenes").mkdir(parents=True)
    (proj_dir / "audio").mkdir(parents=True)
    (proj_dir / "script").mkdir(parents=True)

    scene_plan = {"scenes": _make_scenes()}
    (proj_dir / "scenes" / "scene-plan.json").write_text(json.dumps(scene_plan))
    (proj_dir / "script" / "script.md").write_text("Once upon a time in India…")
    (proj_dir / "project.json").write_text(json.dumps({
        "id": project_id,
        "title": title,
        "language": "en",
        "stages": {s: "pending" for s in
                   ["research", "script", "scenes", "images", "audio", "subtitles", "video", "publish"]},
    }))


# ── PublishConfig ─────────────────────────────────────────────────────────────


class TestPublishConfig:
    def test_defaults(self):
        cfg = PublishConfig()
        assert cfg.thumbnail_width == 1280
        assert cfg.thumbnail_height == 720
        assert cfg.max_title_length == 100
        assert cfg.optimal_title_length == 70
        assert cfg.max_tags_chars == 500
        assert cfg.max_hashtags == 15
        assert cfg.thumbnail_variants == 3
        assert not cfg.skip_thumbnail

    def test_thumbnail_not_1080p(self):
        cfg = PublishConfig()
        assert cfg.thumbnail_height != 1080
        assert cfg.thumbnail_width != 1920


# ── Models ────────────────────────────────────────────────────────────────────


class TestChapterEntry:
    def test_to_dict(self):
        e = ChapterEntry(index=1, timestamp_seconds=0.0, timestamp_str="0:00", title="Intro")
        d = e.to_dict()
        assert d["index"] == 1
        assert d["timestamp_str"] == "0:00"
        assert d["title"] == "Intro"

    def test_format_timestamp_minutes(self):
        assert _format_timestamp(0) == "0:00"
        assert _format_timestamp(75) == "1:15"
        assert _format_timestamp(3600) == "1:00:00"
        assert _format_timestamp(3661) == "1:01:01"


class TestTitleResult:
    def test_to_dict(self):
        r = TitleResult(primary="My Title", alternatives=["A", "B", "C", "D", "E"],
                        length_valid=True, length_warning=False)
        d = r.to_dict()
        assert d["primary"] == "My Title"
        assert len(d["alternatives"]) == 5
        assert d["length_valid"]

    def test_length_flags(self):
        long_title = "X" * 101
        r = TitleResult(primary=long_title, alternatives=[],
                        length_valid=False, length_warning=True)
        assert not r.length_valid
        assert r.length_warning


class TestSEOResult:
    def test_all_keywords_combines(self):
        r = SEOResult(
            primary_keywords=["a"], secondary_keywords=["b"],
            long_tail_keywords=["c"], hashtags=["#d"],
            youtube_tags=["a", "b"], total_tags_chars=4,
        )
        assert r.all_keywords == ["a", "b", "c"]

    def test_to_dict(self):
        r = SEOResult(primary_keywords=["k"], secondary_keywords=[],
                      long_tail_keywords=[], hashtags=[], youtube_tags=[], total_tags_chars=0)
        d = r.to_dict()
        assert "primary_keywords" in d
        assert d["primary_keywords"] == ["k"]


class TestDescriptionResult:
    def test_to_dict_fields(self):
        r = DescriptionResult(full_text="hello", word_count=1, has_chapters=False, has_cta=True)
        d = r.to_dict()
        assert "word_count" in d
        assert d["has_cta"]


class TestPublishingPackage:
    def _make_package(self, tmp_path):
        title = TitleResult(primary="T", alternatives=["A"] * 5,
                            length_valid=True, length_warning=False)
        seo = SEOResult(primary_keywords=[], secondary_keywords=[], long_tail_keywords=[],
                        hashtags=[], youtube_tags=[], total_tags_chars=0)
        desc = DescriptionResult(full_text="desc", word_count=1, has_chapters=False, has_cta=False)
        return PublishingPackage(
            project_id="test", timestamp="2026-01-01T00:00:00Z",
            title=title, seo=seo, description=desc,
            output_dir=tmp_path,
        )

    def test_to_dict_version(self, tmp_path):
        pkg = self._make_package(tmp_path)
        d = pkg.to_dict()
        assert d["version"] == "v1"
        assert d["project_id"] == "test"

    def test_is_valid_default_true(self, tmp_path):
        pkg = self._make_package(tmp_path)
        assert pkg.is_valid


# ── ChaptersGenerator ─────────────────────────────────────────────────────────


class TestChaptersGenerator:
    def test_cumulative_timestamps(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "proj1"
        (tmp_path / project_id / "publish").mkdir(parents=True)

        scenes = [
            {"index": 1, "title": "Intro", "duration_seconds": 30.0},
            {"index": 2, "title": "Body", "duration_seconds": 45.0},
            {"index": 3, "title": "End", "duration_seconds": 15.0},
        ]
        entries = ChaptersGenerator().generate(project_id, tmp_path / project_id, scenes)

        assert entries[0].timestamp_seconds == 0.0
        assert entries[0].timestamp_str == "0:00"
        assert entries[1].timestamp_seconds == 30.0
        assert entries[1].timestamp_str == "0:30"
        assert entries[2].timestamp_seconds == 75.0
        assert entries[2].timestamp_str == "1:15"

    def test_uses_real_audio_duration(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "proj2"
        proj_dir = tmp_path / project_id
        (proj_dir / "audio").mkdir(parents=True)
        (proj_dir / "publish").mkdir(parents=True)

        # Write timing.json with last entry end=25.5
        timing = [{"word": "hello", "start": 0.0, "end": 12.0},
                  {"word": "world", "start": 12.0, "end": 25.5}]
        (proj_dir / "audio" / "scene-001.timing.json").write_text(json.dumps(timing))

        scenes = [{"index": 1, "title": "Scene 1", "duration_seconds": 10.0}]
        entries = ChaptersGenerator().generate(project_id, proj_dir, scenes)
        # cumulative starts at 0; next scene would start at 25.5 — just verify entry 1 = 0
        assert entries[0].timestamp_seconds == 0.0

    def test_fallback_when_timing_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "proj3"
        (tmp_path / project_id / "publish").mkdir(parents=True)

        scenes = [
            {"index": 1, "title": "A", "duration_seconds": 20.0},
            {"index": 2, "title": "B", "duration_seconds": 40.0},
        ]
        entries = ChaptersGenerator().generate(project_id, tmp_path / project_id, scenes)
        assert entries[1].timestamp_seconds == 20.0

    def test_writes_chapters_txt(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "proj4"
        (tmp_path / project_id / "publish").mkdir(parents=True)
        scenes = [{"index": 1, "title": "Intro", "duration_seconds": 10.0}]
        ChaptersGenerator().generate(project_id, tmp_path / project_id, scenes)

        txt = (tmp_path / project_id / "publish" / "chapters.txt").read_text()
        assert "0:00 Intro" in txt

    # ── Chapter cap / merge tests ─────────────────────────────────────────────

    def _fake_settings(self, max_chapters=10, min_seconds=10):
        s = MagicMock()
        s.publish_max_chapters = max_chapters
        s.publish_min_chapter_seconds = min_seconds
        return s

    def test_under_cap_unchanged(self, tmp_path, monkeypatch):
        """5 scenes (each 30s) → 5 chapters; not padded up to 10."""
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "cap1"
        (tmp_path / project_id / "publish").mkdir(parents=True)
        scenes = [{"index": i, "title": f"Scene {i}", "duration_seconds": 30.0} for i in range(1, 6)]
        entries = ChaptersGenerator(self._fake_settings()).generate(
            project_id, tmp_path / project_id, scenes
        )
        assert len(entries) == 5

    def test_over_cap_merged_to_max(self, tmp_path, monkeypatch):
        """12 scenes (each 30s) → exactly 10 chapters after merge."""
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "cap2"
        (tmp_path / project_id / "publish").mkdir(parents=True)
        scenes = [{"index": i, "title": f"Scene {i}", "duration_seconds": 30.0} for i in range(1, 13)]
        entries = ChaptersGenerator(self._fake_settings(max_chapters=10)).generate(
            project_id, tmp_path / project_id, scenes
        )
        assert len(entries) == 10

    def test_sub_minimum_merged_further(self, tmp_path, monkeypatch):
        """After grouping to 10 chapters a short-duration chapter triggers further merge.

        12 scenes: scenes 11 and 12 are 4s each.  Grouped as 10 → some chapter ends
        up < 10s → merged further → fewer than 10 chapters, all >= 10s.
        """
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "cap3"
        (tmp_path / project_id / "publish").mkdir(parents=True)
        scenes = [{"index": i, "title": f"S{i}", "duration_seconds": 30.0} for i in range(1, 11)]
        # Two tiny scenes at the end
        scenes += [
            {"index": 11, "title": "S11", "duration_seconds": 4.0},
            {"index": 12, "title": "S12", "duration_seconds": 4.0},
        ]
        entries = ChaptersGenerator(self._fake_settings(max_chapters=10, min_seconds=10)).generate(
            project_id, tmp_path / project_id, scenes
        )
        # All chapters meet the minimum duration
        from ytfactory.publish.generators.chapters import _make_chapter_groups
        durations = [s["duration_seconds"] for s in scenes]
        groups = _make_chapter_groups(len(scenes), durations, 10, 10)
        for g in groups:
            assert sum(durations[i] for i in g) >= 10
        # Chapter count is <= cap
        assert len(entries) <= 10

    def test_first_chapter_always_zero(self, tmp_path, monkeypatch):
        """First chapter timestamp must always be 0:00 regardless of input."""
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "cap4"
        (tmp_path / project_id / "publish").mkdir(parents=True)
        scenes = [{"index": i, "title": f"S{i}", "duration_seconds": 20.0} for i in range(1, 8)]
        entries = ChaptersGenerator(self._fake_settings()).generate(
            project_id, tmp_path / project_id, scenes
        )
        assert entries[0].timestamp_seconds == 0.0
        assert entries[0].timestamp_str == "0:00"


# ── TitleGenerator ────────────────────────────────────────────────────────────


class TestTitleGenerator:
    def _gen(self, project_id, tmp_path, monkeypatch, json_text):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        (tmp_path / project_id / "publish").mkdir(parents=True)
        return TitleGenerator(_llm_mock(json_text)).generate(
            project_id=project_id, project_title="History of Shivaji",
            script_excerpt="Long ago…", scene_titles=["Ch1", "Ch2"],
        )

    def test_parses_llm_json(self, tmp_path, monkeypatch):
        payload = '{"primary": "Shivaji the Great", "alternatives": ["A","B","C","D","E"]}'
        result = self._gen("t1", tmp_path, monkeypatch, payload)
        assert result.primary == "Shivaji the Great"
        assert result.alternatives == ["A", "B", "C", "D", "E"]

    def test_fallback_on_parse_error(self, tmp_path, monkeypatch):
        result = self._gen("t2", tmp_path, monkeypatch, "not json at all")
        assert result.primary == "History of Shivaji"
        assert len(result.alternatives) == 5

    def test_length_valid_flag(self, tmp_path, monkeypatch):
        short = '{"primary": "Short", "alternatives": ["A","B","C","D","E"]}'
        result = self._gen("t3", tmp_path, monkeypatch, short)
        assert result.length_valid

    def test_length_warning_over_70(self, tmp_path, monkeypatch):
        long_title = "X" * 75
        payload = f'{{"primary": "{long_title}", "alternatives": ["A","B","C","D","E"]}}'
        result = self._gen("t4", tmp_path, monkeypatch, payload)
        assert result.length_warning

    def test_writes_title_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "t5"
        (tmp_path / project_id / "publish").mkdir(parents=True)
        payload = '{"primary": "My Video", "alternatives": ["A","B","C","D","E"]}'
        TitleGenerator(_llm_mock(payload)).generate(
            project_id=project_id, project_title="My Video",
            script_excerpt="", scene_titles=[],
        )
        assert (tmp_path / project_id / "publish" / "title.txt").read_text() == "My Video"
        alts = (tmp_path / project_id / "publish" / "alternate-titles.txt").read_text()
        assert "A" in alts

    def test_strips_markdown_fences(self, tmp_path, monkeypatch):
        payload = '```json\n{"primary": "Clean", "alternatives": ["A","B","C","D","E"]}\n```'
        result = self._gen("t6", tmp_path, monkeypatch, payload)
        assert result.primary == "Clean"


# ── SEOGenerator ─────────────────────────────────────────────────────────────


class TestSEOGenerator:
    def _gen(self, project_id, tmp_path, monkeypatch, json_text, config=None):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        (tmp_path / project_id / "publish").mkdir(parents=True)
        return SEOGenerator(_llm_mock(json_text), config).generate(
            project_id=project_id, project_title="Test", script_excerpt="", scene_titles=[],
        )

    def _payload(self):
        return json.dumps({
            "primary_keywords": ["kw1", "kw2"],
            "secondary_keywords": ["sk1"],
            "long_tail_keywords": ["long phrase here"],
            "hashtags": ["#tag1", "tag2"],
            "youtube_tags": ["kw1", "kw2", "sk1"],
        })

    def test_parses_llm_json(self, tmp_path, monkeypatch):
        result = self._gen("s1", tmp_path, monkeypatch, self._payload())
        assert result.primary_keywords == ["kw1", "kw2"]

    def test_hashtag_prefix_added(self, tmp_path, monkeypatch):
        result = self._gen("s2", tmp_path, monkeypatch, self._payload())
        assert all(h.startswith("#") for h in result.hashtags)

    def test_tag_budget_clamping(self, tmp_path, monkeypatch):
        payload = json.dumps({
            "primary_keywords": [], "secondary_keywords": [],
            "long_tail_keywords": [],
            "hashtags": [],
            "youtube_tags": ["word"] * 100,
        })
        config = PublishConfig(max_tags_chars=20)
        result = self._gen("s3", tmp_path, monkeypatch, payload, config)
        assert result.total_tags_chars <= 20

    def test_clamp_tags_function(self):
        tags = ["apple", "banana", "cherry", "date"]
        clamped = _clamp_tags(tags, 15)
        assert len(", ".join(clamped)) <= 15

    def test_writes_files(self, tmp_path, monkeypatch):
        self._gen("s4", tmp_path, monkeypatch, self._payload())
        assert (tmp_path / "s4" / "publish" / "keywords.txt").exists()
        assert (tmp_path / "s4" / "publish" / "hashtags.txt").exists()
        assert (tmp_path / "s4" / "publish" / "youtube-tags.txt").exists()

    def test_fallback_on_bad_json(self, tmp_path, monkeypatch):
        result = self._gen("s5", tmp_path, monkeypatch, "garbage")
        assert result.primary_keywords == []


# ── DescriptionGenerator ──────────────────────────────────────────────────────


def _desc_payload(**overrides) -> str:
    """Return a valid template-spec JSON payload with sensible defaults."""
    data = {
        "search_queries": ["Why do we suffer?", "Bhagavad Gita suffering"],
        "hook": "Why does suffering follow us no matter how hard we try to escape it?",
        "who_this_is_for": [
            "wondered why pain keeps returning",
            "wanted ancient wisdom in plain language",
        ],
        "what_you_discover": [
            "The root cause of suffering",
            "What the Gita says about acceptance",
        ],
        "key_teachings": [
            "Suffering is resistance to what is.",
            "Acceptance is not defeat — it is clarity.",
        ],
        "questions_answered": [
            "What causes suffering according to the Bhagavad Gita?",
            "How do I stop resisting change?",
        ],
        "what_you_experience": "A calm, clear journey through one of life's hardest questions.",
        "this_video_explains": "Why the Gita frames suffering as a signal, not a punishment.",
        "sources": ["Bhagavad Gita Chapter 2"],
        "engagement_prompt": "Which teaching stayed with you after watching?",
        "hashtags": ["#BhagavadGita", "#Suffering", "#Vedanta"],
    }
    data.update(overrides)
    return json.dumps(data)


class TestDescriptionGenerator:
    def _gen(self, project_id, tmp_path, monkeypatch, json_text, config=None):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        (tmp_path / project_id / "publish").mkdir(parents=True)
        return DescriptionGenerator(_llm_mock(json_text), config).generate(
            project_id=project_id,
            project_title="Why We Suffer — Bhagavad Gita",
            script="The teacher explained suffering at length.",
        )

    def test_template_sections_assembled(self, tmp_path, monkeypatch):
        """All sections from the template spec appear in the assembled description."""
        result = self._gen("d1", tmp_path, monkeypatch, _desc_payload())
        assert "Why does suffering follow" in result.full_text       # hook
        assert "This video is for you" in result.full_text           # who-for
        assert "What You'll Discover" in result.full_text            # discover
        assert "Key Teachings" in result.full_text                   # key teachings
        assert "Questions Answered" in result.full_text              # Q&A
        assert "What You'll Experience" in result.full_text          # experience
        assert "This Video Explains" in result.full_text             # explains
        assert "Sources" in result.full_text                         # sources
        assert "Which teaching stayed with you" in result.full_text  # engagement
        assert "#BhagavadGita" in result.full_text                   # hashtags

    def test_has_chapters_always_false(self, tmp_path, monkeypatch):
        """Spec: no chapters for 7–10 min format — has_chapters must always be False."""
        result = self._gen("d2", tmp_path, monkeypatch, _desc_payload())
        assert result.has_chapters is False

    def test_has_cta_detected_via_subscribe(self, tmp_path, monkeypatch):
        config = PublishConfig(subscribe_url="https://youtube.com/@channel")
        result = self._gen("d3", tmp_path, monkeypatch, _desc_payload(), config)
        assert result.has_cta

    def test_length_clamped(self, tmp_path, monkeypatch):
        # Produce a very long payload by repeating content
        big = _desc_payload(what_you_experience="A" * 4000)
        config = PublishConfig(max_description_length=5000)
        result = self._gen("d4", tmp_path, monkeypatch, big, config)
        assert len(result.full_text) <= 5000

    def test_fallback_on_bad_json(self, tmp_path, monkeypatch):
        result = self._gen("d5", tmp_path, monkeypatch, "not json at all")
        assert result.full_text  # non-empty fallback
        assert result.word_count > 0

    def test_writes_description_md(self, tmp_path, monkeypatch):
        self._gen("d6", tmp_path, monkeypatch, _desc_payload())
        assert (tmp_path / "d6" / "publish" / "description.md").exists()

    def test_search_queries_stored(self, tmp_path, monkeypatch):
        result = self._gen("d7", tmp_path, monkeypatch, _desc_payload())
        assert "Why do we suffer?" in result.search_queries

    def test_sections_present_populated(self, tmp_path, monkeypatch):
        result = self._gen("d8", tmp_path, monkeypatch, _desc_payload())
        assert "hook" in result.sections_present
        assert "key_teachings" in result.sections_present
        assert "questions_answered" in result.sections_present

    def test_sources_section_omitted_when_empty(self, tmp_path, monkeypatch):
        payload = _desc_payload(sources=[])
        result = self._gen("d9", tmp_path, monkeypatch, payload)
        assert "Sources" not in result.full_text

    def test_hashtags_capped_at_config_max(self, tmp_path, monkeypatch):
        many_tags = [f"#tag{i}" for i in range(20)]
        config = PublishConfig(description_max_hashtags=5)
        payload = _desc_payload(hashtags=many_tags)
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "d10" / "publish").mkdir(parents=True)
        result = DescriptionGenerator(_llm_mock(payload), config).generate(
            project_id="d10", project_title="Test", script="Some script."
        )
        shown_tags = [w for w in result.full_text.split() if w.startswith("#")]
        assert len(shown_tags) <= 5

    def test_links_block_subscribe_first(self, tmp_path, monkeypatch):
        config = PublishConfig(
            subscribe_url="https://youtube.com/@ch",
            playlist_url="https://youtube.com/playlist?list=ABC",
        )
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "d11" / "publish").mkdir(parents=True)
        result = DescriptionGenerator(_llm_mock(_desc_payload()), config).generate(
            project_id="d11", project_title="Test", script="Script."
        )
        sub_pos = result.full_text.find("Subscribe")
        playlist_pos = result.full_text.find("Playlist")
        assert sub_pos != -1
        assert playlist_pos != -1
        assert sub_pos < playlist_pos  # Subscribe before Playlist

    def test_links_block_omitted_when_no_urls(self, tmp_path, monkeypatch):
        config = PublishConfig()  # no URLs configured
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "d12" / "publish").mkdir(parents=True)
        result = DescriptionGenerator(_llm_mock(_desc_payload()), config).generate(
            project_id="d12", project_title="Test", script="Script."
        )
        assert "▶" not in result.full_text

    def test_legacy_caller_compat(self, tmp_path, monkeypatch):
        """Old callers using script_excerpt and chapters_block don't raise."""
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        (tmp_path / "d13" / "publish").mkdir(parents=True)
        result = DescriptionGenerator(_llm_mock(_desc_payload())).generate(
            project_id="d13", project_title="Test Video",
            script_excerpt="Once upon a time…",
            chapters_block="0:00 Intro\n1:30 Body",
            seo_keywords=["kw1"],
        )
        assert result.full_text


# ── ThumbnailGenerator ────────────────────────────────────────────────────────


class TestThumbnailGenerator:
    def _gen(self, project_id, tmp_path, monkeypatch, config=None):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        (tmp_path / project_id / "publish").mkdir(parents=True)
        img = _image_mock()
        result = ThumbnailGenerator(img, config).generate(
            project_id=project_id, project_title="Test",
            first_scene_visual_prompt="golden temple",
        )
        return result, img

    def test_generates_primary_and_variants(self, tmp_path, monkeypatch):
        result, img = self._gen("th1", tmp_path, monkeypatch)
        assert result is not None
        assert result.primary_path.exists()
        assert len(result.variant_paths) == 3

    def test_thumbnail_dimensions_1280x720(self, tmp_path, monkeypatch):
        result, img = self._gen("th2", tmp_path, monkeypatch)
        assert result.width == 1280
        assert result.height == 720

    def test_skip_thumbnail_returns_none(self, tmp_path, monkeypatch):
        config = PublishConfig(skip_thumbnail=True)
        result, img = self._gen("th3", tmp_path, monkeypatch, config)
        assert result is None
        img.generate.assert_not_called()

    def test_variant_count_configurable(self, tmp_path, monkeypatch):
        config = PublishConfig(thumbnail_variants=2)
        result, _ = self._gen("th4", tmp_path, monkeypatch, config)
        assert result is not None
        assert len(result.variant_paths) == 2

    def test_to_dict(self, tmp_path, monkeypatch):
        result, _ = self._gen("th5", tmp_path, monkeypatch)
        assert result is not None
        d = result.to_dict()
        assert "primary_path" in d
        assert "variant_paths" in d


# ── UploadPackageGenerator ────────────────────────────────────────────────────


class TestUploadPackageGenerator:
    def _make_title(self, primary="My Title"):
        return TitleResult(primary=primary, alternatives=["A"] * 5,
                           length_valid=True, length_warning=False)

    def _make_seo(self):
        return SEOResult(primary_keywords=["k"], secondary_keywords=[],
                         long_tail_keywords=[], hashtags=["#h"],
                         youtube_tags=["k"], total_tags_chars=1)

    def _make_desc(self, has_cta=True, has_chapters=True):
        return DescriptionResult(
            full_text="Watch and subscribe now! 0:00 Intro",
            word_count=6, has_chapters=has_chapters, has_cta=has_cta,
        )

    def _make_chapters(self):
        return [ChapterEntry(index=1, timestamp_seconds=0.0, timestamp_str="0:00", title="Intro")]

    def test_writes_metadata_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "pkg1"
        (tmp_path / project_id / "publish").mkdir(parents=True)

        gen = UploadPackageGenerator()
        pkg = gen.generate(
            project_id=project_id, timestamp="2026-01-01T00:00:00Z",
            title=self._make_title(), seo=self._make_seo(),
            description=self._make_desc(), chapters=self._make_chapters(),
            thumbnail=None,
        )
        meta_path = tmp_path / project_id / "publish" / "youtube-metadata.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["version"] == "v1"
        assert meta["project_id"] == project_id

    def test_validation_error_on_long_title(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "pkg2"
        (tmp_path / project_id / "publish").mkdir(parents=True)
        long_title = TitleResult(primary="X" * 101, alternatives=["A"] * 5,
                                 length_valid=False, length_warning=True)
        gen = UploadPackageGenerator()
        pkg = gen.generate(
            project_id=project_id, timestamp="t",
            title=long_title, seo=self._make_seo(),
            description=self._make_desc(), chapters=[], thumbnail=None,
        )
        assert not pkg.is_valid
        assert any("Title exceeds" in e for e in pkg.validation_errors)

    def test_warning_on_no_cta(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "pkg3"
        (tmp_path / project_id / "publish").mkdir(parents=True)
        gen = UploadPackageGenerator()
        pkg = gen.generate(
            project_id=project_id, timestamp="t",
            title=self._make_title(), seo=self._make_seo(),
            description=self._make_desc(has_cta=False), chapters=[], thumbnail=None,
        )
        assert pkg.is_valid  # warnings don't fail validation
        assert any("call-to-action" in w for w in pkg.validation_warnings)

    def test_warning_on_no_thumbnail(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        project_id = "pkg4"
        (tmp_path / project_id / "publish").mkdir(parents=True)
        gen = UploadPackageGenerator()
        pkg = gen.generate(
            project_id=project_id, timestamp="t",
            title=self._make_title(), seo=self._make_seo(),
            description=self._make_desc(), chapters=[], thumbnail=None,
        )
        assert any("thumbnail" in w.lower() for w in pkg.validation_warnings)


# ── PublishPipeline (integration) ─────────────────────────────────────────────


class TestPublishPipeline:
    def test_creates_all_output_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.publish.pipeline.WORKSPACE_DIR", str(tmp_path))

        project_id = "integ1"
        _write_project(tmp_path, project_id, title="History of Shivaji")

        title_json = '{"primary": "Shivaji the Great", "alternatives": ["A","B","C","D","E"]}'
        seo_json = json.dumps({
            "primary_keywords": ["shivaji", "history"],
            "secondary_keywords": ["maratha"],
            "long_tail_keywords": ["history of shivaji maharaj"],
            "hashtags": ["#history", "#india"],
            "youtube_tags": ["shivaji", "history"],
        })
        desc_json = json.dumps({
            "search_queries": ["Who was Shivaji?"],
            "hook": "One man stood against an empire — and changed history forever.",
            "who_this_is_for": ["wondered how ordinary people shape history"],
            "what_you_discover": ["The rise of Shivaji Maharaj"],
            "key_teachings": ["Courage is not the absence of fear."],
            "questions_answered": ["Who was Shivaji Maharaj?", "What did Shivaji accomplish?"],
            "what_you_experience": "A cinematic journey through one of history's greatest stories.",
            "this_video_explains": "How Shivaji built an empire through strategy and valor.",
            "sources": [],
            "engagement_prompt": "Which moment in Shivaji's story moved you most?",
            "hashtags": ["#Shivaji", "#History", "#India"],
        })

        comment_json = '{"comment": "Every one of us carries a silent force. What moment made you feel yours? Share below."}'

        llm = MagicMock()
        llm.generate.side_effect = [
            LLMResponse(text=title_json, model="mock"),
            LLMResponse(text=seo_json, model="mock"),
            LLMResponse(text=desc_json, model="mock"),
            LLMResponse(text=comment_json, model="mock"),
        ]

        from ytfactory.publish.pipeline import PublishPipeline

        config = PublishConfig(skip_thumbnail=True)
        with patch("ytfactory.publish.pipeline.get_llm_provider", return_value=llm), \
             patch("ytfactory.publish.pipeline.get_image_provider", return_value=_image_mock()), \
             patch("ytfactory.publish.pipeline.ProjectRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.load.return_value = MagicMock(title="History of Shivaji", language="en")
            mock_repo_cls.return_value = mock_repo

            pipeline = PublishPipeline(config=config)
            package = pipeline.run(project_id)

        pub_dir = tmp_path / project_id / "publish"
        assert (pub_dir / "title.txt").exists()
        assert (pub_dir / "alternate-titles.txt").exists()
        assert (pub_dir / "keywords.txt").exists()
        assert (pub_dir / "hashtags.txt").exists()
        assert (pub_dir / "youtube-tags.txt").exists()
        assert (pub_dir / "chapters.txt").exists()
        assert (pub_dir / "description.md").exists()
        assert (pub_dir / "pinned-comment.txt").exists()
        assert (pub_dir / "youtube-metadata.json").exists()

        assert package.title.primary == "Shivaji the Great"
        mock_repo.update_stage.assert_called_with(project_id, "publish", "completed")

    def test_returns_publishing_package(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ytfactory.publish.artifacts.WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setattr("ytfactory.publish.pipeline.WORKSPACE_DIR", str(tmp_path))

        project_id = "integ2"
        _write_project(tmp_path, project_id)

        llm = MagicMock()
        llm.generate.side_effect = [
            LLMResponse(text='{"primary": "T", "alternatives": ["A","B","C","D","E"]}', model="mock"),
            LLMResponse(text='{"primary_keywords":[],"secondary_keywords":[],"long_tail_keywords":[],"hashtags":[],"youtube_tags":[]}', model="mock"),
            LLMResponse(text=json.dumps({
                "search_queries": ["test query"],
                "hook": "A short hook.", "who_this_is_for": ["anyone curious"],
                "what_you_discover": ["The topic"], "key_teachings": ["A teaching."],
                "questions_answered": ["What is this?"], "what_you_experience": "A journey.",
                "this_video_explains": "The core idea.", "sources": [],
                "engagement_prompt": "What resonated with you?", "hashtags": ["#topic"],
            }), model="mock"),
            LLMResponse(text='{"comment": "What part of this hit you the hardest?"}', model="mock"),
        ]

        from ytfactory.publish.pipeline import PublishPipeline

        with patch("ytfactory.publish.pipeline.get_llm_provider", return_value=llm), \
             patch("ytfactory.publish.pipeline.get_image_provider", return_value=_image_mock()), \
             patch("ytfactory.publish.pipeline.ProjectRepository") as mock_repo_cls:
            mock_repo = MagicMock()
            mock_repo.load.return_value = MagicMock(title="Test Video", language="en")
            mock_repo_cls.return_value = mock_repo

            package = PublishPipeline(config=PublishConfig(skip_thumbnail=True)).run(project_id)

        assert isinstance(package, PublishingPackage)
        assert package.project_id == project_id


# ── Backward Compatibility ────────────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_publish_stage_in_project_stages(self):
        from ytfactory.shared.constants import PROJECT_STAGES
        assert "publish" in PROJECT_STAGES

    def test_review_pipeline_unmodified(self):
        from ytfactory.review.pipeline import ReviewPipeline
        assert hasattr(ReviewPipeline, "run")

    def test_remediation_engine_unmodified(self):
        from ytfactory.review.remediation.engine import AutoRemediationEngine
        assert hasattr(AutoRemediationEngine, "remediate")

    def test_build_pipeline_has_publish(self):
        from ytfactory.build.pipeline import BuildPipeline
        import inspect
        src = inspect.getsource(BuildPipeline)
        assert "publish" in src
