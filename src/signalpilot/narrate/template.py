"""Template-based narrative generation (no LLM required).

Full implementation will:
- Use Jinja2 templates to render a human-readable explanation for each Finding
- Produce a structured plain-text summary of the full Analysis
- Support Markdown and plain-text output modes
"""

from __future__ import annotations

from signalpilot.models import Analysis, Finding


def render_finding(finding: Finding) -> str:
    """Return a single-paragraph plain-text explanation for *finding*."""
    raise NotImplementedError


def render_analysis_summary(analysis: Analysis) -> str:
    """Return a full plain-text RCA narrative for *analysis*."""
    raise NotImplementedError
