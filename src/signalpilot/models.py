"""All Pydantic v2 data models for SignalPilot.

Defines the shared vocabulary used across every layer of the pipeline:
signals, deploy changes, log clusters, RCA findings, and topology graphs.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class SignalSource(str, Enum):
    KUBE_API = "kube_api"
    EVENTS = "events"
    METRICS_SERVER = "metrics_server"
    LOGS = "logs"
    CADVISOR = "cadvisor"
    PROMETHEUS = "prometheus"
    OTEL_TRACES = "otel_traces"
    LOKI = "loki"
    NETWORK = "network"
    GIT = "git"


class SignalKind(str, Enum):
    RESTART = "restart"
    OOM_KILLED = "oom_killed"
    CRASH_LOOP = "crash_loop"
    IMAGE_PULL_ERROR = "image_pull_error"
    PROBE_FAILURE = "probe_failure"
    PENDING_POD = "pending_pod"
    EVENT = "event"
    CPU_USAGE = "cpu_usage"
    CPU_THROTTLED = "cpu_throttled"
    MEM_USAGE = "mem_usage"
    MEM_WORKING_SET = "mem_working_set"
    LOG_ERROR_RATE = "log_error_rate"
    LOG_CLUSTER = "log_cluster"
    LATENCY_P95 = "latency_p95"
    LATENCY_P99 = "latency_p99"
    ERROR_RATE = "error_rate"
    DNS_LATENCY = "dns_latency"
    TCP_RETRANSMIT = "tcp_retransmit"
    DISK_PRESSURE = "disk_pressure"
    PSI_PRESSURE = "psi_pressure"
    NODE_CONDITION = "node_condition"


class Target(BaseModel):
    """Identifies a Kubernetes resource being observed."""

    kind: str
    namespace: str
    name: str
    container: Optional[str] = None


class Signal(BaseModel):
    """A single observable event or metric data point from a collector."""

    ts: datetime
    source: SignalSource
    kind: SignalKind
    severity: Severity
    target: Target
    value: Optional[float] = None
    message: str
    labels: dict[str, str] = Field(default_factory=dict)
    raw: Optional[Any] = None


class ImageDiff(BaseModel):
    """Records a container image change between two deployment revisions."""

    from_image: Optional[str]
    to_image: str
    tag_changed: bool
    digest_changed: bool


class ResourceDiff(BaseModel):
    """Records a CPU/memory resource request/limit change for a container."""

    container: str
    from_cpu_request: Optional[str]
    to_cpu_request: Optional[str]
    from_cpu_limit: Optional[str]
    to_cpu_limit: Optional[str]
    from_mem_request: Optional[str]
    to_mem_request: Optional[str]
    from_mem_limit: Optional[str]
    to_mem_limit: Optional[str]


class CommitInfo(BaseModel):
    """A single git commit associated with a deployment."""

    sha: str
    author: str
    message: str
    files_changed: list[str] = Field(default_factory=list)
    ts: Optional[datetime] = None


class GitChange(BaseModel):
    """Git diff between two deployment revisions, including suspect commits."""

    repo: str
    from_sha: Optional[str]
    to_sha: str
    commits: list[CommitInfo] = Field(default_factory=list)
    suspect_commits: list[CommitInfo] = Field(default_factory=list)
    suspect_files: list[str] = Field(default_factory=list)


class DeployChange(BaseModel):
    """Complete diff of a Kubernetes Deployment between two revisions."""

    deployment: str
    namespace: str
    from_revision: Optional[str]
    to_revision: str
    deploy_time: datetime
    image_diffs: list[ImageDiff] = Field(default_factory=list)
    env_diff: dict[str, tuple[Optional[str], Optional[str]]] = Field(default_factory=dict)
    resource_diffs: list[ResourceDiff] = Field(default_factory=list)
    config_ref_changes: list[str] = Field(default_factory=list)
    replica_diff: Optional[tuple[int, int]] = None
    git: Optional[GitChange] = None


class LogCluster(BaseModel):
    """A drain3-derived log template cluster comparing before/after deploy."""

    fingerprint: str
    template: str
    count_before: int
    count_after: int
    is_new: bool
    sample_lines: list[str] = Field(default_factory=list, max_length=5)
    category: Optional[str] = None


class Fix(BaseModel):
    """A concrete, actionable remediation for a finding."""

    description: str
    kind: Literal["patch", "scale", "config", "code", "network", "info"]
    kubectl_snippet: Optional[str] = None
    yaml_snippet: Optional[str] = None
    expected_improvement: Optional[str] = None
    current_value: Optional[str] = None
    proposed_value: Optional[str] = None


Evidence = Union[Signal, LogCluster, GitChange]


class Finding(BaseModel):
    """A ranked root-cause finding produced by the RCA engine."""

    id: str
    title: str
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    blast_radius: float = Field(ge=0.0, le=1.0)
    target: Target
    evidence: list[Evidence] = Field(default_factory=list)
    explanation: str
    fixes: list[Fix] = Field(default_factory=list)
    rule_id: Optional[str] = None


class TopologyNode(BaseModel):
    """A node in the cluster service/workload topology graph."""

    id: str
    kind: str
    name: str
    namespace: str
    labels: dict[str, str] = Field(default_factory=dict)


class TopologyEdge(BaseModel):
    """A directed relationship edge in the topology graph."""

    from_id: str
    to_id: str
    kind: str


class TopologyGraph(BaseModel):
    """Full workload topology: nodes (workloads/services) and edges (relationships)."""

    nodes: list[TopologyNode] = Field(default_factory=list)
    edges: list[TopologyEdge] = Field(default_factory=list)


class RegressionWindow(BaseModel):
    """Statistical regression result for a single metric over a deploy window."""

    metric: str
    before_mean: float
    after_mean: float
    pct_change: float
    z_score: float
    is_regression: bool


class Analysis(BaseModel):
    """Top-level RCA analysis result combining all signal sources and findings."""

    id: str
    ts: datetime
    namespace: str
    deploy_change: Optional[DeployChange]
    regressions: list[RegressionWindow] = Field(default_factory=list)
    log_clusters: list[LogCluster] = Field(default_factory=list)
    topology: Optional[TopologyGraph] = None
    findings: list[Finding] = Field(default_factory=list)
    narrative: str = ""
    sources_used: list[str] = Field(default_factory=list)
    duration_s: Optional[float] = None
