"""File-system paths for Publishing & Growth Engine V1 outputs."""

from __future__ import annotations

from pathlib import Path

from ytfactory.shared.constants import WORKSPACE_DIR


def publish_directory(project_id: str) -> Path:
    """Return (and create) workspace/jobs/<project_id>/publish/."""
    directory = Path(WORKSPACE_DIR) / project_id / "publish"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def thumbnail_variants_directory(project_id: str) -> Path:
    """Return (and create) workspace/jobs/<project_id>/publish/thumbnail-variants/."""
    directory = publish_directory(project_id) / "thumbnail-variants"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def thumbnail_path(project_id: str) -> Path:
    return publish_directory(project_id) / "thumbnail.png"


def title_path(project_id: str) -> Path:
    return publish_directory(project_id) / "title.txt"


def alternate_titles_path(project_id: str) -> Path:
    return publish_directory(project_id) / "alternate-titles.txt"


def description_path(project_id: str) -> Path:
    return publish_directory(project_id) / "description.md"


def keywords_path(project_id: str) -> Path:
    return publish_directory(project_id) / "keywords.txt"


def hashtags_path(project_id: str) -> Path:
    return publish_directory(project_id) / "hashtags.txt"


def youtube_tags_path(project_id: str) -> Path:
    return publish_directory(project_id) / "youtube-tags.txt"


def chapters_path(project_id: str) -> Path:
    return publish_directory(project_id) / "chapters.txt"


def pinned_comment_path(project_id: str) -> Path:
    return publish_directory(project_id) / "pinned-comment.txt"


def youtube_metadata_path(project_id: str) -> Path:
    return publish_directory(project_id) / "youtube-metadata.json"
