"""Slack webhook integration for SignalPilot."""
from __future__ import annotations

import httpx

from signalpilot.models import Analysis, Severity


def send_slack_alert(analysis: Analysis, webhook_url: str, report_url: str = "") -> bool:
    """
    Send a Slack alert for an Analysis.
    Returns True on success, False on failure.

    Format: colored attachment with top finding, severity counts, link.
    """
    if not analysis.findings:
        return True  # nothing to alert on

    top = analysis.findings[0]
    crit = sum(1 for f in analysis.findings if f.severity == Severity.CRITICAL)
    high = sum(1 for f in analysis.findings if f.severity == Severity.HIGH)

    color = {"critical": "#dc2626", "high": "#ea580c", "medium": "#d97706"}.get(
        top.severity.value, "#2563eb"
    )

    top_fix = top.fixes[0] if top.fixes else None
    fix_text = f"\n>*Fix:* {top_fix.description}" if top_fix else ""
    if top_fix and top_fix.kubectl_snippet:
        fix_text += f"\n>```{top_fix.kubectl_snippet}```"

    payload = {
        "attachments": [{
            "color": color,
            "title": f"\u26a1 SignalPilot RCA \u2014 {analysis.namespace}",
            "text": (
                f"*{top.severity.value.upper()}*: {top.title}\n"
                f">{top.explanation[:200]}"
                + fix_text
            ),
            "fields": [
                {"title": "Critical", "value": str(crit), "short": True},
                {"title": "High", "value": str(high), "short": True},
                {"title": "Namespace", "value": analysis.namespace, "short": True},
                {"title": "Total Findings", "value": str(len(analysis.findings)), "short": True},
            ],
            "footer": "PerfSage SignalPilot" + (f" | <{report_url}|View Report>" if report_url else ""),
        }]
    }

    try:
        r = httpx.post(webhook_url, json=payload, timeout=10.0)
        return r.status_code == 200
    except Exception:
        return False
