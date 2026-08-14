"""Tests for the TTS Pronunciation Preparation Layer.

Covers:
- PronunciationHint / TTSPreparedScript domain models
- Dictionary loading and cache
- Term detection (Sanskrit detected, English ignored)
- TTSPreparationService (canonical text never mutated)
- TTS Provider Adapter (SSML sub injection, non-SSML passthrough)
- Word count invariance (hints don't add spoken words)
- Backward compatibility (scripts without special terms unchanged)
- Low-confidence terms surface for review
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from ytfactory.tts_prep import (
    TTSPreparationService,
    apply_pronunciation,
    PronunciationHint,
    TTSPreparedScript,
    reset_cache,
)
from ytfactory.tts_prep.detector import detect_terms
from ytfactory.tts_prep.dictionary import get_dictionary
from ytfactory.tts_prep.adapter import _apply_ssml_sub
from ytfactory.ssml_enhancer import strip_ssml


# ── Fixtures ──────────────────────────────────────────────────────────────────

_SAMPLE_DICT = {
    "Dirghakala": PronunciationHint(
        term="Dirghakala",
        pronunciation="DEER-gha KAA-la",
        language="Sanskrit",
        source="dictionary",
        confidence=1.0,
    ),
    "Nairantarya": PronunciationHint(
        term="Nairantarya",
        pronunciation="nai-ran-TAR-ya",
        language="Sanskrit",
        source="dictionary",
        confidence=1.0,
    ),
    "Satkara": PronunciationHint(
        term="Satkara",
        pronunciation="SAT-kaa-ra",
        language="Sanskrit",
        source="dictionary",
        confidence=1.0,
    ),
    "Patanjali": PronunciationHint(
        term="Patanjali",
        pronunciation="pah-TAN-jah-lee",
        language="Sanskrit",
        source="dictionary",
        confidence=1.0,
    ),
}

_SAMPLE_NARRATION = textwrap.dedent("""\
    Maharishi Patanjali offered an ancient blueprint in the Yoga Sutras.

    Dirghakala means practice over a long period of time.

    Nairantarya means without interruption.

    Satkara means devotion and sincerity.
