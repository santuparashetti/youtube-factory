"""Tests for the Script Selector + Polisher node and the composer two-variant
output that feeds it. No real API calls — the LLM is always mocked."""

from __future__ import annotations

import json

import pytest

from video_core.domain.llm import LLMResponse
from ytfactory.agents.nodes import script_selector_polisher as ssp
from ytfactory.agents.nodes.script_selector_polisher import (
    script_selector_polisher_node,
)


class _FakeLLM:
    """Returns a canned response and records the call for assertions."""

    def __init__(self, text: str):
        self._text = text
        self.calls: list[dict] = []

    def generate(self, prompt, *, system_prompt=None, temperature=0.2,
                 json_mode=False, json_schema=None):
        self.calls.append(
            {"prompt": prompt, "system_prompt": system_prompt,
             "temperature": temperature, "json_mode": json_mode}
        )
        return LLMResponse(
            text=self._text, model="fake", prompt_tokens=123,
            completion_tokens=45, total_tokens=168,
        )


@pytest.fixture
def patch_workspace(tmp_path, monkeypatch):
    """Redirect the node's disk write into a temp dir."""
    monkeypatch.setattr(ssp, "WORKSPACE_DIR", str(tmp_path))
    return tmp_path


def _install_llm(monkeypatch, text: str) -> _FakeLLM:
    fake = _FakeLLM(text)
    monkeypatch.setattr(ssp, "_get_polisher_llm", lambda settings: fake)
    return fake


def _state():
    return {
        "project_id": "test-proj",
        "script_a": "AAAA short variant a",
        "script_b": "BBBB a noticeably longer variant b with more words in it",
    }


def test_valid_json_parsed_correctly(patch_workspace, monkeypatch):
    payload = {
        "chosen": "B",
        "selection_reason": "B has a stronger hook and a cleaner close.",
        "changes_made": ["Tightened sentence 3 — it dragged."],
        "change_percentage": 7,
        "unchanged_note": "Structure and voice preserved.",
        "final_script": "The polished final script text.",
    }
    fake = _install_llm(monkeypatch, json.dumps(payload))

    result = script_selector_polisher_node(_state())

    assert result["selected_script"] == "The polished final script text."
    assert result["script_md"] == "The polished final script text."  # shim
    report = result["polisher_report"]
    assert report["chosen"] == "B"
    assert report["change_percentage"] == 7
    assert "fallback" not in report
    # LLM was asked for JSON at the configured (low) polish temperature.
    assert fake.calls[0]["json_mode"] is True
    assert fake.calls[0]["system_prompt"] == ssp.SYSTEM_PROMPT
    # Disk shim wrote the selected script.
    written = (patch_workspace / "test-proj" / "script" / "script.md").read_text()
    assert written == "The polished final script text."


def test_fallback_triggers_on_malformed_json(patch_workspace, monkeypatch):
    _install_llm(monkeypatch, "this is not JSON at all — the model rambled")

    result = script_selector_polisher_node(_state())

    report = result["polisher_report"]
    assert report["fallback"] is True
    assert report["change_percentage"] == 0
    # Length heuristic → the longer variant (B) wins.
    assert result["selected_script"] == _state()["script_b"]
    assert report["chosen"] == "B"


def test_fallback_on_empty_final_script(patch_workspace, monkeypatch):
    payload = {
        "chosen": "A", "selection_reason": "x", "changes_made": [],
        "change_percentage": 3, "unchanged_note": "y", "final_script": "   ",
    }
    _install_llm(monkeypatch, json.dumps(payload))

    result = script_selector_polisher_node(_state())
    assert result["polisher_report"]["fallback"] is True


def test_change_percentage_is_int(patch_workspace, monkeypatch):
    # Model returns the percentage as a string / float — node must coerce to int.
    payload = {
        "chosen": "A", "selection_reason": "x",
        "changes_made": [], "change_percentage": "9",
        "unchanged_note": "y", "final_script": "final.",
    }
    _install_llm(monkeypatch, json.dumps(payload))

    result = script_selector_polisher_node(_state())
    pct = result["polisher_report"]["change_percentage"]
    assert isinstance(pct, int)
    assert pct == 9


def test_selected_script_non_empty_string(patch_workspace, monkeypatch):
    payload = {
        "chosen": "A", "selection_reason": "x", "changes_made": [],
        "change_percentage": 0, "unchanged_note": "y",
        "final_script": "A real polished script.",
    }
    _install_llm(monkeypatch, json.dumps(payload))

    result = script_selector_polisher_node(_state())
    assert isinstance(result["selected_script"], str)
    assert result["selected_script"].strip()


def test_json_in_code_fence_is_parsed(patch_workspace, monkeypatch):
    payload = {
        "chosen": "A", "selection_reason": "x", "changes_made": [],
        "change_percentage": 2, "unchanged_note": "y", "final_script": "fenced.",
    }
    _install_llm(monkeypatch, f"```json\n{json.dumps(payload)}\n```")

    result = script_selector_polisher_node(_state())
    assert result["selected_script"] == "fenced."
    assert "fallback" not in result["polisher_report"]  # parsed cleanly, no fallback


def test_composer_node_produces_both_variants(monkeypatch):
    """composer_node (default path) writes script_a and script_b into state."""
    from ytfactory.agents.nodes import composer as composer_mod

    class _FakeComposer:
        def __init__(self, settings):
            pass

        def run(self, project_id, script_text=None, *, temperature=None, **kwargs):
            return f"variant@{temperature}"

    monkeypatch.setattr(composer_mod, "ComposerPipeline", _FakeComposer)

    result = composer_mod.composer_node(
        {"project_id": "p", "script_md": "base", "ab_script_selection": False}
    )

    assert "script_a" in result and "script_b" in result
    assert result["script_a"] != result["script_b"]  # different temperatures
    assert "script_md" not in result  # selection happens in the polisher, not here
