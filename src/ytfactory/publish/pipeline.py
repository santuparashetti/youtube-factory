"""PublishPipeline — Publishing & Growth Engine V1.

Produces an upload-ready YouTube package under workspace/jobs/<id>/publish/:
  thumbnail.png, thumbnail-variants/, title.txt, alternate-titles.txt,
  description.md, keywords.txt, hashtags.txt, youtube-tags.txt,
  chapters.txt, youtube-metadata.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ytfactory.config.settings import Settings
from ytfactory.providers.image.factory import get_image_provider
from video_core.providers.llm.factory import get_llm_provider
from ytfactory.publish.artifacts import publish_directory
from ytfactory.publish.config import PublishConfig
from ytfactory.publish.generators.chapters import ChaptersGenerator
from ytfactory.publish.generators.comment import PinnedCommentGenerator
from ytfactory.publish.generators.description import DescriptionGenerator
from ytfactory.publish.generators.package import UploadPackageGenerator
from ytfactory.publish.generators.seo import SEOGenerator
from ytfactory.publish.generators.thumbnail import ThumbnailGenerator
from ytfactory.publish.generators.title import TitleGenerator
from ytfactory.publish.models import PublishingPackage
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.storage.project_repository import ProjectRepository


def _load_scenes(project_id: str) -> list[dict]:
    scene_file = Path(WORKSPACE_DIR) / project_id / "scenes" / "scene-plan.json"
    return json.loads(scene_file.read_text(encoding="utf-8"))["scenes"]


def _load_script(project_id: str) -> str:
    script_file = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"
    if script_file.exists():
        return script_file.read_text(encoding="utf-8")
    return ""


class PublishPipeline:
    """Orchestrates the Publishing & Growth Engine V1."""

    def __init__(
        self, config: PublishConfig | None = None, settings: Settings | None = None
    ):
        self._config = config or PublishConfig()
        self._settings = settings or Settings()
        self._projects = ProjectRepository()
        self._llm = get_llm_provider(self._settings)
        self._image = get_image_provider(self._settings)

    def run(self, project_id: str) -> PublishingPackage:
        project = self._projects.load(project_id)
        project_dir = Path(WORKSPACE_DIR) / project_id
        publish_directory(project_id)  # ensure output dir exists

        print(f"\n── Publishing & Growth Engine V1 ─── project: {project_id}\n")

        scenes = _load_scenes(project_id)
        script = _load_script(project_id)
        script_excerpt = script[: self._config.script_excerpt_chars]
        scene_titles = [s.get("title", "") for s in scenes]
        first_visual = (
            scenes[0].get("visual_prompt", project.title) if scenes else project.title
        )

        # ── 1. Chapters ────────────────────────────────────────────────────
        print("  [1/7] Generating chapters…")
        chapters = ChaptersGenerator().generate(project_id, project_dir, scenes)

        # Build chapters block for description prompt
        chapters_lines = [f"{c.timestamp_str} {c.title}" for c in chapters]
        chapters_block = "\n".join(chapters_lines)

        # ── 2. Title ───────────────────────────────────────────────────────
        print("  [2/7] Generating title…")
        title = TitleGenerator(self._llm, self._config).generate(
            project_id=project_id,
            project_title=project.title,
            script_excerpt=script_excerpt,
            scene_titles=scene_titles,
        )

        # ── 3. SEO ─────────────────────────────────────────────────────────
        print("  [3/7] Generating SEO metadata…")
        seo = SEOGenerator(self._llm, self._config).generate(
            project_id=project_id,
            project_title=project.title,
            script_excerpt=script_excerpt,
            scene_titles=scene_titles,
        )

        # ── 4. Description ─────────────────────────────────────────────────
        print("  [4/7] Generating description…")
        description = DescriptionGenerator(self._llm, self._config).generate(
            project_id=project_id,
            project_title=project.title,
            script_excerpt=script_excerpt,
            chapters_block=chapters_block,
            seo_keywords=seo.all_keywords,
        )

        # ── 5. Pinned Comment ──────────────────────────────────────────────
        print("  [5/7] Generating pinned comment…")
        pinned_comment = PinnedCommentGenerator(self._llm, self._config).generate(
            project_id=project_id,
            project_title=project.title,
            script_excerpt=script_excerpt,
        )

        # ── 6. Thumbnail ───────────────────────────────────────────────────
        print("  [6/7] Generating thumbnail…")
        thumbnail = ThumbnailGenerator(self._image, self._config).generate(
            project_id=project_id,
            project_title=project.title,
            first_scene_visual_prompt=first_visual,
        )

        # ── 7. Package ─────────────────────────────────────────────────────
        print("  [7/7] Assembling youtube-metadata.json…")
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        package = UploadPackageGenerator().generate(
            project_id=project_id,
            timestamp=timestamp,
            title=title,
            seo=seo,
            description=description,
            chapters=chapters,
            thumbnail=thumbnail,
            pinned_comment=pinned_comment,
        )

        self._projects.update_stage(project_id, "publish", "completed")

        # ── Summary ────────────────────────────────────────────────────────
        status = "VALID" if package.is_valid else "INVALID"
        print(f"\n  ✔ Publishing complete — {status}")
        print(f"    Title   : {title.primary}")
        print(f"    Chapters: {len(chapters)}")
        print(f"    Tags    : {len(seo.youtube_tags)}")
        print(f"    Comment : {pinned_comment.text[:80]}…")
        print(f"    Errors  : {len(package.validation_errors)}")
        print(f"    Warnings: {len(package.validation_warnings)}")
        print(f"    Output  : {package.output_dir}\n")

        return package
