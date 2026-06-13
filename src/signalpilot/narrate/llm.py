"""
Optional LLM narrative polishing for PerfSage SignalPilot.

Requires SIGNALPILOT_LLM_PROVIDER env var ("openai" or "anthropic") and
SIGNALPILOT_LLM_API_KEY to be set. Falls back to template narrative if not.

Always grounds the LLM in deterministic context — never lets it hallucinate
K8s objects or recommendations not present in the Analysis.
"""
from __future__ import annotations

from signalpilot.config import get_settings
from signalpilot.models import Analysis
from signalpilot.narrate.template import generate_narrative


def polish_narrative(analysis: Analysis) -> str:
    """
    Polish the deterministic narrative with an LLM if configured.
    Falls back to template narrative if LLM is not configured or fails.
    """
    settings = get_settings()
    base_narrative = generate_narrative(analysis)

    if not settings.llm_provider or not settings.llm_api_key:
        return base_narrative

    try:
        return _call_llm(base_narrative, analysis, settings)
    except Exception:
        return base_narrative


def _call_llm(base: str, analysis: Analysis, settings) -> str:
    """Call configured LLM to polish the narrative."""
    prompt = (
        "You are a site reliability engineer writing a brief incident analysis report. "
        "Polish the following Kubernetes RCA summary into a clear, professional paragraph "
        "(max 5 sentences). Do NOT add findings, recommendations, or facts not in the text. "
        "Keep all specific values, names, and kubectl commands exactly as-is.\n\n"
        f"DRAFT:\n{base}\n\nPOLISHED:"
    )

    if settings.llm_provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=settings.llm_api_key)
        response = client.chat.completions.create(
            model=settings.llm_model or "gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=settings.llm_max_tokens,
        )
        return response.choices[0].message.content.strip()

    elif settings.llm_provider == "anthropic":
        from anthropic import Anthropic
        client = Anthropic(api_key=settings.llm_api_key)
        response = client.messages.create(
            model=settings.llm_model or "claude-3-haiku-20240307",
            max_tokens=settings.llm_max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    return base
