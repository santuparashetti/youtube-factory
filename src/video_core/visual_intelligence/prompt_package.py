from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class PromptPackage:
    """Structured output from the Prompt Builder.

    Future pipeline stages consume PromptPackage instead of raw prompt strings.
    """

    final_prompt: str
    negative_prompt: str | None = None
    visual_profile: str = ""
    prompt_fingerprint: str = ""
    metadata_snapshot: dict = field(default_factory=dict)
    assembly_report: dict | None = None
