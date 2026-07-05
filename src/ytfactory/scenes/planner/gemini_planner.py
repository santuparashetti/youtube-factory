import json

from ytfactory.config.settings import Settings
from ytfactory.providers.llm.factory import get_llm_provider
from ytfactory.scenes.models import ScenePlan
from ytfactory.scenes.prompts.system_prompt import SYSTEM_PROMPT


class GeminiScenePlanner:
    """Generates a scene plan from a narration script."""

    def __init__(self, settings: Settings):
        self._llm = get_llm_provider(settings)

    def generate(self, script: str) -> ScenePlan:
        response = self._llm.generate(
            script,
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,
        )

        data = json.loads(response.text)

        return ScenePlan.model_validate(data)
