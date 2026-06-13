"""
HTML report generator for PerfSage SignalPilot.

Generates a self-contained HTML file (no external CSS/JS dependencies)
with PerfSage branding, finding cards, evidence drill-down, and copy-paste fixes.
"""
from __future__ import annotations
from pathlib import Path
import base64
import json
from datetime import datetime, timezone
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from signalpilot.models import Analysis, Severity


_SEVERITY_COLOR = {
    Severity.CRITICAL: "#DC2626",
    Severity.HIGH: "#EA580C",
    Severity.MEDIUM: "#D97706",
    Severity.LOW: "#059669",
    Severity.INFO: "#2563EB",
}

# Human-readable labels for signal sources
_SOURCE_LABELS: dict[str, str] = {
    "kube_api": "Kube API",
    "events": "K8s Events",
    "metrics_server": "Metrics Server",
    "logs": "Container Logs",
    "cadvisor": "cAdvisor",
    "prometheus": "Prometheus",
    "otel_traces": "OTel Traces",
    "loki": "Loki",
    "network": "Network",
}

# Human-readable labels for signal kinds
_KIND_LABELS: dict[str, str] = {
    "restart": "Restart",
    "oom_killed": "OOM Killed",
    "crash_loop": "Crash Loop",
    "image_pull_error": "Image Pull Error",
    "probe_failure": "Probe Failure",
    "pending_pod": "Pending Pod",
    "event": "Event",
    "cpu_usage": "CPU Usage",
    "mem_usage": "Memory Usage",
    "log_error_rate": "Log Error Rate",
    "node_condition": "Node Condition",
    "network_error": "Network Error",
    "latency": "Latency",
}

# Emoji icons for signal kinds
_KIND_ICON: dict[str, str] = {
    "oom_killed": "💥",
    "crash_loop": "🔄",
    "image_pull_error": "📦",
    "probe_failure": "💉",
    "pending_pod": "⏳",
    "restart": "🔁",
    "event": "📋",
    "cpu_usage": "⚡",
    "mem_usage": "🧠",
    "log_error_rate": "📝",
    "node_condition": "🖥",
    "network_error": "🌐",
    "latency": "⏱",
}


def _clean_enum_str(raw: Any) -> str:
    """Normalise an enum (or string) to its lowercase value string."""
    s = str(raw)
    # Handle `SignalSource.KUBE_API` / `SignalKind.CRASH_LOOP` repr form
    if "." in s:
        s = s.split(".", 1)[1]
    return s.lower()


def _filter_source(raw: Any) -> str:
    key = _clean_enum_str(raw)
    return _SOURCE_LABELS.get(key, key.replace("_", " ").title())


def _filter_kind(raw: Any) -> str:
    key = _clean_enum_str(raw)
    return _KIND_LABELS.get(key, key.replace("_", " ").title())


def _filter_kind_icon(raw: Any) -> str:
    key = _clean_enum_str(raw)
    return _KIND_ICON.get(key, "🔍")


def _filter_severity_css(raw: Any) -> str:
    """Return the CSS class suffix for a severity value (critical / high / …)."""
    s = str(raw)
    if "." in s:
        s = s.split(".", 1)[1]
    return s.lower()


def _logo_data_uri() -> str:
    """Return the PerfSage logo as a base64 data URI, or empty string if not found."""
    workspace = Path(__file__).parent.parent.parent.parent  # …/src → workspace root
    candidates = [
        workspace / ".cursor" / "projects" / "Users-aashu-Documents-SignalPilot" / "assets"
        / "color-circle-icon-layout__1_-0a48524f-7dda-4a9d-99af-9d40f37c5eb9.png",
        Path.home() / ".cursor" / "projects" / "Users-aashu-Documents-SignalPilot" / "assets"
        / "color-circle-icon-layout__1_-0a48524f-7dda-4a9d-99af-9d40f37c5eb9.png",
    ]
    for p in candidates:
        if p.exists():
            data = base64.b64encode(p.read_bytes()).decode()
            return f"data:image/png;base64,{data}"
    return ""


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
    env.filters["severity_css"] = _filter_severity_css
    env.filters["source_label"] = _filter_source
    env.filters["kind_label"] = _filter_kind
    env.filters["kind_icon"] = _filter_kind_icon
    env.filters["pct"] = lambda v: f"{int(round(float(v) * 100))}%"
    env.filters["json"] = json.dumps

    # Count findings by severity
    sev_counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in analysis.findings:
        key = _filter_severity_css(f.severity)
        sev_counts[key] = sev_counts.get(key, 0) + 1

    template = env.get_template("report.html.j2")

    html = template.render(
        analysis=analysis,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        findings=analysis.findings,
        deploy_change=analysis.deploy_change,
        sev_counts=sev_counts,
        logo_uri=_logo_data_uri(),
    )

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        return str(output_path)

    return html
