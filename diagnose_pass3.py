"""Reproduce the Pass 3 duration bug for diagnosis."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from ytfactory.script_enhancer.pipeline import DocumentaryScriptEnhancerPipeline
from ytfactory.shared.pipeline_status import PipelineAbort


def make_response(text: str) -> MagicMock:
    r = MagicMock()
    r.text = text
    return r


# Short script (~348 words = 5.8 min)
SHORT_SCRIPT = """The teacher began with a simple observation about the nature of consciousness and how it relates to our everyday experience of suffering and joy.

Attachment creates pain. This is the core insight. When we cling to people, possessions, outcomes, and identities, we set ourselves up for inevitable disappointment.

The teacher tells a story of a man carrying a heavy burden across a desert, convinced it holds treasure, only to discover it is filled with ordinary stones. His suffering was real, but the burden was entirely optional.

Another analogy follows. The mind is like a clear mountain lake. When disturbed by wind, it cannot reflect the sky. But the sky is always there, unchanged. The practice is not to stop the ripples but to identify with the depth beneath them.

Stories and analogies follow naturally from this observation, each one deepening the understanding that suffering is not a failure but an invitation.

The closing wisdom lands with weight: every frustration carries a teaching if we are willing to receive it with an open mind.
"""

# Pass 2 response with high narrative score but same word count
PASS2_SHORT_HIGH_SCORE = SHORT_SCRIPT + """
---NARRATIVE SCORE---
Hook: 9/10
Story Density: 9/10
Curiosity: 9/10
Emotional Rhythm: 9/10
Accessibility: 9/10
Overall: 9.4/10
---END SCORE---
EDITOR'S NOTES:
dominant_visual_symbol: river
rule_skips: none
factual_gaps: none
"""

# Pass 3 response that simulates the bug: same word count as input
PASS3_SAME_LENGTH = (
    "The teacher began with a simple observation about the nature of consciousness "
    "and how it relates to our everyday experience of suffering and joy. "
    "There is a clarity in this starting point that immediately draws the listener in.\n\n"
    "Attachment creates pain. This is the core insight. When we cling to people, "
    "possessions, outcomes, and identities, we set ourselves up for inevitable disappointment. "
    "The teacher explores this with precision and compassion.\n\n"
    "The teacher tells a story of a man carrying a heavy burden across a desert, "
    "convinced it holds treasure, only to discover it is filled with ordinary stones. "
    "His suffering was real, but the burden was entirely optional -- a creation of his own mind.\n\n"
    "Another analogy follows. The mind is like a clear mountain lake. "
    "When disturbed by wind, it cannot reflect the sky. But the sky is always there, "
    "unchanged. The practice is not to stop the ripples but to identify with the depth beneath them.\n\n"
    "Stories and analogies follow naturally from this observation. "
    "Each one deepens the understanding that suffering is not a failure but an invitation "
    "to deeper understanding.\n\n"
    "The closing wisdom lands with weight. Every frustration carries a teaching "
    "if we are willing to receive it with an open mind."
)


def main():
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        make_response(SHORT_SCRIPT),                    # Pass 1
        make_response(PASS2_SHORT_HIGH_SCORE),         # Pass 2
        make_response(PASS3_SAME_LENGTH),              # Pass 3 (same word count)
    ]

    settings = MagicMock()
    settings.stop_on_quality_gate_failure = True

    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("ytfactory.script_enhancer.pipeline.get_llm_provider", return_value=mock_llm):
            pipeline = DocumentaryScriptEnhancerPipeline(settings)
            project_id = "proj-diag"

            with patch("ytfactory.script_enhancer.pipeline.WORKSPACE_DIR", tmp_dir):
                try:
                    result = pipeline.run(project_id, topic="Test", script_text=SHORT_SCRIPT, target_minutes=8)
                except PipelineAbort as e:
                    print(f"\n[PIPELINE ABORTED] stage={e.stage} reason={e.reason}")
                    return
                except Exception as e:
                    print(f"\n[UNEXPECTED ERROR] {e}")
                    return

            report = json.loads(
                (Path(tmp_dir) / project_id / "script" / "enhancement-report.json").read_text()
            )
            print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
