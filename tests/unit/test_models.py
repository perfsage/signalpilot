"""Comprehensive tests for all Pydantic v2 data models in signalpilot.models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from signalpilot.models import (
    Analysis,
    CommitInfo,
    DeployChange,
    Evidence,
    Finding,
    Fix,
    GitChange,
    ImageDiff,
    LogCluster,
    RegressionWindow,
    ResourceDiff,
    Severity,
    Signal,
    SignalKind,
    SignalSource,
    Target,
    TopologyEdge,
    TopologyGraph,
    TopologyNode,
)

NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Target
# ---------------------------------------------------------------------------

class TestTarget:
    def test_basic_instantiation(self) -> None:
        t = Target(kind="Deployment", namespace="prod", name="api")
        assert t.kind == "Deployment"
        assert t.namespace == "prod"
        assert t.name == "api"
        assert t.container is None

    def test_with_container(self) -> None:
        t = Target(kind="Pod", namespace="default", name="pod-abc", container="main")
        assert t.container == "main"

    def test_round_trip(self) -> None:
        t = Target(kind="Service", namespace="kube-system", name="svc")
        assert Target.model_validate(t.model_dump()) == t


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TestEnums:
    def test_severity_values(self) -> None:
        assert Severity.CRITICAL == "critical"
        assert Severity.INFO == "info"

    def test_signal_source_values(self) -> None:
        assert SignalSource.PROMETHEUS == "prometheus"
        assert SignalSource.GIT == "git"

    def test_signal_kind_values(self) -> None:
        assert SignalKind.OOM_KILLED == "oom_killed"
        assert SignalKind.TCP_RETRANSMIT == "tcp_retransmit"


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------

class TestSignal:
    def test_minimal_instantiation(self) -> None:
        target = Target(kind="Pod", namespace="prod", name="p")
        s = Signal(
            ts=NOW,
            source=SignalSource.KUBE_API,
            kind=SignalKind.RESTART,
            severity=Severity.HIGH,
            target=target,
            message="restarted",
        )
        assert s.value is None
        assert s.labels == {}
        assert s.raw is None

    def test_labels_default_factory(self) -> None:
        target = Target(kind="Pod", namespace="prod", name="p")
        s1 = Signal(ts=NOW, source=SignalSource.EVENTS, kind=SignalKind.EVENT,
                    severity=Severity.INFO, target=target, message="x")
        s2 = Signal(ts=NOW, source=SignalSource.EVENTS, kind=SignalKind.EVENT,
                    severity=Severity.INFO, target=target, message="y")
        # Default factory must produce independent dicts
        s1.labels["k"] = "v"
        assert "k" not in s2.labels

    def test_with_raw_any_type(self) -> None:
        target = Target(kind="Pod", namespace="ns", name="p")
        raw_obj = {"apiVersion": "v1", "kind": "Pod"}
        s = Signal(ts=NOW, source=SignalSource.KUBE_API, kind=SignalKind.PROBE_FAILURE,
                   severity=Severity.MEDIUM, target=target, message="probe failed", raw=raw_obj)
        assert s.raw == raw_obj

    def test_round_trip(self, sample_signal: Signal) -> None:
        data = sample_signal.model_dump()
        restored = Signal.model_validate(data)
        assert restored == sample_signal

    def test_invalid_source_raises(self) -> None:
        with pytest.raises(ValidationError):
            Signal(
                ts=NOW,
                source="nonexistent_source",  # type: ignore[arg-type]
                kind=SignalKind.RESTART,
                severity=Severity.HIGH,
                target=Target(kind="Pod", namespace="ns", name="p"),
                message="x",
            )


# ---------------------------------------------------------------------------
# LogCluster
# ---------------------------------------------------------------------------

class TestLogCluster:
    def test_basic(self) -> None:
        lc = LogCluster(
            fingerprint="fp1",
            template="Error connecting to <*>",
            count_before=0,
            count_after=100,
            is_new=True,
        )
        assert lc.sample_lines == []
        assert lc.category is None

    def test_sample_lines_max_length(self) -> None:
        lc = LogCluster(
            fingerprint="fp2",
            template="T",
            count_before=1,
            count_after=2,
            is_new=False,
            sample_lines=["a", "b", "c", "d", "e"],
        )
        assert len(lc.sample_lines) == 5

    def test_sample_lines_exceeds_max_raises(self) -> None:
        with pytest.raises(ValidationError):
            LogCluster(
                fingerprint="fp3",
                template="T",
                count_before=0,
                count_after=1,
                is_new=True,
                sample_lines=["a", "b", "c", "d", "e", "f"],  # 6 > max_length=5
            )

    def test_round_trip(self, sample_log_cluster: LogCluster) -> None:
        assert LogCluster.model_validate(sample_log_cluster.model_dump()) == sample_log_cluster


# ---------------------------------------------------------------------------
# GitChange / CommitInfo
# ---------------------------------------------------------------------------

class TestGitChange:
    def test_basic(self) -> None:
        gc = GitChange(repo="https://github.com/x/y", from_sha=None, to_sha="abc")
        assert gc.commits == []
        assert gc.suspect_commits == []
        assert gc.suspect_files == []

    def test_with_commits(self) -> None:
        commit = CommitInfo(sha="def", author="bob", message="fix: memory leak", ts=NOW)
        gc = GitChange(repo="r", from_sha="abc", to_sha="def", commits=[commit])
        assert gc.commits[0].sha == "def"

    def test_round_trip(self, sample_git_change: GitChange) -> None:
        assert GitChange.model_validate(sample_git_change.model_dump()) == sample_git_change


# ---------------------------------------------------------------------------
# ImageDiff / ResourceDiff / DeployChange
# ---------------------------------------------------------------------------

class TestDeployChange:
    def test_minimal(self) -> None:
        dc = DeployChange(
            deployment="api",
            namespace="prod",
            from_revision="3",
            to_revision="4",
            deploy_time=NOW,
        )
        assert dc.image_diffs == []
        assert dc.git is None

    def test_with_image_diff(self) -> None:
        dc = DeployChange(
            deployment="api",
            namespace="prod",
            from_revision=None,
            to_revision="1",
            deploy_time=NOW,
            image_diffs=[ImageDiff(from_image="img:1", to_image="img:2", tag_changed=True, digest_changed=True)],
        )
        assert dc.image_diffs[0].tag_changed is True

    def test_resource_diff(self) -> None:
        rd = ResourceDiff(
            container="app",
            from_cpu_request="100m", to_cpu_request="200m",
            from_cpu_limit=None, to_cpu_limit="500m",
            from_mem_request="128Mi", to_mem_request="256Mi",
            from_mem_limit="256Mi", to_mem_limit="512Mi",
        )
        dc = DeployChange(
            deployment="api", namespace="prod", from_revision="1", to_revision="2",
            deploy_time=NOW, resource_diffs=[rd],
        )
        assert dc.resource_diffs[0].container == "app"

    def test_replica_diff(self) -> None:
        dc = DeployChange(
            deployment="api", namespace="prod", from_revision="1", to_revision="2",
            deploy_time=NOW, replica_diff=(2, 4),
        )
        assert dc.replica_diff == (2, 4)

    def test_round_trip(self) -> None:
        dc = DeployChange(
            deployment="api", namespace="prod", from_revision="1", to_revision="2",
            deploy_time=NOW,
        )
        assert DeployChange.model_validate(dc.model_dump()) == dc

    def test_json_round_trip_with_complex_fields(self) -> None:
        dc = DeployChange(
            deployment="api",
            namespace="prod",
            from_revision="1",
            to_revision="2",
            deploy_time=NOW,
            env_diff={"PORT": ("8080", "9090"), "DEBUG": ("true", None)},
            replica_diff=(2, 4),
        )
        json_str = dc.model_dump_json()
        restored = DeployChange.model_validate_json(json_str)
        assert restored == dc
        assert restored.env_diff["PORT"] == ("8080", "9090")
        assert restored.replica_diff == (2, 4)


# ---------------------------------------------------------------------------
# Fix
# ---------------------------------------------------------------------------

class TestFix:
    def test_valid_kinds(self) -> None:
        for kind in ("patch", "rollback", "scale", "config", "code", "network", "info"):
            fix = Fix(description="do something", kind=kind)  # type: ignore[arg-type]
            assert fix.kind == kind

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(ValidationError):
            Fix(description="x", kind="unknown")  # type: ignore[arg-type]

    def test_optional_fields_default_none(self) -> None:
        fix = Fix(description="x", kind="info")
        assert fix.kubectl_snippet is None
        assert fix.yaml_snippet is None
        assert fix.expected_improvement is None


# ---------------------------------------------------------------------------
# Finding – confidence/blast_radius bounds + mixed Evidence
# ---------------------------------------------------------------------------

class TestFinding:
    def test_valid_confidence_bounds(self, sample_target: Target) -> None:
        for value in (0.0, 0.5, 1.0):
            f = Finding(id="x", title="t", severity=Severity.LOW,
                        confidence=value, blast_radius=0.5,
                        target=sample_target, explanation="e")
            assert f.confidence == value

    def test_confidence_below_zero_raises(self, sample_target: Target) -> None:
        with pytest.raises(ValidationError):
            Finding(id="x", title="t", severity=Severity.LOW,
                    confidence=-0.1, blast_radius=0.5,
                    target=sample_target, explanation="e")

    def test_confidence_above_one_raises(self, sample_target: Target) -> None:
        with pytest.raises(ValidationError):
            Finding(id="x", title="t", severity=Severity.LOW,
                    confidence=1.1, blast_radius=0.5,
                    target=sample_target, explanation="e")

    def test_blast_radius_below_zero_raises(self, sample_target: Target) -> None:
        with pytest.raises(ValidationError):
            Finding(id="x", title="t", severity=Severity.MEDIUM,
                    confidence=0.5, blast_radius=-0.01,
                    target=sample_target, explanation="e")

    def test_blast_radius_above_one_raises(self, sample_target: Target) -> None:
        with pytest.raises(ValidationError):
            Finding(id="x", title="t", severity=Severity.MEDIUM,
                    confidence=0.5, blast_radius=1.01,
                    target=sample_target, explanation="e")

    def test_mixed_evidence_types(
        self,
        sample_target: Target,
        sample_signal: Signal,
        sample_log_cluster: LogCluster,
        sample_git_change: GitChange,
    ) -> None:
        """Evidence list must accept Signal, LogCluster, and GitChange."""
        f = Finding(
            id="f-mix",
            title="Mixed evidence",
            severity=Severity.HIGH,
            confidence=0.9,
            blast_radius=0.7,
            target=sample_target,
            evidence=[sample_signal, sample_log_cluster, sample_git_change],
            explanation="Multiple correlated signals.",
        )
        assert len(f.evidence) == 3
        assert isinstance(f.evidence[0], Signal)
        assert isinstance(f.evidence[1], LogCluster)
        assert isinstance(f.evidence[2], GitChange)

    def test_evidence_union_discriminates(self) -> None:
        """model_validate must reconstruct the correct Evidence subtype."""
        target = Target(kind="Pod", namespace="ns", name="p")
        signal = Signal(ts=NOW, source=SignalSource.PROMETHEUS, kind=SignalKind.ERROR_RATE,
                        severity=Severity.CRITICAL, target=target, message="spike")
        finding = Finding(
            id="f-disc",
            title="Discriminator test",
            severity=Severity.CRITICAL,
            confidence=1.0,
            blast_radius=1.0,
            target=target,
            evidence=[signal],
            explanation="x",
        )
        data = finding.model_dump()
        restored = Finding.model_validate(data)
        assert isinstance(restored.evidence[0], Signal)
        assert restored.evidence[0].kind == SignalKind.ERROR_RATE

    def test_round_trip(self, sample_finding: Finding) -> None:
        data = sample_finding.model_dump()
        restored = Finding.model_validate(data)
        assert restored.id == sample_finding.id
        assert restored.confidence == sample_finding.confidence


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------

class TestTopology:
    def test_empty_graph(self) -> None:
        g = TopologyGraph()
        assert g.nodes == []
        assert g.edges == []

    def test_with_nodes_and_edges(self) -> None:
        n1 = TopologyNode(id="d1", kind="Deployment", name="api", namespace="prod")
        n2 = TopologyNode(id="s1", kind="Service", name="api-svc", namespace="prod")
        e = TopologyEdge(from_id="s1", to_id="d1", kind="routes_to")
        g = TopologyGraph(nodes=[n1, n2], edges=[e])
        assert len(g.nodes) == 2
        assert g.edges[0].kind == "routes_to"

    def test_round_trip(self) -> None:
        g = TopologyGraph(
            nodes=[TopologyNode(id="x", kind="Pod", name="p", namespace="ns")],
            edges=[TopologyEdge(from_id="x", to_id="x", kind="owns")],
        )
        assert TopologyGraph.model_validate(g.model_dump()) == g


# ---------------------------------------------------------------------------
# RegressionWindow
# ---------------------------------------------------------------------------

class TestRegressionWindow:
    def test_regression_flagged(self) -> None:
        rw = RegressionWindow(
            metric="cpu_usage",
            before_mean=0.1,
            after_mean=0.4,
            pct_change=3.0,
            z_score=4.5,
            is_regression=True,
        )
        assert rw.is_regression is True

    def test_no_regression(self) -> None:
        rw = RegressionWindow(
            metric="latency_p99",
            before_mean=100.0,
            after_mean=102.0,
            pct_change=0.02,
            z_score=0.5,
            is_regression=False,
        )
        assert rw.is_regression is False


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

class TestAnalysis:
    def test_minimal(self) -> None:
        a = Analysis(
            id="a-001",
            ts=NOW,
            namespace="staging",
            deploy_change=None,
        )
        assert a.narrative == ""
        assert a.findings == []
        assert a.regressions == []

    def test_with_findings(self, sample_finding: Finding) -> None:
        a = Analysis(
            id="a-002",
            ts=NOW,
            namespace="prod",
            deploy_change=None,
            findings=[sample_finding],
            sources_used=["kube_api", "prometheus"],
            duration_s=12.5,
        )
        assert len(a.findings) == 1
        assert a.sources_used == ["kube_api", "prometheus"]

    def test_round_trip(self, sample_finding: Finding) -> None:
        a = Analysis(
            id="a-003",
            ts=NOW,
            namespace="prod",
            deploy_change=None,
            findings=[sample_finding],
        )
        restored = Analysis.model_validate(a.model_dump())
        assert restored.id == "a-003"
        assert len(restored.findings) == 1


# ---------------------------------------------------------------------------
# Settings – read from env vars via monkeypatch
# ---------------------------------------------------------------------------

class TestSettings:
    def test_defaults(self) -> None:
        from signalpilot.config import Settings
        s = Settings()
        assert s.baseline_window_s == 1800
        assert s.analysis_window_s == 900
        assert s.regression_z_score_threshold == 2.0
        assert s.regression_min_pct_change == 0.20
        assert s.log_tail_lines == 5000
        assert s.gate_severity_threshold == "high"
        assert s.data_dir == ".signalpilot"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIGNALPILOT_BASELINE_WINDOW_S", "600")
        monkeypatch.setenv("SIGNALPILOT_PROMETHEUS_URL", "http://prometheus:9090")
        monkeypatch.setenv("SIGNALPILOT_LLM_PROVIDER", "openai")
        from signalpilot.config import Settings
        s = Settings()
        assert s.baseline_window_s == 600
        assert s.prometheus_url == "http://prometheus:9090"
        assert s.llm_provider == "openai"

    def test_none_optionals(self) -> None:
        from signalpilot.config import Settings
        s = Settings()
        assert s.kubeconfig is None
        assert s.loki_url is None
        assert s.jaeger_url is None
        assert s.llm_api_key is None

    def test_get_settings_helper(self) -> None:
        from signalpilot.config import get_settings
        s = get_settings()
        assert isinstance(s.baseline_window_s, int)
