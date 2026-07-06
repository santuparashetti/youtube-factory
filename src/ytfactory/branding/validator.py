"""Brand script validator.

Verifies that a generated script conforms to the Brand Template System rules:
  - Hook exists (non-empty opening)
  - Opening welcome appears exactly once, near the top
  - Closing signature appears exactly once, near the end
  - No branding interrupts the main teaching
  - CTA appears exactly once
  - Closing quote ends the video
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ytfactory.branding.config import BrandConfig, get_brand_config


@dataclass
class BrandValidationReport:
    """Result of a brand validation pass on a script."""

    valid: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines: list[str] = []
        if self.valid:
            lines.append("PASS — all branding rules satisfied")
        else:
            lines.append(f"FAIL — {len(self.issues)} issue(s)")
        for issue in self.issues:
            lines.append(f"  ✗ {issue}")
        for warning in self.warnings:
            lines.append(f"  ⚠ {warning}")
        return "\n".join(lines)


class BrandValidator:
    """Validate that a script satisfies the Brand Template System placement rules."""

    # Fraction of script where opening welcome must appear (0.0–opening_cutoff).
    _OPENING_CUTOFF = 0.30

    # Fraction of script where closing content must appear (closing_cutoff–1.0).
    _CLOSING_CUTOFF = 0.55

    def validate(
        self,
        script: str,
        config: BrandConfig | None = None,
    ) -> BrandValidationReport:
        """Run all brand placement checks on *script*."""
        cfg = config or get_brand_config()
        issues: list[str] = []
        warnings: list[str] = []

        if not script or not script.strip():
            return BrandValidationReport(
                valid=False,
                issues=["Script is empty."],
            )

        script_lower = script.lower()
        total_chars = len(script_lower)

        # ── 1. Hook exists ──────────────────────────────────────────────────
        words = script.split()
        if len(words) < 10:
            issues.append(
                "Script is too short to contain a proper hook "
                f"({len(words)} words — minimum 10 expected)."
            )

        # ── 2. Opening welcome — enabled, appears once, near the top ───────
        if cfg.opening.enabled:
            opening_key = cfg.opening.text().lower()
            if opening_key:
                match_key = opening_key[:40]
                positions = _find_all(script_lower, match_key)
                if not positions:
                    issues.append(
                        f"Opening welcome not found. Expected text starting with: "
                        f'"{cfg.opening.text()[:60]}..."'
                    )
                elif len(positions) > 1:
                    issues.append(
                        f"Opening welcome appears {len(positions)} times. "
                        "It must appear exactly once."
                    )
                else:
                    pct = positions[0] / total_chars
                    if pct > self._OPENING_CUTOFF:
                        issues.append(
                            "Opening welcome appears too late "
                            f"({pct:.0%} into the script — must be in the first "
                            f"{self._OPENING_CUTOFF:.0%}). "
                            "It must follow immediately after the hook."
                        )

        # ── 3. Closing signature — enabled, appears once, near the end ──────
        if cfg.signature.enabled:
            sig_key = cfg.signature.text().lower()
            if sig_key:
                match_key = sig_key[:30]
                positions = _find_all(script_lower, match_key)
                if not positions:
                    warnings.append(
                        f"Closing signature not found. Expected text starting with: "
                        f'"{cfg.signature.text()[:60]}..."'
                    )
                elif len(positions) > 1:
                    issues.append(
                        f"Closing signature appears {len(positions)} times. "
                        "It must appear exactly once."
                    )
                else:
                    pct = positions[0] / total_chars
                    if pct < self._CLOSING_CUTOFF:
                        issues.append(
                            "Closing signature appears too early "
                            f"({pct:.0%} into the script — must be in the last "
                            f"{1 - self._CLOSING_CUTOFF:.0%}). "
                            "Branding must not interrupt the main teaching."
                        )

        # ── 4. Closing statement — enabled, near the end ────────────────────
        if cfg.closing.enabled:
            closing_text = cfg.closing.text().lower()
            if closing_text:
                match_key = closing_text[:25]
                positions = _find_all(script_lower, match_key)
                if positions:
                    pct = positions[0] / total_chars
                    if pct < self._CLOSING_CUTOFF:
                        issues.append(
                            "Closing statement appears too early "
                            f"({pct:.0%} into the script). "
                            "Branding must not interrupt the main teaching."
                        )

        # ── 5. CTA appears once (if enabled) ────────────────────────────────
        if cfg.cta.enabled:
            cta_text = cfg.cta.text().lower()
            if cta_text:
                match_key = cta_text[:30]
                positions = _find_all(script_lower, match_key)
                if not positions:
                    warnings.append("Call to action not found in script.")
                elif len(positions) > 1:
                    issues.append(
                        f"Call to action appears {len(positions)} times. "
                        "It must appear exactly once."
                    )

        # ── 5b. Brand assertion must come before CTA ────────────────────────
        if cfg.closing.enabled and cfg.cta.enabled:
            closing_text = cfg.closing.text().lower()
            cta_text = cfg.cta.text().lower()
            if closing_text and cta_text:
                closing_pos = script_lower.rfind(closing_text[:25])
                cta_pos = script_lower.rfind(cta_text[:30])
                if closing_pos >= 0 and cta_pos >= 0 and closing_pos > cta_pos:
                    issues.append(
                        "Brand signature assertion must come before the CTA, not after it. "
                        "Script structure: ... → Reflection → Brand Signature → CTA → Closing Quote."
                    )

        # ── 6. Closing quote ends the video — sig must be last brand element ─
        if cfg.signature.enabled and cfg.cta.enabled:
            sig_text = cfg.signature.text().lower()
            cta_text = cfg.cta.text().lower()
            if sig_text and cta_text:
                sig_pos = script_lower.rfind(sig_text[:30])
                cta_pos = script_lower.rfind(cta_text[:30])
                if sig_pos >= 0 and cta_pos >= 0 and sig_pos < cta_pos:
                    issues.append(
                        "Closing signature must come after the CTA, not before it. "
                        "Script structure: ... → CTA → Closing Signature."
                    )

        return BrandValidationReport(
            valid=len(issues) == 0,
            issues=issues,
            warnings=warnings,
        )


# -- Helpers -------------------------------------------------------------------


def _find_all(text: str, substring: str) -> list[int]:
    """Return start positions of all non-overlapping occurrences of *substring*."""
    positions: list[int] = []
    start = 0
    while True:
        idx = text.find(substring, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + len(substring)
    return positions
