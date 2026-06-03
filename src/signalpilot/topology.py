"""Kubernetes service topology graph builder.

Full implementation will:
- Walk K8s Services, Deployments, ReplicaSets, Pods via the API
- Infer call edges from Prometheus metrics (``calls_total`` labels)
- Detect dependency chains that could amplify a failure blast radius
- Expose a NetworkX DiGraph for path/centrality analysis
"""

from __future__ import annotations

import networkx as nx

from signalpilot.models import TopologyGraph


def build_topology(namespace: str) -> TopologyGraph:
    """Discover and return the workload topology for *namespace*."""
    raise NotImplementedError


def to_networkx(graph: TopologyGraph) -> nx.DiGraph:
    """Convert a TopologyGraph to a NetworkX DiGraph for graph algorithms."""
    raise NotImplementedError


def blast_radius_score(graph: TopologyGraph, node_id: str) -> float:
    """Return a 0-1 score representing how many services depend on *node_id*."""
    raise NotImplementedError
