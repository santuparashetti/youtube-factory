"""Domain models for Publishing & Growth Engine V1."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChapterEntry:
    """A single chapter / timestamp entry."""

    index: int  # 1-based chapter number
    timestamp_seconds: float  # cumulative start time in seconds
    timestamp_str: str  # human-readable: "0:00", "1:23", "1:02:34"
    title: str  # chapter title (from scene title)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp_seconds": self.timestamp_seconds,
            "timestamp_str": self.timestamp_str,
            "title": self.title,
        }


@dataclass
class TitleResult:
    """Generated YouTube titles."""

    primary: str
    alternatives: list[str]  # exactly 5 alternatives
    length_valid: bool  # primary ≤ max_title_length
    length_warning: bool  # primary > optimal_title_length

    def to_dict(self) -> dict:
        return {
            "primary": self.primary,
            "alternatives": self.alternatives,
            "length_valid": self.length_valid,
            "length_warning": self.length_warning,
        }


@dataclass
class SEOResult:
    """Generated SEO metadata."""

    primary_keywords: list[str]
    secondary_keywords: list[str]
    long_tail_keywords: list[str]
    hashtags: list[str]  # with # prefix
    youtube_tags: list[str]  # comma-joined for YouTube upload
    total_tags_chars: int

    @property
    def all_keywords(self) -> list[str]:
        return self.primary_keywords + self.secondary_keywords + self.long_tail_keywords

    def to_dict(self) -> dict:
        return {
            "primary_keywords": self.primary_keywords,
            "secondary_keywords": self.secondary_keywords,
            "long_tail_keywords": self.long_tail_keywords,
            "hashtags": self.hashtags,
            "youtube_tags": self.youtube_tags,
            "total_tags_chars": self.total_tags_chars,
        }


@dataclass
class PinnedCommentResult:
    """Generated YouTube pinned comment."""

    text: str
    char_count: int
    has_question: bool

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "char_count": self.char_count,
            "has_question": self.has_question,
        }


@dataclass
class DescriptionResult:
    """Generated YouTube description."""

    full_text: str
    word_count: int
    has_chapters: bool
    has_cta: bool

    def to_dict(self) -> dict:
        return {
            "word_count": self.word_count,
            "has_chapters": self.has_chapters,
            "has_cta": self.has_cta,
        }


@dataclass
class ThumbnailResult:
    """Generated thumbnail(s)."""

    primary_path: Path
    variant_paths: list[Path]
    width: int
    height: int

    def to_dict(self) -> dict:
        return {
            "primary_path": str(self.primary_path),
            "variant_paths": [str(p) for p in self.variant_paths],
            "width": self.width,
            "height": self.height,
        }


@dataclass
class PublishingPackage:
    """Top-level result produced by PublishPipeline.run()."""

    project_id: str
    timestamp: str

    title: TitleResult
    seo: SEOResult
    description: DescriptionResult
    chapters: list[ChapterEntry] = field(default_factory=list)
    thumbnail: ThumbnailResult | None = None
    pinned_comment: PinnedCommentResult | None = None

    output_dir: Path = field(default_factory=lambda: Path("."))
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    is_valid: bool = True

    def to_dict(self) -> dict:
        return {
            "version": "v1",
            "project_id": self.project_id,
            "timestamp": self.timestamp,
            "is_valid": self.is_valid,
            "validation_errors": self.validation_errors,
            "validation_warnings": self.validation_warnings,
            "output_dir": str(self.output_dir),
            "title": self.title.to_dict(),
            "seo": self.seo.to_dict(),
            "description": self.description.to_dict(),
            "chapters": [c.to_dict() for c in self.chapters],
            "thumbnail": self.thumbnail.to_dict() if self.thumbnail else None,
            "pinned_comment": self.pinned_comment.to_dict() if self.pinned_comment else None,
        }