""")

_PLAIN_ENGLISH = "The pursuit of excellence requires consistency and discipline."


# ── Domain model tests ────────────────────────────────────────────────────────

class TestPronunciationHint:
    def test_to_dict(self):
        hint = PronunciationHint(
            term="Dirghakala",
            pronunciation="DEER-gha KAA-la",
            language="Sanskrit",
        )
        d = hint.to_dict()
        assert d["term"] == "Dirghakala"
        assert d["pronunciation"] == "DEER-gha KAA-la"
        assert d["language"] == "Sanskrit"
        assert d["source"] == "dictionary"
        assert d["confidence"] == 1.0

    def test_defaults(self):
        hint = PronunciationHint(term="foo", pronunciation="bar")
        assert hint.language == ""
        assert hint.source == "dictionary"
        assert hint.confidence == 1.0


class TestTTSPreparedScript:
    def test_canonical_text_preserved(self):
        script = TTSPreparedScript(canonical_text="Dirghakala is a Sanskrit term.")
        assert script.canonical_text == "Dirghakala is a Sanskrit term."

    def test_hint_count(self):
        hint = PronunciationHint(term="Dirghakala", pronunciation="DEER-gha KAA-la")
        script = TTSPreparedScript(
            canonical_text="Dirghakala is a term.",
            hints=[hint],
        )
        assert script.hint_count == 1
        assert script.review_count == 0

    def test_to_dict(self):
        hint = PronunciationHint(term="Dirghakala", pronunciation="DEER-gha KAA-la")
        script = TTSPreparedScript(canonical_text="text", hints=[hint])
        d = script.to_dict()
        assert d["canonical_text"] == "text"
        assert len(d["hints"]) == 1
        assert d["hints"][0]["term"] == "Dirghakala"


# ── Dictionary tests ──────────────────────────────────────────────────────────

class TestDictionary:
    def setup_method(self):
        reset_cache()

    def test_loads_yaml(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            pronunciations:
              Dirghakala:
                pronunciation: "DEER-gha KAA-la"
                language: Sanskrit
              Nairantarya:
                pronunciation: "nai-ran-TAR-ya"
                language: Sanskrit
        """)
        config = tmp_path / "pronunciations.yaml"
        config.write_text(yaml_content)

        d = get_dictionary(config)
        assert "Dirghakala" in d
        assert d["Dirghakala"].pronunciation == "DEER-gha KAA-la"
        assert d["Dirghakala"].language == "Sanskrit"
        assert d["Dirghakala"].source == "dictionary"
        assert d["Dirghakala"].confidence == 1.0

    def test_missing_file_returns_empty(self, tmp_path):
        d = get_dictionary(tmp_path / "nonexistent.yaml")
        assert d == {}

    def test_malformed_entry_skipped(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            pronunciations:
              Good:
                pronunciation: "GOOD"
                language: English
              Bad: "not a dict"
        """)
        config = tmp_path / "pronunciations.yaml"
        config.write_text(yaml_content)
        reset_cache()

        d = get_dictionary(config)
        assert "Good" in d
        assert "Bad" not in d

    def test_reset_cache(self, tmp_path):
        config = tmp_path / "pronunciations.yaml"
        config.write_text("pronunciations:\n  A:\n    pronunciation: 'AY'\n")
        d1 = get_dictionary(config)

        reset_cache()
        config.write_text("pronunciations:\n  B:\n    pronunciation: 'BEE'\n")
        d2 = get_dictionary(config)

        assert "A" in d1
        assert "B" in d2
        assert "A" not in d2


# ── Detector tests ────────────────────────────────────────────────────────────

class TestDetector:
    def test_dictionary_terms_detected(self):
        text = "Dirghakala means practice over a long period."
        hits = detect_terms(text, _SAMPLE_DICT)
        terms = [h.term for h in hits]
        assert "Dirghakala" in terms

    def test_multiple_dictionary_terms_detected(self):
        hits = detect_terms(_SAMPLE_NARRATION, _SAMPLE_DICT)
        terms = {h.term for h in hits}
        assert "Dirghakala" in terms
        assert "Nairantarya" in terms
        assert "Satkara" in terms
        assert "Patanjali" in terms

    def test_ordinary_english_ignored(self):
        text = "The pursuit of excellence requires consistency and discipline."
        hits = detect_terms(text, {})
        assert hits == []

    def test_term_not_in_text_not_returned(self):
        # "Vairagya" is not in the sample narration
        hits = detect_terms(_SAMPLE_NARRATION, _SAMPLE_DICT)
        terms = [h.term for h in hits]
        assert "Vairagya" not in terms

    def test_no_duplicates(self):
        text = "Dirghakala is Dirghakala — practice over time."
        hits = detect_terms(text, _SAMPLE_DICT)
        terms = [h.term for h in hits]
        assert terms.count("Dirghakala") == 1

    def test_short_words_ignored(self):
        hits = detect_terms("The dh term is short.", {})
        terms = [h.term for h in hits]
        assert all(len(t) >= 5 for t in terms)

    def test_detected_unknown_term_low_confidence(self):
        # A Sanskrit-pattern term not in the dictionary
        text = "Brahmacharya is a Sanskrit concept."
        hits = detect_terms(text, {})  # empty dict
        brahma_hits = [h for h in hits if h.term == "Brahmacharya"]
        if brahma_hits:
            assert brahma_hits[0].confidence < 1.0
            assert brahma_hits[0].source == "detected"


# ── TTSPreparationService tests ───────────────────────────────────────────────

class TestTTSPreparationService:
    def _make_service(self, tmp_path) -> TTSPreparationService:
        reset_cache()
        yaml_content = textwrap.dedent("""\
            pronunciations:
              Dirghakala:
                pronunciation: "DEER-gha KAA-la"
                language: Sanskrit
              Nairantarya:
                pronunciation: "nai-ran-TAR-ya"
                language: Sanskrit
              Satkara:
                pronunciation: "SAT-kaa-ra"
                language: Sanskrit
              Patanjali:
                pronunciation: "pah-TAN-jah-lee"
                language: Sanskrit
        """)
        config = tmp_path / "pronunciations.yaml"
        config.write_text(yaml_content)
        return TTSPreparationService(config_path=str(config))

    def test_canonical_text_never_mutated(self, tmp_path):
        service = self._make_service(tmp_path)
        original = _SAMPLE_NARRATION
        prepared = service.prepare(original)
        assert prepared.canonical_text == original
        assert prepared.canonical_text is original  # same object

    def test_hints_populated(self, tmp_path):
        service = self._make_service(tmp_path)
        prepared = service.prepare(_SAMPLE_NARRATION)
        terms = {h.term for h in prepared.hints}
        assert "Dirghakala" in terms
        assert "Nairantarya" in terms
        assert "Satkara" in terms
        assert "Patanjali" in terms

    def test_empty_text_no_crash(self, tmp_path):
        service = self._make_service(tmp_path)
        prepared = service.prepare("")
        assert prepared.canonical_text == ""
        assert prepared.hints == []

    def test_plain_english_no_hints(self, tmp_path):
        service = self._make_service(tmp_path)
        prepared = service.prepare(_PLAIN_ENGLISH)
        assert prepared.hint_count == 0

    def test_low_confidence_goes_to_review(self, tmp_path):
        reset_cache()
        # Empty dictionary → detected terms (low confidence) go to requires_review
        config = tmp_path / "pronunciations.yaml"
        config.write_text("pronunciations: {}\n")
        service = TTSPreparationService(config_path=str(config))

        text = "Brahmacharya is a Sanskrit concept of celibacy."
        prepared = service.prepare(text)
        review_terms = {h.term for h in prepared.requires_review}
        # Brahmacharya should be detected (Sanskrit pattern) with low confidence
        assert "Brahmacharya" in review_terms
        # And it must NOT appear in trusted hints
        trusted_terms = {h.term for h in prepared.hints}
        assert "Brahmacharya" not in trusted_terms

    def test_word_count_unaffected(self, tmp_path):
        service = self._make_service(tmp_path)
        prepared = service.prepare(_SAMPLE_NARRATION)
        # Word count of canonical_text must equal the original
        original_wc = len(_SAMPLE_NARRATION.split())
        canonical_wc = len(prepared.canonical_text.split())
        assert canonical_wc == original_wc


# ── Adapter tests ─────────────────────────────────────────────────────────────

class TestAdapter:
    def _make_hints(self) -> list[PronunciationHint]:
        return [
            PronunciationHint(
                term="Dirghakala",
                pronunciation="DEER-gha KAA-la",
                language="Sanskrit",
            ),
            PronunciationHint(
                term="Patanjali",
                pronunciation="pah-TAN-jah-lee",
                language="Sanskrit",
            ),
        ]

    def _make_prepared(self, text: str, hints=None) -> TTSPreparedScript:
        return TTSPreparedScript(
            canonical_text=text,
            hints=hints or self._make_hints(),
        )

    # ── SSML <sub> injection ──────────────────────────────────────────────

    def test_ssml_sub_injected(self):
        ssml = "<speak>Patanjali offered an ancient blueprint. Dirghakala means practice.</speak>"
        prepared = self._make_prepared(ssml)
        result = apply_pronunciation(
            ssml, prepared, provider_name="speechify", ssml_mode=True
        )
        assert '<sub alias="pah-TAN-jah-lee">Patanjali</sub>' in result
        assert '<sub alias="DEER-gha KAA-la">Dirghakala</sub>' in result

    def test_ssml_sub_preserves_canonical_after_strip(self):
        ssml = "<speak>Dirghakala means practice.</speak>"
        prepared = self._make_prepared(ssml)
        result = apply_pronunciation(
            ssml, prepared, provider_name="speechify", ssml_mode=True
        )
        stripped = strip_ssml(result)
        assert "Dirghakala" in stripped
        assert "DEER-gha KAA-la" not in stripped

    def test_sub_not_double_applied(self):
        already_subbed = (
            '<speak><sub alias="DEER-gha KAA-la">Dirghakala</sub> means practice.</speak>'
        )
        prepared = self._make_prepared(already_subbed)
        result = apply_pronunciation(
            already_subbed, prepared, provider_name="speechify", ssml_mode=True
        )
        # Should not nest <sub> inside <sub>
        assert result.count("<sub") == 1

    def test_no_hints_returns_unchanged(self):
        tts_text = "<speak>Hello world.</speak>"
        prepared = TTSPreparedScript(canonical_text=tts_text, hints=[])
        result = apply_pronunciation(
            tts_text, prepared, provider_name="speechify", ssml_mode=True
        )
        assert result == tts_text

    # ── Non-SSML path ─────────────────────────────────────────────────────

    def test_non_ssml_provider_no_injection(self):
        plain_text = "Dirghakala means practice over a long period."
        prepared = self._make_prepared(plain_text)
        result = apply_pronunciation(
            plain_text, prepared, provider_name="kokoro", ssml_mode=False
        )
        assert result == plain_text  # unchanged
        assert "<sub" not in result

    def test_edge_tts_no_injection(self):
        plain_text = "Patanjali offered a blueprint."
        prepared = self._make_prepared(plain_text)
        result = apply_pronunciation(
            plain_text, prepared, provider_name="edge_tts", ssml_mode=False
        )
        assert result == plain_text

    def test_speechify_without_ssml_mode_no_injection(self):
        plain_text = "Dirghakala means practice."
        prepared = self._make_prepared(plain_text)
        # ssml_mode=False → no injection even for Speechify.
        # Integration test (2026-08-14) confirmed <sub> only works when the full
        # text is wrapped in <speak>…</speak>. Standalone <sub> in plain text is
        # untested; we block it rather than risk the tags being spoken literally.
        result = apply_pronunciation(
            plain_text, prepared, provider_name="speechify", ssml_mode=False
        )
        # Text must be returned unchanged — no <sub> tags injected.
        assert result == plain_text
        assert "<sub" not in result

    # ── Word count in TTS vs subtitle ────────────────────────────────────

    def test_pronunciation_hint_not_counted_in_canonical_words(self):
        narration = "Dirghakala means practice over time."
        original_wc = len(narration.split())

        prepared = TTSPreparedScript(
            canonical_text=narration,
            hints=[PronunciationHint(term="Dirghakala", pronunciation="DEER-gha KAA-la")],
        )

        # Canonical word count is unaffected
        assert len(prepared.canonical_text.split()) == original_wc

        # Even after SSML injection, strip_ssml recovers canonical
        ssml = f"<speak>{narration}</speak>"
        tts_text = apply_pronunciation(
            ssml, prepared, provider_name="speechify", ssml_mode=True
        )
        stripped = strip_ssml(tts_text)
        stripped_wc = len(stripped.split())
        assert stripped_wc == original_wc


# ── Backward compatibility tests ──────────────────────────────────────────────

class TestBackwardCompatibility:
    def test_scripts_without_special_terms_unchanged(self, tmp_path):
        reset_cache()
        config = tmp_path / "pronunciations.yaml"
        config.write_text("pronunciations: {}\n")
        service = TTSPreparationService(config_path=str(config))

        plain = "Consistency is the foundation of all achievement."
        prepared = service.prepare(plain)

        assert prepared.canonical_text == plain
        assert prepared.hint_count == 0
        assert prepared.review_count == 0

        tts_text = apply_pronunciation(
            plain, prepared, provider_name="speechify", ssml_mode=False
        )
        assert tts_text == plain

    def test_ssml_enhanced_script_without_terms_unchanged(self, tmp_path):
        reset_cache()
        config = tmp_path / "pronunciations.yaml"
        config.write_text("pronunciations: {}\n")
        service = TTSPreparationService(config_path=str(config))

        ssml = "<speak>Consistency is the foundation of all achievement.</speak>"
        prepared = service.prepare("Consistency is the foundation of all achievement.")

        result = apply_pronunciation(
            ssml, prepared, provider_name="speechify", ssml_mode=True
        )
        assert result == ssml


# ── Full pipeline integration test ───────────────────────────────────────────

class TestFullPipeline:
    """Simulate the script → pronunciation preparation → TTS path."""

    def test_accepted_script_to_tts_pipeline(self, tmp_path):
        reset_cache()
        yaml_content = textwrap.dedent("""\
            pronunciations:
              Dirghakala:
                pronunciation: "DEER-gha KAA-la"
                language: Sanskrit
              Nairantarya:
                pronunciation: "nai-ran-TAR-ya"
                language: Sanskrit
              Satkara:
                pronunciation: "SAT-kaa-ra"
                language: Sanskrit
        """)
        config = tmp_path / "pronunciations.yaml"
        config.write_text(yaml_content)

        # Step 1: Accepted canonical script (never modified)
        canonical = textwrap.dedent("""\
            Maharishi Patanjali offered an ancient blueprint in the Yoga Sutras.
            Dirghakala means practice over a long period of time.
            Nairantarya means without interruption.
            Satkara means devotion and sincerity.
        """).strip()

        # Step 2: Pronunciation preparation
        service = TTSPreparationService(config_path=str(config))
        prepared = service.prepare(canonical)

        # Canonical text is byte-for-byte unchanged
        assert prepared.canonical_text == canonical

        # Three terms found
        terms = {h.term for h in prepared.hints}
        assert "Dirghakala" in terms
        assert "Nairantarya" in terms
        assert "Satkara" in terms

        # Step 3: Simulate SSML enhancement (mocked — just wrap in <speak>)
        ssml_text = f"<speak>{canonical}</speak>"

        # Step 4: Apply pronunciation to SSML
        tts_text = apply_pronunciation(
            ssml_text, prepared, provider_name="speechify", ssml_mode=True
        )

        # TTS text has <sub> tags
        assert '<sub alias="DEER-gha KAA-la">Dirghakala</sub>' in tts_text
        assert '<sub alias="nai-ran-TAR-ya">Nairantarya</sub>' in tts_text
        assert '<sub alias="SAT-kaa-ra">Satkara</sub>' in tts_text

        # Step 5: Subtitle path — strip SSML → canonical terms remain
        subtitle_text = strip_ssml(tts_text)
        assert "Dirghakala" in subtitle_text
        assert "Nairantarya" in subtitle_text
        assert "Satkara" in subtitle_text

        # No pronunciation hints in subtitle text
        assert "DEER-gha" not in subtitle_text
        assert "nai-ran-TAR-ya" not in subtitle_text

        # Word count: subtitle text matches canonical
        assert len(subtitle_text.split()) == len(canonical.split())

    def test_canonical_script_not_mutated_by_any_stage(self, tmp_path):
        reset_cache()
        config = tmp_path / "pronunciations.yaml"
        config.write_text("pronunciations:\n  Abhyasa:\n    pronunciation: 'ah-BYAH-sa'\n    language: Sanskrit\n")

        canonical = "Abhyasa is the practice of consistent effort."
        original_id = id(canonical)

        service = TTSPreparationService(config_path=str(config))
        prepared = service.prepare(canonical)

        # Same string object returned
        assert prepared.canonical_text is canonical
        assert id(prepared.canonical_text) == original_id

        # Adapter never touches canonical_text
        ssml = f"<speak>{canonical}</speak>"
        tts_out = apply_pronunciation(
            ssml, prepared, provider_name="speechify", ssml_mode=True
        )
        assert prepared.canonical_text == canonical  # still unchanged
