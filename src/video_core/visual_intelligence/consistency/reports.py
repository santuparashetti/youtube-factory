"""Consistency reports — JSON and Markdown exports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_core.visual_intelligence.consistency.scene_memory import SceneMemory


def generate_consistency_report(
    memory: SceneMemory,
    output_path: Path,
    fmt: str = "json",
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    entries = memory.all_entries()
    recurring: dict[str, int] = {}
    for entry in entries:
        for identity_id in entry.identities_used:
            recurring[identity_id] = recurring.get(identity_id, 0) + 1
    recurring_list = [{"identity_id": k, "appearances": v} for k, v in sorted(recurring.items(), key=lambda x: x[1], reverse=True)]
    report: dict[str, Any] = {
        "total_scenes": len(entries),
        "recurring_identities": recurring_list,
        "entries": [
            {
                "scene_id": e.scene_id,
                "video_id": e.video_id,
                "identities": e.identities_used,
                "prompt_fingerprint": e.prompt_fingerprint,
                "regeneration_count": e.regeneration_count,
            }
            for e in entries
        ],
    }
    if fmt == "json":
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    elif fmt == "markdown":
        lines = ["# Consistency Report", ""]
        lines.append(f"Total scenes: {len(entries)}")
        lines.append("")
        lines.append("## Recurring Identities")
        lines.append("")
        for item in report["recurring_identities"]:
            lines.append(f"- {item.get('identity_id', '?')}: {item.get('appearances', 0)} appearances")
        output_path.write_text("\n".join(lines), encoding="utf-8")
    else:
        raise ValueError(f"Unsupported format: {fmt}")
