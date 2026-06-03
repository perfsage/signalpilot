"""
HTML report generator for PerfSage SignalPilot.

Generates a self-contained HTML file (no external CSS/JS dependencies)
with dark/light theme, finding cards, evidence drill-down, and copy-paste fixes.
"""
from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, timezone
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from signalpilot.models import Analysis, Severity


_SEVERITY_COLOR = {
    Severity.CRITICAL: "#dc2626",
    Severity.HIGH: "#ea580c",
    Severity.MEDIUM: "#d97706",
    Severity.LOW: "#16a34a",
    Severity.INFO: "#2563eb",
}


def generate_html_report(analysis: Analysis, output_path: Optional[Path] = None) -> str:
    """
    Generate a self-contained HTML report from an Analysis.

    If output_path is provided, writes to file and returns the path string.
    Otherwise returns the HTML string.
    """
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["severity_color"] = lambda s: _SEVERITY_COLOR.get(Severity(s), "#666")
    env.filters["pct"] = lambda v: f"{v:.0%}"
    env.filters["json"] = json.dumps

    template = env.get_template("report.html.j2")

    html = template.render(
        analysis=analysis,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        severity_color=_SEVERITY_COLOR,
        findings=analysis.findings,
        deploy_change=analysis.deploy_change,
    )

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        return str(output_path)

    return html
