"""Tests for SubtitleTypographer — display-facing punctuation repair."""

from __future__ import annotations

import pytest

from ytfactory.subtitles.typography import SubtitleTypographer


@pytest.fixture()
def typo() -> SubtitleTypographer:
    return SubtitleTypographer()


class TestPunctuationRepair:
    def test_comma_period_repaired(self, typo):
        result = typo.repair_punctuation("Hello,.world")
        assert ",." not in result

    def test_question_period_repaired(self, typo):
        result = typo.repair_punctuation("Really?. Yes.")
        assert "?." not in result

    def test_exclaim_period_repaired(self, typo):
        result = typo.repair_punctuation("Wow!. Great.")
        assert "!." not in result

    def test_four_periods_collapsed(self, typo):
        result = typo.repair_punctuation("Wait.... then")
        assert "...." not in result
        assert "..." in result

    def test_space_before_comma_removed(self, typo):
        result = typo.repair_punctuation("Hello , world")
        assert " ," not in result

    def test_three_periods_preserved(self, typo):
        result = typo.repair_punctuation("Waiting... for something")
        assert "..." in result


class TestQuoteNormalization:
    def test_smart_double_quotes(self, typo):
        result = typo.normalize_quotes("“hello”")
        assert "“" not in result
        assert "”" not in result
        assert "hello" in result

    def test_smart_single_quotes(self, typo):
        result = typo.normalize_quotes("‘world’")
        assert "‘" not in result
        assert "’" not in result

    def test_straight_quotes_preserved(self, typo):
        result = typo.normalize_quotes('"quoted"')
        assert '"quoted"' == result


class TestDashNormalization:
    def test_em_dash_replaced(self, typo):
        result = typo.normalize_dashes("one—two")
        assert "—" not in result
        assert " - " in result

    def test_en_dash_replaced(self, typo):
        result = typo.normalize_dashes("1–2")
        assert "–" not in result

    def test_regular_hyphen_preserved(self, typo):
        result = typo.normalize_dashes("self-aware")
        assert "self-aware" == result


class TestEllipsisNormalization:
    def test_unicode_ellipsis_replaced(self, typo):
        result = typo.normalize_ellipsis("wait…")
        assert "…" not in result
        assert "..." in result

    def test_ascii_ellipsis_preserved(self, typo):
        result = typo.normalize_ellipsis("wait...")
        assert "..." in result


class TestCapitalization:
    def test_first_letter_capitalized(self, typo):
        result = typo.capitalize_first("hello world")
        assert result[0] == "H"

    def test_already_capitalized_unchanged(self, typo):
        result = typo.capitalize_first("Hello world")
        assert result == "Hello world"

    def test_empty_string(self, typo):
        result = typo.capitalize_first("")
        assert result == ""


class TestFullClean:
    def test_all_repairs_applied(self, typo):
        raw = "“Wait…”,. Really?."
        result = typo.clean(raw)
        assert "“" not in result
        assert "”" not in result
        assert ",." not in result
        assert "?." not in result

    def test_empty_string_returned_unchanged(self, typo):
        assert typo.clean("") == ""

    def test_whitespace_only_returned_unchanged(self, typo):
        result = typo.clean("   ")
        assert result.strip() == ""

    def test_clean_lines_applies_to_each(self, typo):
        lines = ["hello,.world", "wait…"]
        result = typo.clean_lines(lines)
        assert ",." not in result[0]
        assert "…" not in result[1]

    def test_spaces_normalized(self, typo):
        result = typo.clean("word   word")
        assert "   " not in result
