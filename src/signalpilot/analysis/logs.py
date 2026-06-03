"""Log analysis using drain3 template mining.

Full implementation will:
- Accept raw log lines from any collector (K8s logs or Loki)
- Use drain3 to extract log templates (fingerprints)
- Compute per-template frequency deltas between baseline and analysis windows
- Identify new or significantly increased error clusters as LogCluster objects
"""

from __future__ import annotations

from signalpilot.models import LogCluster


def cluster_logs(
    before_lines: list[str],
    after_lines: list[str],
    max_clusters: int = 200,
) -> list[LogCluster]:
    """Mine log templates and return clusters with before/after frequency deltas.

    Args:
        before_lines: Log lines from the baseline window (before deploy).
        after_lines: Log lines from the analysis window (after deploy).
        max_clusters: Maximum number of clusters to return, ranked by delta.

    Returns:
        List of LogCluster sorted by descending ``count_after``.
    """
    raise NotImplementedError


def categorise_cluster(template: str) -> str | None:
    """Assign a short category label to a log template.

    Categories: ``oom``, ``gc``, ``conn``, ``timeout``, ``dns``, ``tls``,
    ``pool``, ``auth``, ``panic``, or ``None`` if unrecognised.
    """
    raise NotImplementedError
