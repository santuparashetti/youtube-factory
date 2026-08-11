"""ActionConstraint — physically grounded action+object validation.

Provides build_action_constraints_block() for injection into visual prompts,
and extract_action_constraints() for pulling constraints from narration text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Physical constraint rules: (action_pattern, object_pattern) → constraint
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Rule:
    action_pattern: str     # regex for the action verb/phrase
    object_pattern: str     # regex for the object receiving the action
    constraint: str         # instruction to inject into the prompt
    bad_example: str = ""   # example of what NOT to show


_PHYSICAL_RULES: list[_Rule] = [
    # Pouring oil into a lamp — common "pour oil out" hallucination
    _Rule(
        action_pattern=r"\bpours?\s+(oil|fuel)\b",
        object_pattern=r"\b(lamp|lantern|flame|torch|wick)\b",
        constraint=(
            "POURING OIL INTO LAMP: Show the character tilting a vessel/flask DOWNWARD into the lamp's oil "
            "reservoir — NOT pouring onto the flame or wick. The lamp flame must not be touched."
        ),
        bad_example="pouring liquid over a flame",
    ),
    # Lighting a lamp / candle — must use external flame
    _Rule(
        action_pattern=r"\blights?\s+(?:(?:a|the|his|her|their)\s+)?(?:\w+\s+)?(lamp|lantern|candle|torch|wick)\b",
        object_pattern=r"",
        constraint=(
            "LIGHTING A LAMP: Show the character holding a small flame source (match, taper, or torch) "
            "to the wick. Never show the character blowing on a lamp to light it."
        ),
    ),
    # Writing on parchment/paper — must use correct tool
    _Rule(
        action_pattern=r"\bwrites?\b|\bscribes?\b|\binscribes?\b",
        object_pattern=r"\b(parchment|scroll|paper|stone|wall|tablet)\b",
        constraint=(
            "WRITING: Character must hold a period-appropriate writing tool (quill, reed, stylus, chisel) "
            "in contact with the surface. Do NOT show empty hands writing."
        ),
    ),
    # Carrying a heavy/large object
    _Rule(
        action_pattern=r"\bcarries?\b|\blifts?\b|\bholds?\b|\bbears?\b",
        object_pattern=r"\b(boulder|stone|rock|log|chest|body|corpse)\b",
        constraint=(
            "CARRYING HEAVY OBJECT: Show correct body mechanics — bent knees, arms under/around the object, "
            "realistic strain posture. Object weight must be plausible for a single person."
        ),
    ),
    # Sword / weapon combat
    _Rule(
        action_pattern=r"\b(strikes?|swings?|thrusts?|parries?|blocks?|wields?)\b",
        object_pattern=r"\b(sword|blade|spear|axe|weapon|knife|dagger)\b",
        constraint=(
            "WEAPON USE: Show two-handed or correct one-handed grip appropriate to the weapon. "
            "Blade edge must face the correct direction for the described action. "
            "No floating or impossible wrist angles."
        ),
    ),
    # Riding a horse
    _Rule(
        action_pattern=r"\brides?\b|\bridding\b|\bgallops?\b|\btrot\b",
        object_pattern=r"\b(horse|steed|stallion|mare|mount|camel|elephant)\b",
        constraint=(
            "RIDING ANIMAL: Rider must sit in saddle with legs on both sides, feet in stirrups if visible. "
            "Hands must hold reins. Do not show rider floating above the animal."
        ),
    ),
    # Drinking from a vessel
    _Rule(
        action_pattern=r"\bdrinks?\b|\bsips?\b|\bquaffs?\b",
        object_pattern=r"\b(cup|goblet|flask|vessel|bowl|mug|chalice|urn)\b",
        constraint=(
            "DRINKING: Show the vessel tilted toward the character's mouth with hand gripping the vessel. "
            "Liquid must be inside the vessel, not floating."
        ),
    ),
    # Reading / studying a text
    _Rule(
        action_pattern=r"\breads?\b|\bstudies?\b|\bscrutinizes?\b|\bpores? over\b",
        object_pattern=r"\b(scroll|book|text|parchment|manuscript|tablet|map)\b",
        constraint=(
            "READING: Character must hold the document open and at a readable angle. "
            "Eyes must be directed at the document. Do not show character holding a blank surface."
        ),
    ),
]


@dataclass
class ActionConstraint:
    """A detected action with its physical constraints."""

    action: str               # the detected action phrase
    obj: str                  # the detected object phrase
    constraint: str           # prompt instruction to inject
    bad_example: str = ""

    def to_prompt_block(self) -> str:
        lines = [f"ACTION CONSTRAINT ({self.action} + {self.obj}):"]
        lines.append(f"  {self.constraint}")
        if self.bad_example:
            lines.append(f"  BAD: do NOT show '{self.bad_example}'")
        return "\n".join(lines)


def extract_action_constraints(narration: str) -> list[ActionConstraint]:
    """Scan narration text and return all matching ActionConstraints."""
    constraints: list[ActionConstraint] = []
    text = (narration or "").lower()

    for rule in _PHYSICAL_RULES:
        action_m = re.search(rule.action_pattern, text)
        if not action_m:
            continue
        if rule.object_pattern:
            obj_m = re.search(rule.object_pattern, text)
            if not obj_m:
                continue
            obj_phrase = obj_m.group(0)
        else:
            obj_phrase = "(any)"
        constraints.append(ActionConstraint(
            action=action_m.group(0),
            obj=obj_phrase,
            constraint=rule.constraint,
            bad_example=rule.bad_example,
        ))
    return constraints


def build_action_constraints_block(narration: str) -> str:
    """Return a ready-to-inject prompt block for all action constraints in narration.

    Returns empty string when narration has no detectable physical actions.
    """
    constraints = extract_action_constraints(narration)
    if not constraints:
        return ""
    lines = ["PHYSICAL ACTION GROUNDING — follow exactly or the prompt fails QA:"]
    for c in constraints:
        lines.append(c.to_prompt_block())
    return "\n".join(lines)
