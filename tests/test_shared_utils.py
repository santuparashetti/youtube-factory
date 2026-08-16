"""Tests for ytfactory.shared.script_utils and ytfactory.shared.religion_agnostic."""

from ytfactory.shared.religion_agnostic import check as ra_check
from ytfactory.shared.script_utils import strip_script_heading, strip_tts_directives


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


# ── strip_tts_directives ──────────────────────────────────────────────────────

class TestStripTtsDirectives:
    def test_strips_visual_directive(self):
        text = "A tiny ant.\n\n[Visual: A tiny ant crawls across a massive rock.]\n\nThe ant moves on."
        result = strip_tts_directives(text)
        assert "[Visual:" not in result
        assert "A tiny ant." in result
        assert "The ant moves on." in result

    def test_strips_engagement_directive(self):
        text = "Stay with this.\n\n[ENGAGEMENT: value_promise]\n\nHere is why."
        result = strip_tts_directives(text)
        assert "[ENGAGEMENT:" not in result
        assert "Stay with this." in result
        assert "Here is why." in result

    def test_strips_narrative_ending(self):
        text = "Remember the ant.\n\n[NARRATIVE_ENDING]\n\nStart measuring by ground."
        result = strip_tts_directives(text)
        assert "[NARRATIVE_ENDING]" not in result
        assert "Remember the ant." in result

    def test_strips_text_overlay(self):
        text = "Most people fail.\n\n[Text Overlay on Screen: **CONSISTENCY > CAPACITY**]\n\nWe mistake greatness."
        result = strip_tts_directives(text)
        assert "[Text Overlay" not in result
        assert "Most people fail." in result
        assert "We mistake greatness." in result

    def test_strips_end_screen(self):
        text = "Subscribe to Atma Theory.\n\n[End Screen: Related video suggestions and Subscribe button graphic]"
        result = strip_tts_directives(text)
        assert "[End Screen:" not in result
        assert "Subscribe to Atma Theory." in result

    def test_preserves_normal_punctuation(self):
        text = "First, **Dirghakala**: practice over a long period of time. Don't judge a goal.\n\n[ENGAGEMENT: comment_prompt]"
        result = strip_tts_directives(text)
        assert "**Dirghakala**:" in result
        assert "Don't judge a goal." in result
        assert "[ENGAGEMENT:" not in result

    def test_normalizes_whitespace_after_strip(self):
        text = "Para one.\n\n[ENGAGEMENT: x]\n\n\n\nPara two."
        result = strip_tts_directives(text)
        assert "\n\n\n" not in result
        assert "Para one." in result
        assert "Para two." in result

    def test_returns_stripped_text(self):
        text = "\n\nActual narration here.\n\n"
        assert strip_tts_directives(text) == "Actual narration here."

    def test_plain_narration_unchanged(self):
        text = "Mastery grows quietly, through work that rarely looks impressive in the moment."
        assert strip_tts_directives(text) == text

    def test_inline_visual_within_paragraph(self):
        text = "The ant [Visual: close-up] continues climbing without pause."
        result = strip_tts_directives(text)
        assert "[Visual:" not in result
        assert "The ant  continues climbing without pause." == result or "The ant" in result


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
