"""Git history collector.

Full implementation will:
- Clone or fetch the repository associated with a deployment image tag
- Extract commits between two image tags/SHAs
- Identify suspect commits (large diffs, risky file patterns, hot authors)
"""

from __future__ import annotations

from signalpilot.models import GitChange


async def collect_git_change(repo_url: str, from_sha: str | None, to_sha: str) -> GitChange:
    """Return a GitChange between *from_sha* and *to_sha* in *repo_url*.

    If *from_sha* is ``None``, uses the first parent of *to_sha* as the base.
    """
    raise NotImplementedError


def identify_suspect_commits(change: GitChange, risk_patterns: list[str] | None = None) -> GitChange:
    """Re-rank *change* with ``suspect_commits`` populated based on *risk_patterns*.

    Default risk patterns include: migration files, dependency manifests, init scripts.
    """
    raise NotImplementedError
