"""Scene Bible Validator — validates a SceneBibleExtension before prompt generation.

Runs before ImagePromptEngineV4.build_prompt(). Invalid Bible-enabled scenes
must not reach image generation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .character_bible import CharacterBible, CharacterPresence
from .environment_bible import EnvironmentBible
from .scene_bible_extension import SceneBibleExtension


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str]
    warnings: list[str]

    def __bool__(self) -> bool:
        return self.passed


# Appearance-signal words that must not appear in character action fields.
# Appearance belongs exclusively to CharacterBible — not to scene actions.
_APPEARANCE_TERMS: frozenset[str] = frozenset(
    {
        "hair",
        "beard",
        "mustache",
        "moustache",
        "facial hair",
        "complexion",
        "skin",
        "eyes",
        "eye color",
        "wearing",
        "dressed in",
        "clothing",
        "shirt",
        "trousers",
        "tunic",
        "cloak",
        "mantle",
        "shawl",
        "sandals",
        "boots",
        "tall",
        "short",
        "lean",
        "slim",
        "muscular",
        "heavyset",
        "aged",
        "old",
        "young",
        "elderly",
        "handsome",
        "beautiful",
        "blond",
        "blonde",
        "brunette",
        "gray-haired",
        "grey-haired",
    }
)

# Named character terms that must not appear in anonymous_human_description.
_NAMED_TERMS: frozenset[str] = frozenset(
    {"kai", "socrates", "young husband", "wife"}
)


class SceneBibleValidator:
    def __init__(
        self,
        bible: CharacterBible,
        environment_bible: EnvironmentBible | None = None,
    ):
        self.bible = bible
        self.environment_bible = environment_bible

    def validate(
        self, scene_id: str, ext: SceneBibleExtension
    ) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Required fields
        if ext.temporal_mode is None:
            errors.append(f"[{scene_id}] temporal_mode is required.")

        if ext.character_presence is None:
            errors.append(f"[{scene_id}] character_presence is required.")

        if ext.animal_presence is None:
            errors.append(f"[{scene_id}] animal_presence is required.")

        if ext.environment_id is None:
            errors.append(f"[{scene_id}] environment_id is required.")
        elif self.environment_bible is not None:
            if not self.environment_bible.has(ext.environment_id):
                errors.append(
                    f"[{scene_id}] Unknown environment_id '{ext.environment_id}'."
                )

        # 2. Character presence is a HARD state machine
        if ext.character_presence == CharacterPresence.NONE:
            if ext.allowed_character_ids:
                errors.append(
                    f"[{scene_id}] character_presence=NONE requires "
                    f"allowed_character_ids=[]"
                )
            if ext.characters:
                errors.append(
                    f"[{scene_id}] character_presence=NONE requires characters=[]"
                )
        elif ext.character_presence in {
            CharacterPresence.PRIMARY,
            CharacterPresence.BACKGROUND,
            CharacterPresence.SYMBOLIC,
        }:
            if not ext.characters:
                errors.append(
                    f"[{scene_id}] character_presence="
                    f"{ext.character_presence.value} requires at least one characters[] entry."
                )

        # 3. Named character IDs
        for cid in ext.allowed_character_ids:
            try:
                self.bible.get(cid)
            except KeyError:
                errors.append(f"[{scene_id}] Unknown character ID '{cid}'.")

        for sc in ext.characters:
            if sc.character_id not in ext.allowed_character_ids:
                errors.append(
                    f"[{scene_id}] '{sc.character_id}' appears in characters[] "
                    f"but not in allowed_character_ids."
                )

        overlap = set(ext.allowed_character_ids) & set(ext.forbidden_character_ids)
        if overlap:
            errors.append(
                f"[{scene_id}] IDs cannot be both allowed and forbidden: "
                f"{sorted(overlap)}"
            )

        # 4. Independent anonymous-human control
        if ext.anonymous_humans_allowed and not ext.anonymous_human_description:
            errors.append(
                f"[{scene_id}] anonymous_humans_allowed=true requires "
                f"anonymous_human_description."
            )

        if (
            ext.character_presence == CharacterPresence.NONE
            and ext.anonymous_humans_allowed
        ):
            errors.append(
                f"[{scene_id}] character_presence=NONE cannot allow anonymous humans."
            )

        # 5. Appearance prose is forbidden in character actions
        for sc in ext.characters:
            action_lower = sc.action.lower()
            matched = sorted(
                term for term in _APPEARANCE_TERMS if term in action_lower
            )
            if matched:
                errors.append(
                    f"[{scene_id}] Character '{sc.character_id}' action contains "
                    f"appearance prose: {matched}. "
                    f"Appearance belongs exclusively in CharacterBible."
                )

        # 6. Anonymous-human descriptions must not redefine named identities
        if ext.anonymous_human_description:
            desc_lower = ext.anonymous_human_description.lower()
            matched = sorted(term for term in _NAMED_TERMS if term in desc_lower)
            if matched:
                errors.append(
                    f"[{scene_id}] anonymous_human_description references "
                    f"named character identities: {matched}."
                )

        # 7. Temporal/environment compatibility (data-driven, not hardcoded)
        if (
            ext.temporal_mode is not None
            and ext.environment_id is not None
            and self.environment_bible is not None
            and self.environment_bible.has(ext.environment_id)
        ):
            env = self.environment_bible.get(ext.environment_id)
            if not env.is_compatible_with(ext.temporal_mode):
                errors.append(
                    f"[{scene_id}] temporal_mode='{ext.temporal_mode.value}' is "
                    f"incompatible with environment_id='{ext.environment_id}'."
                )

        return ValidationResult(
            passed=not errors,
            errors=errors,
            warnings=warnings,
        )
