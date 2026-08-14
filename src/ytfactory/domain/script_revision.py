"""Domain models for Atma Theory script refinement pipeline.

ScriptIdentity — extracted deterministically from the raw script before any
LLM refinement. Passed to AtmaRefinerPipeline as a protected constraint.

ScriptRevision — one node in the revision lineage. Tracks parent → child
relationships, reviewer decisions, and feedback.

ScriptValidationFlag / ScriptValidationResult — output of ScriptValidator
before human review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class RevisionStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ReviewDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"


class ValidationFlagType(str, Enum):
    FACTUAL_RISK = "factual_risk"
    WORD_COUNT = "word_count"
    BEAT_COVERAGE = "beat_coverage"
    THESIS_DRIFT = "thesis_drift"
    NARRATIVE_COHERENCE = "narrative_coherence"
    IDENTITY_DRIFT = "identity_drift"


@dataclass(slots=True)
class ScriptIdentity:
    """Deterministically extracted identity of the raw/base script.

    Extracted BEFORE any LLM refinement call. Passed as a protected
    constraint into the 7-Beat refinement so the editor cannot silently
    remove what matters most.

    All fields default to empty string/list so extraction is always safe
    even when the heuristics find nothing.
    """

    core_topic: str = ""
    core_thesis: str = ""
    emotional_promise: str = ""
    central_conflict: str = ""
    key_story: str = ""
    key_philosophical_insight: str = ""
    important_factual_details: list[str] = field(default_factory=list)
    intended_audience_takeaway: str = ""
    strong_original_ideas: list[str] = field(default_factory=list)
    important_visual_moments: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "core_topic": self.core_topic,
            "core_thesis": self.core_thesis,
            "emotional_promise": self.emotional_promise,
            "central_conflict": self.central_conflict,
            "key_story": self.key_story,
            "key_philosophical_insight": self.key_philosophical_insight,
            "important_factual_details": self.important_factual_details,
            "intended_audience_takeaway": self.intended_audience_takeaway,
            "strong_original_ideas": self.strong_original_ideas,
            "important_visual_moments": self.important_visual_moments,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScriptIdentity":
        return cls(
            core_topic=data.get("core_topic", ""),
            core_thesis=data.get("core_thesis", ""),
            emotional_promise=data.get("emotional_promise", ""),
            central_conflict=data.get("central_conflict", ""),
            key_story=data.get("key_story", ""),
            key_philosophical_insight=data.get("key_philosophical_insight", ""),
            important_factual_details=data.get("important_factual_details", []),
            intended_audience_takeaway=data.get("intended_audience_takeaway", ""),
            strong_original_ideas=data.get("strong_original_ideas", []),
            important_visual_moments=data.get("important_visual_moments", []),
        )


@dataclass
class ScriptRevision:
    """One revision in the script lineage.

    Stored in workspace/jobs/<id>/script/revisions.json alongside the
    actual revision text files (revision-1.md, revision-2.md, ...).
    """

    revision_id: str
    revision_number: int
    parent_id: Optional[str]
    status: RevisionStatus
    reviewer_decision: Optional[ReviewDecision]
    reviewer_feedback: Optional[str]
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    script_file: str = ""

    def to_dict(self) -> dict:
        return {
            "revision_id": self.revision_id,
            "revision_number": self.revision_number,
            "parent_id": self.parent_id,
            "status": self.status.value,
            "reviewer_decision": self.reviewer_decision.value
            if self.reviewer_decision
            else None,
            "reviewer_feedback": self.reviewer_feedback,
            "created_at": self.created_at,
            "script_file": self.script_file,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScriptRevision":
        return cls(
            revision_id=data["revision_id"],
            revision_number=data["revision_number"],
            parent_id=data.get("parent_id"),
            status=RevisionStatus(data.get("status", "pending")),
            reviewer_decision=(
                ReviewDecision(data["reviewer_decision"])
                if data.get("reviewer_decision")
                else None
            ),
            reviewer_feedback=data.get("reviewer_feedback"),
            created_at=data.get("created_at", ""),
            script_file=data.get("script_file", ""),
        )


@dataclass(slots=True)
class ValidationFlag:
    """A single validation issue found by ScriptValidator."""

    flag_type: ValidationFlagType
    location: str
    message: str
    severity: str  # "warning" | "error"
    auto_fixable: bool = False

    def to_dict(self) -> dict:
        return {
            "type": self.flag_type.value,
            "location": self.location,
            "message": self.message,
            "severity": self.severity,
            "auto_fixable": self.auto_fixable,
        }


@dataclass
class ScriptValidationResult:
    """Output of ScriptValidator before human review."""

    status: str  # "PASS" | "REVIEW_REQUIRED"
    spoken_word_count: int
    beat_coverage: dict  # {beat_name: bool}
    flags: list[ValidationFlag] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self.flags)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "spoken_word_count": self.spoken_word_count,
            "beat_coverage": self.beat_coverage,
            "flags": [f.to_dict() for f in self.flags],
        }
