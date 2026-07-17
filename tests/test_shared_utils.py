"""Tests for ytfactory.shared.script_utils and ytfactory.shared.religion_agnostic."""

from ytfactory.shared.religion_agnostic import check as ra_check
from ytfactory.shared.script_utils import strip_script_heading


# ── strip_script_heading ───────────────────────────────────────────────────────

class TestStripScriptHeading:
    def test_strips_leading_h1(self):
        text = "# WHEN SUFFERING KNOCKS\n\nHere's a question..."
        body, heading = strip_script_heading(text)
        assert heading == "WHEN SUFFERING KNOCKS"
        assert body.startswith("Here's a question...")
        assert "#" not in body.splitlines()[0]

    def test_returns_empty_heading_when_no_h1(self):
        text = "Here's a question that stops people cold."
        body, heading = strip_script_heading(text)
        assert heading == ""
        assert body == text

    def test_handles_h1_with_multiple_spaces(self):
        text = "#  MY TITLE\n\nContent."
        body, heading = strip_script_heading(text)
        assert heading == "MY TITLE"
        assert body.startswith("Content.")

    def test_ignores_h1_not_at_start(self):
        text = "Opening line.\n\n# Not The Title\n\nMore content."
        body, heading = strip_script_heading(text)
        assert heading == ""
        assert body == text

    def test_strips_leading_blank_lines_before_h1(self):
        text = "\n\n# TITLE\n\nContent."
        body, heading = strip_script_heading(text)
        assert heading == "TITLE"
        assert body.startswith("Content.")

    def test_body_has_no_leading_blank_line(self):
        text = "# TITLE\n\nParagraph one."
        body, _ = strip_script_heading(text)
        assert not body.startswith("\n")
        assert body.startswith("Paragraph one.")


# ── religion_agnostic.check ───────────────────────────────────────────────────

class TestReligionAgnosticCheck:
    def test_clean_text_returns_empty(self):
        text = "Ancient wisdom teaches us to face difficulty with equanimity."
        assert ra_check(text) == []

    def test_flags_vedanta(self):
        text = "The philosophy of Vedanta has much to teach us."
        warnings = ra_check(text)
        assert any("Vedanta" in w for w in warnings)

    def test_flags_bhagavad_gita(self):
        text = "As the Bhagavad Gita teaches, duty must be fulfilled."
        warnings = ra_check(text)
        assert any("Bhagavad" in w or "Gita" in w for w in warnings)

    def test_flags_gita_alone(self):
        text = "As the Gita says, act without attachment to results."
        warnings = ra_check(text)
        assert any("Gita" in w for w in warnings)

    def test_flags_upanishads(self):
        text = "The Upanishads describe the nature of Brahman."
        warnings = ra_check(text)
        assert any("Upanishad" in w for w in warnings)

    def test_flags_hindu(self):
        text = "In Hindu philosophy, the concept of dharma is central."
        warnings = ra_check(text)
        assert any("Hindu" in w for w in warnings)

    def test_flags_sanskrit_label(self):
        text = "The Sanskrit term for this is Dukkha, meaning suffering."
        warnings = ra_check(text)
        assert any("Sanskrit" in w for w in warnings)

    def test_named_teacher_not_flagged(self):
        text = "Adi Shankaracharya taught that the self is unchanging."
        warnings = ra_check(text)
        assert warnings == []

    def test_warning_includes_context_excerpt(self):
        text = "According to Vedanta, the self is eternal and unchanging."
        warnings = ra_check(text)
        assert len(warnings) >= 1
        assert "Vedanta" in warnings[0]
        assert "context:" in warnings[0]

    def test_flags_advaita(self):
        text = "Advaita teaches non-duality as the nature of reality."
        warnings = ra_check(text)
        assert any("Advaita" in w for w in warnings)

    def test_case_insensitive(self):
        text = "vedanta and the gita inform this perspective."
        warnings = ra_check(text)
        assert any("Vedanta" in w or "vedanta" in w.lower() for w in warnings)
        assert any("Gita" in w or "gita" in w.lower() for w in warnings)
