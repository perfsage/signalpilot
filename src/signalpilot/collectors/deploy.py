"""Deployment change collector.

Full implementation will:
- List Deployment revision history via ``kubectl rollout history`` or ReplicaSet diffs
- Diff image, env, resource, and configmap/secret references between revisions
- Optionally enrich with git metadata by correlating image tags to commits
"""

from __future__ import annotations

from signalpilot.models import DeployChange


async def collect_deploy_change(deployment: str, namespace: str) -> DeployChange | None:
    """Return the most recent DeployChange for *deployment* in *namespace*.

    Returns ``None`` if no recent rollout is detected.
    """
    raise NotImplementedError


async def list_recent_deployments(namespace: str, limit: int = 10) -> list[DeployChange]:
    """Return the *limit* most recent deployment changes in *namespace*."""
    raise NotImplementedError
