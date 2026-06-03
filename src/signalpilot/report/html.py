"""HTML report renderer.

Full implementation will:
- Render a self-contained HTML report from an Analysis using Jinja2
- Embed interactive charts (severity breakdown, timeline, topology graph)
- Include kubectl/yaml snippets for every Fix, with copy-to-clipboard buttons
"""

from __future__ import annotations

from pathlib import Path

from signalpilot.models import Analysis


def render_html_report(analysis: Analysis, output_path: str | Path) -> Path:
    """Render an HTML report for *analysis* and write it to *output_path*.

    Returns the resolved Path of the written file.
    """
    raise NotImplementedError
