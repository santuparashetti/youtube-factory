from rich.console import Console

from ytfactory.config.settings import Settings
from ytfactory.providers.llm.factory import get_llm_provider
from ytfactory.providers.search.factory import get_search_provider

console = Console()


class DoctorService:
    """Validate the application environment."""

    def run(self) -> None:
        settings = Settings()

        console.print("\n[bold cyan]YouTube Factory Doctor[/bold cyan]\n")

        console.print("[green]✓[/green] Configuration loaded")

        if settings.gemini_api_key:
            console.print("[green]✓[/green] Gemini API key")
        else:
            raise RuntimeError("Gemini API key not configured.")

        if settings.tavily_api_key:
            console.print("[green]✓[/green] Tavily API key")
        else:
            raise RuntimeError("Tavily API key not configured.")

        llm = get_llm_provider(settings)
        search = get_search_provider(settings)

        console.print(
            f"[green]✓[/green] LLM Provider: {type(llm).__name__}"
        )
        console.print(
            f"[green]✓[/green] Search Provider: {type(search).__name__}"
        )

        # Validate Tavily
        results = search.search("OpenAI", max_results=1)

        if not results:
            raise RuntimeError("Search provider returned no results.")

        console.print("[green]✓[/green] Tavily search")

        # Validate Gemini
        response = llm.generate("Reply with exactly: OK")

        if response.text.strip() != "OK":
            raise RuntimeError(
                f"Unexpected Gemini response: {response.text}"
            )

        console.print("[green]✓[/green] Gemini connection")

        console.print(
            "\n[bold green]Environment is healthy.[/bold green]"
        )