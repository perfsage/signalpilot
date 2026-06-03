"""Kubernetes service topology graph builder.

Builds a directed topology graph from K8s API objects and uses it for
blast-radius scoring and dependency analysis.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import networkx as nx
from kubernetes import client

from signalpilot.models import TopologyGraph, TopologyNode, TopologyEdge, Signal

if TYPE_CHECKING:
    from signalpilot.config import Settings


class TopologyBuilder:
    """
    Builds a directed topology graph from K8s API objects.

    Nodes: Deployment, ReplicaSet, Pod, Service, Node
    Edges:
      - Deployment "owns" ReplicaSet (ownerReferences)
      - ReplicaSet "owns" Pod (ownerReferences)
      - Service "routes_to" Pod (selector matching pod labels)
      - Pod "runs_on" Node
    """

    def __init__(self, settings: "Settings"):
        self._settings = settings
        self._G: nx.DiGraph = nx.DiGraph()
        self._topo: TopologyGraph = TopologyGraph()

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build(self, namespace: str, api_client: Optional[client.ApiClient] = None) -> "TopologyBuilder":
        """Populate graph from live K8s API. Returns self for chaining."""
        core = client.CoreV1Api(api_client=api_client)
        apps = client.AppsV1Api(api_client=api_client)

        pods = core.list_namespaced_pod(namespace).items
        services = core.list_namespaced_service(namespace).items
        deployments = apps.list_namespaced_deployment(namespace).items
        replica_sets = apps.list_namespaced_replica_set(namespace).items

        def _node_id(kind: str, ns: str, name: str) -> str:
            return f"{kind}/{ns}/{name}"

        def _add_node(kind: str, name: str, ns: str, labels: dict) -> str:
            nid = _node_id(kind, ns, name)
            node = TopologyNode(id=nid, kind=kind, name=name, namespace=ns, labels=labels or {})
            self._topo.nodes.append(node)
            self._G.add_node(nid, **node.model_dump())
            return nid

        def _add_edge(from_id: str, to_id: str, kind: str) -> None:
            edge = TopologyEdge(from_id=from_id, to_id=to_id, kind=kind)
            self._topo.edges.append(edge)
            self._G.add_edge(from_id, to_id, kind=kind)

        # Deployments
        for dep in deployments:
            _add_node("Deployment", dep.metadata.name, namespace, dep.metadata.labels or {})

        # ReplicaSets + Deployment→ReplicaSet edges
        for rs in replica_sets:
            rs_id = _add_node("ReplicaSet", rs.metadata.name, namespace, rs.metadata.labels or {})
            for ref in rs.metadata.owner_references or []:
                owner_id = _node_id(ref.kind, namespace, ref.name)
                if owner_id in self._G:
                    _add_edge(owner_id, rs_id, "owns")

        # Pods
        pod_label_map: dict[str, dict] = {}
        for pod in pods:
            pod_id = _add_node("Pod", pod.metadata.name, namespace, pod.metadata.labels or {})
            pod_label_map[pod_id] = pod.metadata.labels or {}

            for ref in pod.metadata.owner_references or []:
                owner_id = _node_id(ref.kind, namespace, ref.name)
                if owner_id in self._G:
                    _add_edge(owner_id, pod_id, "owns")

            if pod.spec.node_name:
                node_nid = _node_id("Node", "", pod.spec.node_name)
                if node_nid not in self._G:
                    node_obj = TopologyNode(
                        id=node_nid, kind="Node", name=pod.spec.node_name,
                        namespace="", labels={},
                    )
                    self._topo.nodes.append(node_obj)
                    self._G.add_node(node_nid, **node_obj.model_dump())
                _add_edge(pod_id, node_nid, "runs_on")

        # Services → matching pods
        for svc in services:
            svc_id = _add_node("Service", svc.metadata.name, namespace, svc.metadata.labels or {})
            selector = svc.spec.selector or {}
            if not selector:
                continue
            for pod_id, pod_labels in pod_label_map.items():
                if all(pod_labels.get(k) == v for k, v in selector.items()):
                    _add_edge(svc_id, pod_id, "routes_to")

        return self

    def from_graph(self, topo: TopologyGraph) -> "TopologyBuilder":
        """Load from a pre-built TopologyGraph (for testing)."""
        self._topo = topo
        for node in topo.nodes:
            self._G.add_node(node.id, **node.model_dump())
        for edge in topo.edges:
            self._G.add_edge(edge.from_id, edge.to_id, kind=edge.kind)
        return self

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def graph(self) -> TopologyGraph:
        """Return the built TopologyGraph model."""
        return self._topo

    def blast_radius(self, node_id: str, max_depth: int = 3) -> float:
        """
        Estimate blast radius as fraction of total nodes reachable from this
        node (inclusive) within max_depth hops, divided by total nodes.

        Returns value in [0.0, 1.0].
        """
        if node_id not in self._G:
            return 0.0
        reachable = nx.single_source_shortest_path_length(self._G, node_id, cutoff=max_depth)
        return min(len(reachable) / max(len(self._G.nodes), 1), 1.0)

    def shortest_path(self, from_id: str, to_id: str) -> list[str]:
        """Return node IDs on the shortest path, or empty list if unreachable."""
        try:
            return nx.shortest_path(self._G, from_id, to_id)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def owners_of(self, node_id: str) -> list[str]:
        """Return node IDs that own this node (parent edges)."""
        return list(self._G.predecessors(node_id))

    def dependents_of(self, node_id: str) -> list[str]:
        """Return node IDs that depend on this node (children, one hop)."""
        return list(self._G.successors(node_id))

    def find_node(self, kind: str, name: str, namespace: str) -> Optional[str]:
        """Return the node ID for a K8s object, or None if not in graph."""
        for node_id, attrs in self._G.nodes(data=True):
            if (
                attrs.get("kind") == kind
                and attrs.get("name") == name
                and attrs.get("namespace") == namespace
            ):
                return node_id
        return None

    def enrich_signals_with_blast_radius(
        self, signals: list[Signal]
    ) -> list[tuple[Signal, float]]:
        """
        For each signal, look up the target node in the graph and compute blast_radius.
        Returns list of (signal, blast_radius_score) tuples.
        """
        results = []
        for signal in signals:
            node_id = self.find_node(
                signal.target.kind, signal.target.name, signal.target.namespace
            )
            br = self.blast_radius(node_id) if node_id else 0.0
            results.append((signal, br))
        return results
