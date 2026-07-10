import json

from loguru import logger

from ytfactory.config.settings import Settings
from ytfactory.providers.llm.factory import get_llm_provider
from ytfactory.scenes.models import ScenePlan
from ytfactory.scenes.prompts.system_prompt import SYSTEM_PROMPT


class LLMScenePlanner:
    """Generates a scene plan from a narration script using the configured LLM provider."""

    def __init__(self, settings: Settings):
        self._llm = get_llm_provider(settings)

    def generate(self, script: str) -> ScenePlan:
        response = self._llm.generate(
            script,
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,
        )

        text = response.text.strip()

        if not text:
            raise RuntimeError(
                f"LLM returned empty response (model={response.model}, "
                f"finish_reason={response.finish_reason}, "
                f"prompt_tokens={response.prompt_tokens}, "
                f"completion_tokens={response.completion_tokens})"
            )

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(
                "Scene planner: LLM returned non-JSON response. "
                "model={} finish_reason={} response_preview={!r}",
                response.model,
                response.finish_reason,
                text[:500],
            )
            raise RuntimeError(
                f"Scene planner: LLM returned invalid JSON "
                f"(model={response.model}, finish_reason={response.finish_reason}). "
                f"Response starts with: {text[:200]}"
            ) from exc

        return ScenePlan.model_validate(data)
