"""Capability contract validation for Model Bundles.

Providers declare capabilities in the registry.
Consumers declare required capabilities.
The LAMM validates that the selected bundle satisfies those capabilities
before marking it READY.

Missing capabilities return MISSING_CAPABILITY(capability_name) formatted
strings rather than raising exceptions — callers decide how to handle gaps.
"""

from __future__ import annotations


def validate_capabilities(
    declared: list[str],
    required: list[str],
) -> list[str]:
    """Return a list of required capabilities not declared by the model.

    An empty return value means all required capabilities are satisfied.

    Parameters
    ----------
    declared:
        Capabilities declared in the model registry entry.
    required:
        Capabilities required by the caller (e.g. ReviewPipeline).
    """
    declared_set = set(declared)
    return [cap for cap in required if cap not in declared_set]


def format_missing(missing: list[str]) -> str:
    """Format missing capabilities as the spec's error strings."""
    return ", ".join(f"MISSING_CAPABILITY({cap})" for cap in missing)


def capability_error_message(model_name: str, missing: list[str]) -> str:
    """Build a human-readable error message for a capability validation failure."""
    formatted = format_missing(missing)
    return (
        f"Model '{model_name}' does not satisfy required capabilities: {formatted}"
    )
