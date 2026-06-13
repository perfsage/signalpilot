"""Unit tests for TopologyBuilder."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import networkx as nx

from signalpilot.models import (
    Severity,
    Signal,
    SignalKind,
    SignalSource,
    Target,
    TopologyEdge,
    TopologyGraph,
    TopologyNode,
)
from signalpilot.topology import TopologyBuilder

T0 = datetime(2024, 6, 1, tzinfo=timezone.utc)


def build_small_graph() -> TopologyGraph:
    """Deployment -> ReplicaSet -> 2 Pods; Service -> 2 Pods."""
    nodes = [
        TopologyNode(id="Deployment/ns/api", kind="Deployment", name="api", namespace="ns"),
        TopologyNode(id="ReplicaSet/ns/api-abc", kind="ReplicaSet", name="api-abc", namespace="ns"),
        TopologyNode(id="Pod/ns/api-abc-1", kind="Pod", name="api-abc-1", namespace="ns"),
        TopologyNode(id="Pod/ns/api-abc-2", kind="Pod", name="api-abc-2", namespace="ns"),
        TopologyNode(id="Service/ns/api-svc", kind="Service", name="api-svc", namespace="ns"),
    ]
    edges = [
        TopologyEdge(from_id="Deployment/ns/api", to_id="ReplicaSet/ns/api-abc", kind="owns"),
        TopologyEdge(from_id="ReplicaSet/ns/api-abc", to_id="Pod/ns/api-abc-1", kind="owns"),
        TopologyEdge(from_id="ReplicaSet/ns/api-abc", to_id="Pod/ns/api-abc-2", kind="owns"),
        TopologyEdge(from_id="Service/ns/api-svc", to_id="Pod/ns/api-abc-1", kind="routes_to"),
        TopologyEdge(from_id="Service/ns/api-svc", to_id="Pod/ns/api-abc-2", kind="routes_to"),
    ]
    return TopologyGraph(nodes=nodes, edges=edges)


class TestTopologyBuilder:
    def test_build_from_graph(self):
        builder = TopologyBuilder.__new__(TopologyBuilder)
        builder._G = nx.DiGraph()
        builder._topo = TopologyGraph()
        builder._settings = None
        builder.from_graph(build_small_graph())
        assert len(builder.graph().nodes) == 5
        assert len(builder.graph().edges) == 5

    def test_blast_radius_deployment_is_large(self):
        builder = TopologyBuilder(MagicMock())
        builder.from_graph(build_small_graph())
        br = builder.blast_radius("Deployment/ns/api")
        assert br > 0.5  # deployment owns most of the graph

    def test_blast_radius_pod_is_small(self):
        builder = TopologyBuilder(MagicMock())
        builder.from_graph(build_small_graph())
        br = builder.blast_radius("Pod/ns/api-abc-1")
        # A leaf pod has no outgoing edges, so only itself is reachable: 1/5 = 0.2
        assert br < 0.3

    def test_blast_radius_unknown_node(self):
        builder = TopologyBuilder(MagicMock())
        builder.from_graph(build_small_graph())
        assert builder.blast_radius("unknown") == 0.0

    def test_shortest_path_exists(self):
        builder = TopologyBuilder(MagicMock())
        builder.from_graph(build_small_graph())
        path = builder.shortest_path("Deployment/ns/api", "Pod/ns/api-abc-1")
        assert len(path) > 0
        assert path[0] == "Deployment/ns/api"
        assert path[-1] == "Pod/ns/api-abc-1"

    def test_shortest_path_no_path(self):
        builder = TopologyBuilder(MagicMock())
        builder.from_graph(build_small_graph())
        path = builder.shortest_path("Pod/ns/api-abc-1", "Deployment/ns/api")
        assert path == []  # directed: can't go upward

    def test_find_node(self):
        builder = TopologyBuilder(MagicMock())
        builder.from_graph(build_small_graph())
        node_id = builder.find_node("Pod", "api-abc-1", "ns")
        assert node_id == "Pod/ns/api-abc-1"

    def test_find_node_missing(self):
        builder = TopologyBuilder(MagicMock())
        builder.from_graph(build_small_graph())
        assert builder.find_node("Pod", "nonexistent", "ns") is None

    def test_owners_of_pod(self):
        builder = TopologyBuilder(MagicMock())
        builder.from_graph(build_small_graph())
        owners = builder.owners_of("Pod/ns/api-abc-1")
        assert "ReplicaSet/ns/api-abc" in owners

    def test_enrich_signals_blast_radius(self):
        builder = TopologyBuilder(MagicMock())
        builder.from_graph(build_small_graph())
        sig = Signal(
            type="signal",
            ts=T0,
            source=SignalSource.KUBE_API,
            kind=SignalKind.RESTART,
            severity=Severity.HIGH,
            target=Target(kind="Deployment", namespace="ns", name="api"),
            value=3.0,
            message="restarted",
        )
        enriched = builder.enrich_signals_with_blast_radius([sig])
        assert len(enriched) == 1
        _, br = enriched[0]
        assert br > 0.5
