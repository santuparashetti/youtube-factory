"""Tests for the Kai anchor-character name firewall (KAI_ANCHOR_CHARACTER_SPEC.md)."""

from __future__ import annotations

import pytest

from ytfactory.validators.kai_firewall import (
    KaiFirewallViolation,
    check_artifact,
    check_file,
)


class TestKaiFirewall:
    def test_raises_on_violation(self):
        with pytest.raises(KaiFirewallViolation):
            check_artifact("Kai sat at the window, waiting.", "test_script.md")

    @pytest.mark.parametrize("variant", ["kai", "Kai", "KAI", "kAi"])
    def test_case_insensitive(self, variant):
        with pytest.raises(KaiFirewallViolation):
            check_artifact(f"The man named {variant} looked up.", "test_script.md")

    def test_passes_clean_text(self):
        # No exception raised — clean text passes.
        check_artifact("A man sat at the window, quietly watching.", "test_script.md")

    def test_word_boundary_avoids_false_positive(self):
        # "kaiser", "kayak", "kaimana" contain the letters but not the word "kai".
        check_artifact("The kaiser sailed past in a kayak.", "test_script.md")

    def test_violation_message_names_artifact_and_count(self):
        with pytest.raises(KaiFirewallViolation, match="my_script.md"):
            check_artifact("Kai and Kai again.", "my_script.md")

    def test_check_file_missing_path_is_noop(self, tmp_path):
        # Non-existent file: no read, no exception.
        check_file(tmp_path / "does-not-exist.srt")

    def test_check_file_flags_dirty_file(self, tmp_path):
        p = tmp_path / "subtitles.srt"
        p.write_text("1\n00:00:01,000 --> 00:00:02,000\nKai looked up.\n", encoding="utf-8")
        with pytest.raises(KaiFirewallViolation):
            check_file(p)

    def test_check_file_passes_clean_file(self, tmp_path):
        p = tmp_path / "subtitles.srt"
        p.write_text("1\n00:00:01,000 --> 00:00:02,000\nA man looked up.\n", encoding="utf-8")
        check_file(p)
