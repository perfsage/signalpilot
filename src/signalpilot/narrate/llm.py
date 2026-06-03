"""LLM-assisted narrative generation (optional).

Full implementation will:
- Accept a structured Analysis and call the configured LLM (OpenAI or Anthropic)
- Use a carefully crafted system prompt that grounds the LLM in the evidence
- Stream the response and return it as a string
- Fall back gracefully to template-based narration if LLM is not configured
"""

from __future__ import annotations

from signalpilot.config import Settings
from signalpilot.models import Analysis


async def generate_narrative(
    analysis: Analysis,
    settings: Settings | None = None,
) -> str:
    """Generate an LLM-assisted narrative for *analysis*.

    Falls back to template-based narration if ``llm_provider`` is not set.

    Args:
        analysis: The populated Analysis object to narrate.
        settings: Optional settings override.

    Returns:
        Markdown-formatted narrative string.
    """
    raise NotImplementedError
