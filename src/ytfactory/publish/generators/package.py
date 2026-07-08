"""UploadPackageGenerator — assembles youtube-metadata.json and validates outputs."""

from __future__ import annotations

import json

from ytfactory.publish.artifacts import (
    alternate_titles_path,
    chapters_path,
    description_path,
    hashtags_path,
    keywords_path,
    pinned_comment_path,
    publish_directory,
    thumbnail_path,
    title_path,
    youtube_metadata_path,
    youtube_tags_path,
)
from ytfactory.publish.models import (
    ChapterEntry,
    DescriptionResult,
    PinnedCommentResult,
    PublishingPackage,
    SEOResult,
    ThumbnailResult,
    TitleResult,
)


class UploadPackageGenerator:
    """Assembles all sub-results into youtube-metadata.json and returns PublishingPackage."""

    def generate(
        self,
        project_id: str,
        timestamp: str,
        title: TitleResult,
        seo: SEOResult,
        description: DescriptionResult,
        chapters: list[ChapterEntry],
        thumbnail: ThumbnailResult | None,
        pinned_comment: PinnedCommentResult | None = None,
    ) -> PublishingPackage:
        errors: list[str] = []
        warnings: list[str] = []

        if not title.length_valid:
            errors.append(
                f"Title exceeds YouTube limit ({len(title.primary)} chars > 100)"
            )
        if title.length_warning:
            warnings.append(f"Title is long ({len(title.primary)} chars); optimal ≤ 70")
        if not description.has_cta:
            warnings.append(
                "Description missing call-to-action (subscribe/like/comment)"
            )
        if not description.has_chapters:
            warnings.append("Description missing chapters block")
        if thumbnail is None:
            warnings.append(
                "No thumbnail generated (skip_thumbnail=True or provider error)"
            )

        if pinned_comment and not pinned_comment.has_question:
            warnings.append("Pinned comment does not contain a question — engagement may be lower")

        output_dir = publish_directory(project_id)
        package = PublishingPackage(
            project_id=project_id,
            timestamp=timestamp,
            title=title,
            seo=seo,
            description=description,
            chapters=chapters,
            thumbnail=thumbnail,
            pinned_comment=pinned_comment,
            output_dir=output_dir,
            validation_errors=errors,
            validation_warnings=warnings,
            is_valid=len(errors) == 0,
        )

        metadata = {
            "version": "v1",
            "project_id": package.project_id,
            "timestamp": package.timestamp,
            "is_valid": package.is_valid,
            "validation_errors": package.validation_errors,
            "validation_warnings": package.validation_warnings,
            "title": package.title.to_dict(),
            "seo": package.seo.to_dict(),
            "description": package.description.to_dict(),
            "chapters": [c.to_dict() for c in package.chapters],
            "thumbnail": package.thumbnail.to_dict() if package.thumbnail else None,
            "pinned_comment": package.pinned_comment.to_dict() if package.pinned_comment else None,
            "output_files": {
                "title": str(title_path(project_id)),
                "alternate_titles": str(alternate_titles_path(project_id)),
                "description": str(description_path(project_id)),
                "keywords": str(keywords_path(project_id)),
                "hashtags": str(hashtags_path(project_id)),
                "youtube_tags": str(youtube_tags_path(project_id)),
                "chapters": str(chapters_path(project_id)),
                "pinned_comment": str(pinned_comment_path(project_id)),
                "thumbnail": str(thumbnail_path(project_id))
                if package.thumbnail
                else None,
            },
        }
        youtube_metadata_path(project_id).write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )
        return package
