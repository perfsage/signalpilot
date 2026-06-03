"""Slack notification integration.

Full implementation will:
- Format an Analysis summary as a Slack Block Kit message
- Post to the configured webhook URL
- Throttle notifications to avoid alert fatigue (one per deploy per namespace)
"""

from __future__ import annotations

from signalpilot.models import Analysis


async def post_analysis_summary(analysis: Analysis, webhook_url: str) -> None:
    """Post a formatted summary of *analysis* to the Slack *webhook_url*."""
    raise NotImplementedError


def format_slack_blocks(analysis: Analysis) -> list[dict]:
    """Return a Slack Block Kit payload for *analysis*."""
    raise NotImplementedError
