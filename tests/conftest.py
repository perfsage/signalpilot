"""Shared pytest fixtures for SignalPilot tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from signalpilot.models import (
    CommitInfo,
    Finding,
    Fix,
    GitChange,
    LogCluster,
    Severity,
    Signal,
    SignalKind,
    SignalSource,
    Target,
)

NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_target() -> Target:
    return Target(kind="Deployment", namespace="prod", name="api-server")


@pytest.fixture
def sample_signal(sample_target: Target) -> Signal:
    return Signal(
        ts=NOW,
        source=SignalSource.KUBE_API,
        kind=SignalKind.RESTART,
        severity=Severity.HIGH,
        target=sample_target,
        value=5.0,
        message="Container restarted 5 times",
    )


@pytest.fixture
def sample_log_cluster() -> LogCluster:
    return LogCluster(
        fingerprint="abc123",
        template="Connection refused to <*>",
        count_before=0,
        count_after=42,
        is_new=True,
        sample_lines=["Connection refused to db:5432"],
        category="conn",
    )


@pytest.fixture
def sample_git_change() -> GitChange:
    return GitChange(
        repo="https://github.com/org/repo",
        from_sha="abc",
        to_sha="def",
        commits=[
            CommitInfo(sha="def", author="alice", message="feat: increase pool size", ts=NOW)
        ],
    )


@pytest.fixture
def sample_finding(sample_target: Target, sample_signal: Signal) -> Finding:
    return Finding(
        id="f-001",
        title="High restart rate after deployment",
        severity=Severity.HIGH,
        confidence=0.85,
        blast_radius=0.4,
        target=sample_target,
        evidence=[sample_signal],
        explanation="Container has restarted 5 times since the last deploy.",
        fixes=[
            Fix(
                description="Increase memory limit",
                kind="config",
                kubectl_snippet='kubectl set resources deployment api-server --limits=memory=512Mi',
                expected_improvement="Restart rate should drop to 0",
                current_value="256Mi",
                proposed_value="512Mi",
            )
        ],
        rule_id="oom_after_resource_reduction",
    )
